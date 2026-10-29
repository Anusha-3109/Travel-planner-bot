"""Helpers shared by the pages: session state, the open chat, money and model labels."""

from datetime import datetime

import streamlit as st

from backend import config
from backend.accounts import accounts
from backend.live import fx
from backend.live.budget import SessionBudget
from backend.live.status import ServiceStatus, live_status
from backend.rag.ingest import ensure_index
from backend.security.rate_limit import RateLimiter
from backend.storage import history
from frontend.components import cookie
from frontend.i18n import DEFAULT_LANGUAGE, t

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
    st.session_state.setdefault("language", DEFAULT_LANGUAGE)
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


def google_enabled() -> bool:
    """True when Google sign-in is set up ([auth] in .streamlit/secrets.toml)."""
    try:
        return "auth" in st.secrets
    except Exception:  # no secrets file: a computer without sign-in
        return False


def sign_in_enabled() -> bool:
    """True when everyone signs in first: Google sign-in is set up, or password accounts are turned on
    (PASSWORD_ACCOUNTS). Password accounts always come with Google sign-in."""
    return google_enabled() or config.PASSWORD_ACCOUNTS


def signed_in_user() -> dict | None:
    """The signed-in user's details (name, email, how they signed in), or None when nobody is signed in
    or sign-in isn't set up. A password account is in the session after signing in, or comes back
    from this browser's remember-me cookie."""
    if not sign_in_enabled():
        return None
    if google_enabled() and st.user.get("is_logged_in"):
        return {"name": st.user.get("name"), "email": st.user.get("email") or "", "via": "google"}
    account = st.session_state.get("account")
    if account is None and "cookie" not in st.session_state and (token := cookie.remembered_token()):
        account = st.session_state.account = accounts.remembered_account(token)
    if account:
        return {"name": account["username"], "email": account["email"], "via": "password"}
    return None


def sign_out() -> None:
    """Signs out of Google, or ends a password sign-in and its remember-me cookie."""
    if user := signed_in_user():
        if user["via"] == "google":
            st.logout()
            return
        accounts.forget(st.session_state.get("cookie") or cookie.remembered_token())
        cookie.delete()
        st.session_state.account = None


def is_owner() -> bool:
    """True when the signed-in user is the app's owner (OWNER_EMAIL), who confirms new accounts."""
    user = signed_in_user()
    return bool(user and config.OWNER_EMAIL and user["email"].strip().lower() == config.OWNER_EMAIL.strip().lower())


def current_owner() -> str:
    """Whose chats and trips to show: the signed-in user, or "local" without sign-in."""
    if user := signed_in_user():
        return history.owner_for(user["email"])
    return history.LOCAL_OWNER


def open_chat(chat_id: str) -> bool:
    """Loads a saved chat into the session. False if it no longer exists or isn't the user's."""
    chat = history.load_chat(chat_id, current_owner())
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
        return t("cost.not_reported")
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
