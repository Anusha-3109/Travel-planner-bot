"""LLM client: LangChain's ChatOpenAI pointed at OpenRouter's OpenAI-compatible API,
plus the tokens and cost of each model reply."""

from langchain_openai import ChatOpenAI

import config


class LLMConfigError(RuntimeError):
    """Raised when the LLM cannot be created, for example because the API key is missing
    or the model isn't one the app offers."""


def model_name(model: str) -> str:
    return config.MODELS.get(model, (model,))[0]


def call_cost(model: str, input_tokens: int, output_tokens: int, reported: float | None) -> float | None:
    """A call's cost in USD: OpenRouter's own figure, or the model's price list when it sends none."""
    if reported is not None:
        return float(reported)
    _, input_price, output_price = config.MODELS.get(model, (model, None, None))
    if input_price is None or output_price is None:
        return None
    return (input_tokens * input_price + output_tokens * output_price) / 1_000_000


def message_usage(model: str, message) -> dict:
    """Tokens and cost of one model reply. cost_usd is None when neither OpenRouter
    nor the price list gives a cost."""
    usage = getattr(message, "usage_metadata", None) or {}
    reported = ((getattr(message, "response_metadata", None) or {}).get("token_usage") or {}).get("cost")
    tokens = {key: usage.get(key, 0) for key in ("input_tokens", "output_tokens", "total_tokens")}
    return {**tokens, "cost_usd": call_cost(model, tokens["input_tokens"], tokens["output_tokens"], reported)}


def add_usage(totals: dict, usage: dict) -> None:
    """Adds one reply's usage to running totals; the cost stays None once any part is unknown."""
    for key in ("input_tokens", "output_tokens", "total_tokens"):
        totals[key] = totals.get(key, 0) + usage.get(key, 0)
    if usage.get("total_tokens"):
        known = totals.get("cost_usd", 0.0) is not None and usage.get("cost_usd") is not None
        totals["cost_usd"] = round(totals.get("cost_usd", 0.0) + usage["cost_usd"], 6) if known else None


def get_llm(model: str | None = None) -> ChatOpenAI:
    if not config.OPENROUTER_API_KEY:
        raise LLMConfigError(
            "OPENROUTER_API_KEY is not set. Copy .env.example to .env and add your OpenRouter key."
        )
    model = model or config.OPENROUTER_MODEL
    if model not in config.MODELS:
        raise LLMConfigError(f"'{model}' isn't one of the models this app offers. Choose one in the sidebar.")
    return ChatOpenAI(
        model=model,
        api_key=config.OPENROUTER_API_KEY,
        base_url=config.OPENROUTER_BASE_URL,
        temperature=config.LLM_TEMPERATURE,
        timeout=config.LLM_TIMEOUT_SECONDS,
        max_retries=2,
    )
