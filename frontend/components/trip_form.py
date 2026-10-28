"""The trip form pop-up, the currencies it offers and the example questions on an empty chat.

The trip request text itself is built by backend/agent/trip_request.py.
"""

from datetime import date, timedelta

import streamlit as st

from backend import config
from backend.agent.trip_request import trip_question
from backend.security.validation import InputValidationError, validate_city
from backend.travel_data.catalog import HOUSE_RULES, ROOM_TYPES, TRANSPORT_RULES
from frontend.i18n import EXPLORE_EXAMPLES, language, t

CUISINES = ["American", "Chinese", "French", "Indian", "Italian", "Japanese", "Mediterranean", "Mexican", "Spanish",
            "Thai"]
CURRENCIES = ["USD", "EUR", "GBP", "INR", "JPY", "AUD", "CAD", "CHF", "SGD", "AED", "THB"]
GERMAN_MONTHS = ("Januar", "Februar", "März", "April", "Mai", "Juni", "Juli", "August", "September", "Oktober",
                 "November", "Dezember")


def _german_date(day: date, year: bool = True) -> str:
    return f"{day.day}. {GERMAN_MONTHS[day.month - 1]}" + (f" {day.year}" if year else "")


def example_questions(today: date | None = None, mode: str = "plan", lang: str | None = None) -> list[str]:
    """Examples with dates worked out from today, so the live examples always work. Explore mode
    has its own examples, which need no flights or stays. In the chosen language unless lang is given."""
    lang = lang or language()
    if mode == "explore":
        return list(EXPLORE_EXAMPLES[lang])
    today = today or date.today()
    soon, later = today + timedelta(days=14), today + timedelta(days=30)
    if lang == "de":
        return [
            f"Plane eine Reise mit 4 Nächten von London nach Rom ab dem {_german_date(soon)} für 2 Personen mit "
            "einem Budget von 1.500.",
            f"Flüge von New York nach Tokio am {_german_date(later)}.",
            f"Finde ein Airbnb in Paris vom {_german_date(soon, year=False)} bis zum "
            f"{_german_date(soon + timedelta(days=3))} für 2 Personen.",
            EXPLORE_EXAMPLES["de"][1],
            EXPLORE_EXAMPLES["de"][3],
            f"Plane eine 3-tägige Reise von Washington nach Myrtle Beach ab dem {_german_date(later)} für 1 Person "
            "mit einem Budget von 1.400 $.",
        ]
    return [
        f"Plan a 4-night trip from London to Rome starting {soon:%d %B %Y} for 2 people with a budget of 1,500.",
        f"Flights from New York to Tokyo on {later:%d %B %Y}.",
        f"Find an Airbnb in Paris from {soon:%d %B} to {soon + timedelta(days=3):%d %B %Y} for 2 people.",
        "Sushi restaurants in Tokyo rated 4.5 or more.",
        "How do I get from Fiumicino Airport to the Colosseum?",
        f"Plan a 3-day trip from Washington to Myrtle Beach starting {later:%d %B %Y} for 1 person with a $1,400 "
        "budget.",
    ]


def _option(prefix: str):
    """A constraint's label in the chosen language; the value sent stays the catalog's own."""
    return lambda value: t(f"{prefix}.{value}") if value else t("form.no_preference")


def trip_dialog() -> None:
    # Made on each call, so the pop-up's title follows the chosen language.
    st.dialog(t("form.title"), width="medium")(_trip_form)()


def _trip_form() -> None:
    currency, today = st.session_state.currency, date.today()
    st.caption(t("form.intro"))
    with st.form("trip", border=False):
        origin = st.text_input(t("form.from"), value="London")
        destination = st.text_input(t("form.to"), value="Rome")
        start = st.date_input(t("form.start"), value=today + timedelta(days=14), min_value=today,
                              max_value=today + timedelta(days=config.LIVE_DAYS_AHEAD))
        nights = st.number_input(t("form.nights"), min_value=1, max_value=14, value=4)
        people = st.number_input(t("form.travellers"), min_value=1, max_value=8, value=2)
        budget = st.number_input(t("form.budget", currency=currency), min_value=100.0, max_value=1_000_000.0,
                                 value=1500.0, step=100.0)
        stay_type = st.radio(t("form.stay"), ["Airbnb", "Hotel"], horizontal=True)
        with st.expander(t("form.constraints")):
            house_rule = st.selectbox(t("form.house_rule"), [None, *HOUSE_RULES], format_func=_option("rule"))
            room_type = st.selectbox(t("form.room_type"), [None, *ROOM_TYPES], format_func=_option("room"))
            cuisines = st.multiselect(t("form.cuisines"), CUISINES)
            transportation = st.selectbox(t("form.transport"), [None, *TRANSPORT_RULES],
                                          format_func=_option("transport"))
        submitted = st.form_submit_button(t("form.submit"), type="primary", width="stretch")
    if submitted:
        try:
            st.session_state.pending_question = trip_question(
                validate_city(origin), validate_city(destination), start, int(nights), int(people), budget,
                currency, stay_type, house_rule, room_type, cuisines, transportation)
        except InputValidationError as error:
            st.error(str(error))
            return
        st.rerun()  # closes the dialog; the chat page asks the question
