"""The app's screen, checked with Streamlit's test runner, and the text the trip form sends."""

from datetime import date, timedelta

import pytest
from streamlit.testing.v1 import AppTest

import config
from trip_form import example_questions, trip_question


@pytest.fixture
def app(monkeypatch):
    """The app with a placeholder OpenRouter key and no index build, so it renders without network calls."""
    monkeypatch.setattr(config, "OPENROUTER_API_KEY", "test-key")
    monkeypatch.setattr("rag.ingest.ensure_index", lambda on_progress=None: 0)
    at = AppTest.from_file("../app.py", default_timeout=30)
    at.run()
    assert not at.exception
    return at


def test_trip_question_names_dates_currency_and_stay():
    question = trip_question("London", "Rome", date(2026, 11, 10), 4, 2, 1500, "EUR", "Airbnb",
                             house_rule="pets", cuisines=["Italian"])
    assert question.startswith("Plan a 4-night trip from London to Rome, 2026-11-10 to 2026-11-14, for 2 people")
    assert "budget of EUR 1,500" in question and "an Airbnb" in question
    assert "allow pets" in question and "Italian cuisine" in question
    assert "a hotel" in trip_question("London", "Rome", date(2026, 11, 10), 1, 1, 500, "GBP", "Hotel")


def test_examples_use_dates_from_today():
    examples = example_questions(date(2026, 10, 23))
    assert "starting 06 November 2026" in examples[0] and "22 November 2026" in examples[1]
    assert examples[-1].endswith("(snapshot data).")


def test_sidebar_has_currency_and_future_trip_form(app):
    assert app.sidebar.selectbox[0].label == "Currency" and app.sidebar.selectbox[0].value == "USD"
    start = next(d for d in app.sidebar.date_input if d.label == "Start date")
    assert start.value == date.today() + timedelta(days=14)
    assert {t.label: t.value for t in app.sidebar.text_input} == {"From": "London", "To": "Rome"}


def test_changing_currency_updates_the_budget_label(app):
    app.sidebar.selectbox[0].set_value("EUR").run()
    assert app.session_state.currency == "EUR"
    assert "Budget (EUR)" in [n.label for n in app.sidebar.number_input]


def test_example_buttons_are_shown(app):
    labels = [b.label for b in app.button]
    assert example_questions()[0] in labels and example_questions()[-1] in labels
