"""The Settings pop-up: language, answer model, currency, chat history and the knowledge base."""

import json

import streamlit as st

from backend import config
from backend.rag.ingest import build_index
from backend.storage import history
from frontend.components.common import (
    current_owner,
    export_markdown,
    model_label,
    prepare_index,
    start_new_chat,
)
from frontend.components.trip_form import CURRENCIES
from frontend.i18n import LANGUAGES, language, t

TESTED_MODEL = "anthropic/claude-haiku-5.5"


def _model_tags(model: str) -> str:
    tags = [t("set.tag.cloud")]
    if model == TESTED_MODEL:
        tags.append(t("set.tag.tested"))
    if model == config.OPENROUTER_MODEL:
        tags.append(t("set.tag.default"))
    return " · ".join(tags)


# (name, tags, detail) keys in frontend/i18n.py
CHECKS = [("set.guard", "set.guard_tags", "set.guard_text"),
          ("set.screening", "set.guard_tags", "set.screening_text")]


def _set_language() -> None:
    # Clicking the chosen language again would leave neither selected, so it's selected again instead.
    chosen = st.session_state.get("language-picker")
    if chosen:
        st.session_state.language = chosen
        # The whole page is redrawn in the new language, with Settings opened again (sidebar.py).
        st.session_state.language_changed = st.session_state.open_settings = True
    else:
        st.session_state["language-picker"] = language()


def settings_dialog() -> None:
    # Made on each call, so the pop-up's title follows the chosen language.
    st.dialog(t("set.title"), width="medium")(_settings)()


def _settings() -> None:
    st.markdown(f"**{t('set.language')}**")
    st.segmented_control("Language", list(LANGUAGES), format_func=LANGUAGES.get, default=language(),
                         key="language-picker", on_change=_set_language, label_visibility="collapsed")
    if st.session_state.pop("language_changed", False):
        st.rerun(scope="app")  # a pop-up only redraws itself; the sidebar and page change language too
    st.caption(t("set.language_help"))

    st.markdown(f"**{t('set.checks')}**")
    st.caption(t("set.checks_note"))
    for name, tags, detail in CHECKS:
        left, right = st.columns([3, 2])
        left.markdown(f"✓ {t(name)}")
        right.caption(t(tags))
        st.caption(t(detail))

    st.markdown(f"**{t('set.model')}**")
    st.caption(t("set.model_note"))
    models = list(config.MODELS)
    st.session_state.model = st.radio(
        "Model", models, index=models.index(st.session_state.model) if st.session_state.model in models else 0,
        label_visibility="collapsed", format_func=lambda m: f"{model_label(m)}  ·  {_model_tags(m)}")
    with st.container(key="model-note"):  # the orange bar comes from frontend/html/theme.css
        st.caption(t("set.model_warning", model=config.MODELS[TESTED_MODEL][0]))
        st.caption(t("set.model_prices"))

    st.markdown(f"**{t('set.currency')}**")
    st.session_state.currency = st.selectbox(
        "Currency", CURRENCIES, index=CURRENCIES.index(st.session_state.currency), label_visibility="collapsed",
        help=t("set.currency_help"))

    st.markdown(f"**{t('set.live')}**")
    budget = st.session_state.live_budget
    used = " · ".join(f"{name} {budget.used.get(name, 0)} {t('set.of')} {limit}"
                      for name, limit in budget.limits.items())
    st.caption(t("set.live_note", used=used))

    st.markdown(f"**{t('set.history')}**")
    st.caption(t("set.history_note"))
    if st.session_state.messages:
        left, right = st.columns(2)
        left.download_button(t("set.export_md"), export_markdown(st.session_state.messages),
                             file_name="tripmate_chat.md", width="stretch", icon=":material/download:")
        right.download_button(t("set.export_json"), json.dumps(st.session_state.messages, indent=2),
                              file_name="tripmate_chat.json", width="stretch", icon=":material/download:")
    confirm = st.checkbox(t("set.confirm_delete"))
    if st.button(t("set.delete_all"), icon=":material/delete:", disabled=not confirm):
        history.delete_all(current_owner())
        start_new_chat()
        st.rerun()

    with st.expander(t("set.kb")):
        st.caption(t("set.kb_note"))
        if st.button(t("set.kb_rebuild")):
            progress = st.progress(0.0, text=t("set.kb_progress"))
            count = build_index(on_progress=lambda done, total: progress.progress(
                done / total, text=t("set.kb_indexed", done=f"{done:,}", total=f"{total:,}")))
            prepare_index.clear()
            st.success(t("set.kb_done", count=f"{count:,}"))

    st.caption(t("set.applies"))
    if st.button(t("set.done"), type="primary", width="stretch"):
        st.rerun()
