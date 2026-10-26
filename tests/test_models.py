"""Model choice and token cost: OpenRouter's reported cost, the price-list fallback and the app display."""

import pytest
from langchain_core.messages import AIMessage

import config
from agent import agent as agent_module
from agent.llm import LLMConfigError, add_usage, call_cost, get_llm, message_usage
from agent.agent import run_agent
from rag.retriever import SearchPlan, plan_search

HAIKU = "anthropic/claude-haiku-5.5"


def _reply(content="", cost=None, tokens=(1000, 200)):
    metadata = {"token_usage": {"cost": cost}} if cost is not None else {}
    return AIMessage(content=content, response_metadata=metadata,
                     usage_metadata={"input_tokens": tokens[0], "output_tokens": tokens[1],
                                     "total_tokens": sum(tokens)})


def test_offered_models_all_have_names_and_prices():
    assert config.MODELS[HAIKU] == ("Claude Haiku 5.5", 0.10, 0.50)
    assert len(config.MODELS) == 3 and "anthropic/claude-sonnet-5.5" not in config.MODELS
    assert all(name and price is not None for name, price, _ in config.MODELS.values())


def test_reported_cost_wins_over_the_price_list():
    assert call_cost(HAIKU, 1000, 200, 0.00042) == 0.00042
    assert call_cost(HAIKU, 1000, 200, None) == pytest.approx((1000 * 0.10 + 200 * 0.50) / 1e6)
    assert call_cost("someone/unknown-model", 1000, 200, None) is None


def test_usage_is_added_up_and_an_unknown_cost_stays_unknown():
    totals = {"input_tokens": 0, "output_tokens": 0, "total_tokens": 0, "cost_usd": 0.0}
    add_usage(totals, message_usage(HAIKU, _reply(cost=0.0002)))
    add_usage(totals, message_usage(HAIKU, _reply()))  # no reported cost: priced from the list
    assert totals["total_tokens"] == 2400 and totals["cost_usd"] == pytest.approx(0.0002 + 0.0002)
    add_usage(totals, message_usage("someone/unknown-model", _reply()))
    assert totals["cost_usd"] is None and totals["total_tokens"] == 3600


def test_models_outside_the_list_are_refused(monkeypatch):
    monkeypatch.setattr(config, "OPENROUTER_API_KEY", "test-key")
    with pytest.raises(LLMConfigError, match="isn't one of the models"):
        get_llm("someone/unknown-model")
    assert get_llm("openai/gpt-6-luna").model_name == "openai/gpt-6-luna"


def test_agent_uses_the_chosen_model_and_reports_its_cost(monkeypatch):
    chosen = []

    class OneReply:
        def bind_tools(self, tools):
            return self

        def invoke(self, messages):
            return _reply("Hello!", cost=0.0013)

    monkeypatch.setattr(agent_module, "get_llm", lambda model=None: chosen.append(model) or OneReply())
    result = run_agent("Hello, can you help me plan a trip?", model="google/gemini-3.7-flash")
    assert chosen == ["google/gemini-3.7-flash"] and result.model == "google/gemini-3.7-flash"
    assert result.token_usage["cost_usd"] == 0.0013 and result.token_usage["total_tokens"] == 1200


def test_query_translation_reply_is_kept_for_the_totals():
    raw = _reply(cost=0.00001)

    class Translator:
        def with_structured_output(self, schema, include_raw=False):
            assert include_raw
            return self

        def invoke(self, prompt):
            return {"raw": raw, "parsed": SearchPlan(queries=["art museums"]), "parsing_error": None}

    replies = []
    plan = plan_search("museums in Boston", Translator(), replies)
    assert replies == [raw] and plan.queries == ["museums in Boston", "art museums"]
