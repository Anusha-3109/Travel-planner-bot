"""What the user sees when things go wrong: OpenRouter errors, a crashing tool, the step limit,
a missing key and failing live services. Also that follow-up questions get the chat history."""

import json
import re

import httpx
import openai
import pytest
from langchain_core.messages import AIMessage, HumanMessage

import backend.agent.agent as agent_module
from backend import config
from backend.agent.agent import AgentError, run_agent
from backend.agent.llm import LLMConfigError, get_llm
from backend.live import http
from backend.security.validation import InputValidationError
from backend.tools.destinations import search_destination_options
from backend.tools.local_transport import find_local_transport, get_local_transport
from tests.test_agent import ScriptedLLM

REQUEST = httpx.Request("POST", "https://openrouter.ai/api/v1/chat/completions")


def _status(error_class, code: int, message: str = "error"):
    return error_class(message, response=httpx.Response(code, request=REQUEST), body=None)


class FailingLLM(ScriptedLLM):
    def __init__(self, error):
        super().__init__([])
        self.error = error

    def invoke(self, messages):
        raise self.error


@pytest.mark.parametrize("error, shown", [
    (_status(openai.AuthenticationError, 401), "API key was rejected"),
    (_status(openai.RateLimitError, 429), "rate limited"),
    (openai.APITimeoutError(request=REQUEST), "Couldn't reach OpenRouter"),
    (openai.APIConnectionError(request=REQUEST), "Couldn't reach OpenRouter"),
    (_status(openai.NotFoundError, 404, "No endpoints found for model xyz"), "isn't available on OpenRouter"),
    (_status(openai.InternalServerError, 500), "returned an error (HTTP 500)"),
])
def test_openrouter_errors_become_clear_messages(monkeypatch, error, shown):
    monkeypatch.setattr(agent_module, "get_llm", lambda model=None: FailingLLM(error))
    with pytest.raises(AgentError, match=re.escape(shown)):
        run_agent("Flights from London to Rome?")


def test_missing_openrouter_key_has_a_setup_message(monkeypatch):
    monkeypatch.setattr(config, "OPENROUTER_API_KEY", "")
    with pytest.raises(LLMConfigError, match="OPENROUTER_API_KEY is not set"):
        get_llm()


def test_llm_uses_openrouter_and_the_chosen_model(monkeypatch):
    monkeypatch.setattr(config, "OPENROUTER_API_KEY", "test-key")
    llm = get_llm("anthropic/claude-haiku-5.5")
    assert llm.model_name == "anthropic/claude-haiku-5.5" and "openrouter.ai" in str(llm.openai_api_base)


def test_follow_up_questions_get_the_recent_history(monkeypatch):
    llm = ScriptedLLM([AIMessage(content="Here is a cheaper one.")])
    monkeypatch.setattr(agent_module, "get_llm", lambda model=None: llm)
    history = [{"role": "user", "content": f"question {i}"} if i % 2 == 0 else
               {"role": "assistant", "content": f"answer {i}"} for i in range(12)]
    run_agent("Make it cheaper", history=history)
    sent = llm.calls[0]  # the list keeps growing after the call, so cut it at the question
    texts = [m.content for m in sent[1:]]
    texts = texts[:texts.index("Make it cheaper") + 1]
    assert len(texts) == agent_module.MAX_HISTORY_MESSAGES + 1  # only the most recent turns
    assert texts[0] == "question 4" and isinstance(sent[1], HumanMessage)


def test_a_crashing_tool_returns_a_safe_error(monkeypatch):
    def crash(*args):
        raise KeyError("internal detail")
    monkeypatch.setattr(agent_module, "_run_tool", crash)
    llm = ScriptedLLM([AIMessage(content="", tool_calls=[{"name": "search_flights", "args": {}, "id": "c1"}]),
                       AIMessage(content="Sorry, flights are unavailable.")])
    monkeypatch.setattr(agent_module, "get_llm", lambda model=None: llm)
    result = run_agent("Flights?")
    assert json.loads(result.tool_calls[0].output) == {"error": "The search_flights tool failed unexpectedly."}
    assert result.answer == "Sorry, flights are unavailable."


def test_step_limit_forces_an_answer(monkeypatch):
    monkeypatch.setattr(config, "MAX_AGENT_STEPS", 2)
    monkeypatch.setattr(agent_module, "_run_tool", lambda *a: json.dumps({"ok": True}))
    loop = AIMessage(content="", tool_calls=[{"name": "search_flights", "args": {}, "id": "c"}])
    llm = ScriptedLLM([loop, loop, AIMessage(content="Best answer with what I have.")])
    monkeypatch.setattr(agent_module, "get_llm", lambda model=None: llm)
    steps = []
    result = run_agent("Flights?", on_step=steps.append)
    assert result.answer == "Best answer with what I have." and "Writing the answer..." in steps
    assert "Tool budget reached" in llm.calls[-1][-1].content


# --- fallbacks in the place and transport tools ------------------------------------------

def test_place_search_reports_bad_input_as_text():
    assert search_destination_options.invoke({"query": "museums", "category": "weather"}).startswith("Error:")


def test_failing_google_routes_falls_back_to_an_estimate(monkeypatch):
    monkeypatch.setattr(config, "GOOGLE_MAPS_API_KEY", "test-key")
    monkeypatch.setattr("backend.tools.local_transport.search_local_transport",
                        lambda *a: (_ for _ in ()).throw(http.LiveDataError("Google Routes is down")))
    result = find_local_transport("Washington", "Myrtle Beach")
    assert result["transport_source"] == "estimate" and "Google Routes is down" in result["note"]


def test_transport_tool_returns_errors_as_json():
    assert "error" in json.loads(get_local_transport.invoke({"origin": "12345", "destination": "Colosseum"}))
    with pytest.raises(InputValidationError):
        find_local_transport("Colosseum", "Vatican Museums", city="Rome; DROP")
