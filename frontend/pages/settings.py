"""The Settings pop-up: answer model, currency, chat history and the knowledge base."""

import json

import streamlit as st

from backend import config
from backend.rag.ingest import build_index
from backend.storage import history
from frontend.components.common import current_owner, export_markdown, model_label, prepare_index, start_new_chat
from frontend.components.trip_form import CURRENCIES

TESTED_MODEL = "anthropic/claude-haiku-5.5"


def _model_tags(model: str) -> str:
    tags = ["cloud"]
    if model == TESTED_MODEL:
        tags.append("tested")
    if model == config.OPENROUTER_MODEL:
        tags.append("default")
    return " · ".join(tags)


CHECKS = [
    ("Input guard", "rules · always on",
     "Every message is checked before the model sees it: length, control characters and prompt-injection "
     "patterns. Refused messages are counted on the dashboard."),
    ("Tool result screening", "rules · always on",
     "Text from outside sources (listing names, place descriptions) is screened for injected instructions, "
     "links are kept only if they're http(s), and long text is trimmed."),
]


@st.dialog("Settings", width="medium")
def settings_dialog() -> None:
    st.markdown("**How each message is checked**")
    st.caption("Before the answer, so unsafe or off-limits input never reaches the model. These are rules, not a "
               "model, so they can't be switched.")
    for name, tags, detail in CHECKS:
        left, right = st.columns([3, 2])
        left.markdown(f"✓ {name}")
        right.caption(tags)
        st.caption(detail)

    st.markdown("**Model that writes the answers**")
    st.caption("It reads your question, calls the tools, and also writes the knowledge-base search queries. "
               "Prices are USD per million tokens (input / output).")
    models = list(config.MODELS)
    st.session_state.model = st.radio(
        "Model", models, index=models.index(st.session_state.model) if st.session_state.model in models else 0,
        label_visibility="collapsed", format_func=lambda m: f"{model_label(m)}  ·  {_model_tags(m)}")
    with st.container(key="model-note"):  # the orange bar comes from frontend/html/theme.css
        st.caption(f"TripMate was developed and evaluated with {config.MODELS[TESTED_MODEL][0]}, so its rules for "
                   "tools, costs and answer formats were tuned on it. Another model can do worse here: it may skip "
                   "a tool, cost a plan by itself or follow the answer formats less closely.")
        st.caption("Prices, totals and the plan checks always come from the tools, whichever model you choose.")

    st.markdown("**Currency**")
    st.session_state.currency = st.selectbox(
        "Currency", CURRENCIES, index=CURRENCIES.index(st.session_state.currency), label_visibility="collapsed",
        help="Budgets, trip totals and listing prices use this currency, at today's rate.")

    st.markdown("**Live searches**")
    budget = st.session_state.live_budget
    used = " · ".join(f"{name} {budget.used.get(name, 0)} of {limit}" for name, limit in budget.limits.items())
    st.caption(f"Allowed per chat, so one chat can't use up the monthly quota. This chat: {used}. Repeated "
               "searches come from the cache for free; a new chat starts again from zero.")

    st.markdown("**Chat history**")
    st.caption("Chats are saved on this computer in .history/chats.sqlite3 (not in git).")
    if st.session_state.messages:
        left, right = st.columns(2)
        left.download_button("Export chat (Markdown)", export_markdown(st.session_state.messages),
                             file_name="tripmate_chat.md", width="stretch", icon=":material/download:")
        right.download_button("Export chat (JSON)", json.dumps(st.session_state.messages, indent=2),
                              file_name="tripmate_chat.json", width="stretch", icon=":material/download:")
    confirm = st.checkbox("Yes, delete every saved chat and the dashboard log")
    if st.button("Delete all history", icon=":material/delete:", disabled=not confirm):
        history.delete_all(current_owner())
        start_new_chat()
        st.rerun()

    with st.expander("Knowledge base"):
        st.caption("Re-embeds every place from data/world/. Only needed after changing the data by hand; the app "
                   "adds new places by itself at startup.")
        if st.button("Rebuild knowledge base"):
            progress = st.progress(0.0, text="Re-indexing places...")
            count = build_index(on_progress=lambda done, total: progress.progress(
                done / total, text=f"Indexed {done:,} of {total:,} places"))
            prepare_index.clear()
            st.success(f"Indexed {count:,} places.")

    st.caption("Changes apply straight away.")
    if st.button("Done", type="primary", width="stretch"):
        st.rerun()
