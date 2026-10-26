"""Helpers shared by the pages: session state, the open chat, money and model labels."""

from datetime import datetime

import streamlit as st

import config
import history
from live import fx
from live.budget import SessionBudget
from live.status import ServiceStatus, live_status
from rag.ingest import ensure_index
from security.rate_limit import RateLimiter


PAGES: dict = {}  # the app's pages by name, filled in by app.py, for links between pages


@st.cache_resource(show_spinner="Updating the knowledge base (the first run embeds every place and takes a while)...")
def prepare_index() -> int:
    return ensure_index()


@st.cache_data(ttl=300, show_spinner=False)
def cached_live_status() -> list[ServiceStatus]:
    # Re-checked every 5 minutes. The SerpApi check is free and doesn't use a search.
    return live_status()


def init_state() -> None:
    st.session_state.setdefault("messages", [])
    st.session_state.setdefault("chat_id", None)
    st.session_state.setdefault("rate_limiter", RateLimiter())
    st.session_state.setdefault("live_budget", SessionBudget())
    st.session_state.setdefault("currency", "USD")
    st.session_state.setdefault("model", config.OPENROUTER_MODEL)
    st.session_state.setdefault("mode", "plan")


def mode_key(chat_id: str | None) -> str:
    """The Plan / Explore switch's widget key for a chat (one per chat, so each starts from its own mode)."""
    return f"mode-{chat_id or 'new'}"


def set_mode(mode: str) -> None:
    """Sets the mode and the switch showing it, so the switch doesn't reset it on the next run."""
    st.session_state.mode = mode
    st.session_state[mode_key(st.session_state.get("chat_id"))] = mode


def start_new_chat() -> None:
    st.session_state.messages = []
    st.session_state.chat_id = None
    st.session_state.live_budget = SessionBudget()  # a new chat gets a fresh live search limit
    set_mode("plan")
    st.query_params.clear()


def open_chat(chat_id: str) -> bool:
    """Loads a saved chat into the session. False if it no longer exists."""
    chat = history.load_chat(chat_id)
    if chat is None:
        return False
    st.session_state.messages = chat["messages"]
    st.session_state.chat_id = chat_id
    st.session_state.mode = chat.get("mode") or "plan"
    st.session_state.live_budget = SessionBudget()
    return True


def sync_chat_with_url() -> None:
    """The page address carries the open chat (?chat=...), so a refresh reopens it."""
    wanted = st.query_params.get("chat")
    if wanted and wanted != st.session_state.chat_id and not open_chat(wanted):
        start_new_chat()


def chat_totals(messages: list[dict]) -> dict:
    totals = {"input_tokens": 0, "output_tokens": 0, "cost_usd": 0.0}
    for message in messages:
        usage = message.get("token_usage") or {}
        totals["input_tokens"] += usage.get("input_tokens", 0)
        totals["output_tokens"] += usage.get("output_tokens", 0)
        if totals["cost_usd"] is not None and usage.get("total_tokens"):
            cost = usage.get("cost_usd")
            totals["cost_usd"] = None if cost is None else totals["cost_usd"] + cost
    return totals


def cost_text(cost_usd: float | None) -> str:
    """A model cost such as "$0.0021 (≈ EUR 0.0019)"; costs are tiny, so four decimals."""
    if cost_usd is None:
        return "not reported"
    text = r"\$" + f"{cost_usd:,.4f}"  # escaped: Streamlit reads text between two "$" as LaTeX
    currency = st.session_state.get("currency", "USD")
    if currency != "USD":
        try:
            text += f" (≈ {currency} {fx.get_rates().convert(cost_usd, 'USD', currency):,.4f})"
        except Exception:  # no exchange rate: the USD cost alone is enough
            pass
    return text


def show_markdown(text: str) -> None:
    # Streamlit treats text between two "$" signs as LaTeX, which garbles prices like "$1,200 ... $78".
    st.markdown(text.replace("$", r"\$"))


def model_label(model: str) -> str:
    name, input_price, output_price = config.MODELS[model]
    # Labels are Markdown, where two "$" signs would start a formula, so they're escaped.
    return name if input_price is None else rf"{name} (\${input_price:g} / \${output_price:g})"


def export_markdown(messages: list[dict]) -> str:
    lines = [f"# TripMate conversation ({datetime.now():%Y-%m-%d %H:%M})", ""]
    for message in messages:
        lines += [f"## {message['role'].title()}", "", message["content"], ""]
        for source in message.get("sources") or []:
            lines.append(f"- Source: {source['source']}")
    return "\n".join(lines)
