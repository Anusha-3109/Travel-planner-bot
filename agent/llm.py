"""LLM client: LangChain's ChatOpenAI pointed at OpenRouter's OpenAI-compatible API."""

from langchain_openai import ChatOpenAI

import config


class LLMConfigError(RuntimeError):
    """Raised when the LLM cannot be created, for example because the API key is missing."""


def get_llm(model: str | None = None) -> ChatOpenAI:
    if not config.OPENROUTER_API_KEY:
        raise LLMConfigError(
            "OPENROUTER_API_KEY is not set. Copy .env.example to .env and add your OpenRouter key."
        )
    return ChatOpenAI(
        model=model or config.OPENROUTER_MODEL,
        api_key=config.OPENROUTER_API_KEY,
        base_url=config.OPENROUTER_BASE_URL,
        temperature=config.LLM_TEMPERATURE,
        timeout=config.LLM_TIMEOUT_SECONDS,
        max_retries=2,
    )
