"""English and German: the dictionary, the language buttons, German pages and the agent's language rules."""

import re
import string
from datetime import date

from streamlit.testing.v1 import AppTest

from backend.agent.agent import system_prompt
from backend.rag.retriever import SearchPlan
from frontend.i18n import EXPLORE_EXAMPLES, LANGUAGES, TEXTS, step_text


def _fields(text: str) -> set[str]:
    return {name for _, name, _, _ in string.Formatter().parse(text) if name}


def test_every_text_has_both_languages_with_the_same_placeholders():
    for key, texts in TEXTS.items():
        assert set(texts) == set(LANGUAGES), key
        assert all(texts.values()), key
        assert _fields(texts["en"]) == _fields(texts["de"]), key
    assert len(EXPLORE_EXAMPLES["en"]) == len(EXPLORE_EXAMPLES["de"])


def test_every_key_the_pages_use_exists():
    """Every t("...") with a fixed key in the translated files is in the dictionary."""
    from pathlib import Path
    root = Path(__file__).resolve().parents[1]
    files = ["frontend/pages/chat.py", "frontend/pages/settings.py", "frontend/components/cards.py",
             "frontend/components/sidebar.py", "frontend/components/trip_form.py", "frontend/components/common.py",
             "frontend/pages/sign_in.py"]
    used = {key for f in files for key in re.findall(r"""\bt\(["']([a-z_.]*[a-z_])["']""", (root / f).read_text("utf-8"))}
    assert used and used <= set(TEXTS), used - set(TEXTS)


def test_progress_messages_are_translated():
    def script():
        import streamlit as st

        from frontend.i18n import step_text
        st.session_state.language = "de"
        st.markdown(step_text("Searching live flights..."))
        st.markdown(step_text("Working on your answer (step 3)..."))
        st.markdown(step_text("Something new..."))

    at = AppTest.from_function(script, default_timeout=30)
    at.run()
    assert [m.value for m in at.markdown] == ["Suche Live-Flüge...", "Arbeite an deiner Antwort (Schritt 3)...",
                                              "Something new..."]
    assert step_text("Searching live flights...") == "Searching live flights..."  # English by default


def test_german_examples_have_german_dates():
    from frontend.components.trip_form import example_questions
    examples = example_questions(date(2026, 10, 23), lang="de")
    assert "ab dem 6. November 2026" in examples[0] and "am 22. November 2026" in examples[1]
    assert example_questions(mode="explore", lang="de")[0] == "Museen für Kinder in Chicago."


def test_the_agent_answers_in_german_but_searches_in_english():
    prompt = system_prompt(date(2026, 10, 23), language="de")
    assert "Write your answer in German" in prompt and "Vienna, not Wien" in prompt
    assert "Language:" not in system_prompt(date(2026, 10, 23))  # no rule in English
    fields = SearchPlan.model_fields
    assert "in English" in fields["queries"].description and "Vienna, not Wien" in fields["city"].description


def test_the_language_reaches_the_agent(monkeypatch):
    from backend import config
    from backend.agent.agent import AgentResult
    monkeypatch.setattr(config, "OPENROUTER_API_KEY", "test-key")
    monkeypatch.setattr(config, "APP_PASSWORD", "")
    monkeypatch.setattr("frontend.components.common.ensure_index", lambda on_progress=None: 0)
    asked = []

    def answer(question, **kwargs):
        asked.append(kwargs)
        return AgentResult(answer="Antwort", model=kwargs["model"])
    monkeypatch.setattr("frontend.pages.chat.run_agent", answer)

    at = AppTest.from_file("../app.py", default_timeout=30)
    at.session_state.language = "de"
    at.run()
    at.chat_input(key="composer-input").set_value("Museen in Wien").run()
    assert asked[-1]["language"] == "de"


def _german_app(monkeypatch):
    from backend import config
    monkeypatch.setattr(config, "OPENROUTER_API_KEY", "test-key")
    monkeypatch.setattr(config, "APP_PASSWORD", "")
    monkeypatch.setattr("frontend.components.common.ensure_index", lambda on_progress=None: 0)
    at = AppTest.from_file("../app.py", default_timeout=30)
    at.session_state.language = "de"
    at.run()
    assert not at.exception
    return at


def test_the_chat_page_and_sidebar_in_german(monkeypatch):
    at = _german_app(monkeypatch)
    labels = [b.label for b in at.main.button]
    assert "Stattdessen das Reiseformular ausfüllen" in labels and "Ausprobieren" in labels
    text = " ".join(m.value for m in at.markdown)
    assert "**Probier eines davon**" in text and "**Was TripMate kann**" in text and "KI-Planung" in text
    assert at.button_group[0].options[0].endswith("Planen")
    sidebar = [b.label for b in at.sidebar.button]
    assert "Neuer Chat" in sidebar and "Einstellungen" in sidebar
    assert [link.proto.label for link in at.sidebar.get("page_link")][0] == "Meine Reisen"


def test_settings_switch_the_language_with_buttons():
    def page():
        from frontend.components.common import init_state
        from frontend.pages.settings import settings_dialog
        init_state()
        settings_dialog()

    at = AppTest.from_function(page, default_timeout=30)
    at.run()
    picker = at.button_group(key="language-picker")
    assert picker.value == "en" and "**Language**" in [m.value for m in at.markdown]
    picker.set_value("de").run()
    assert at.session_state.language == "de"
    assert "**Sprache**" in [m.value for m in at.markdown] and "**Währung**" in [m.value for m in at.markdown]


def test_cards_and_follow_ups_in_german():
    def script():
        import streamlit as st

        from frontend.components.cards import follow_up, render_result_cards
        st.session_state.language = "de"
        cost = {"people": 2, "total_text": "EUR 742.80", "budget": 900, "budget_text": "EUR 900.00",
                "remaining_budget": 157.2, "remaining_text": "EUR 157.20", "items": [], "unpriced_items": []}
        render_result_cards([{"name": "calculate_trip_cost", "args": {}, "output": __import__("json").dumps(cost)}])
        st.markdown(follow_up("restaurant", {"id": "restaurant-1", "name": "Figlmüller"}, {}, {"days": []}, 2,
                              "dinner"))

    at = AppTest.from_function(script, default_timeout=30)
    at.run()
    assert not at.exception
    assert {m.label for m in at.metric} == {"Gesamt", "Budget", "Übrig"}
    assert at.expander[0].label == "Kostenaufstellung"
    assert at.markdown[-1].value == ("Nimm Figlmüller (restaurant-1) als Abendessen an Tag 2 und aktualisiere den "
                                     "Plan und seine Kosten.")
