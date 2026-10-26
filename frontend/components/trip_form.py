"""The trip form pop-up, the currencies it offers and the example questions on an empty chat.

The trip request text itself is built by backend/agent/trip_request.py.
"""

from datetime import date, timedelta

import streamlit as st

from backend import config
from backend.agent.trip_request import trip_question
from backend.security.validation import InputValidationError, validate_city
from backend.travel_data.catalog import HOUSE_RULES, ROOM_TYPES, TRANSPORT_RULES

CUISINES = ["American", "Chinese", "French", "Indian", "Italian", "Japanese", "Mediterranean", "Mexican", "Spanish",
            "Thai"]
CURRENCIES = ["USD", "EUR", "GBP", "INR", "JPY", "AUD", "CAD", "CHF", "SGD", "AED", "THB"]


EXPLORE_EXAMPLES = [
    "Museums for kids in Chicago.",
    "Sushi restaurants in Tokyo rated 4.5 or more.",
    "Which areas of Lisbon are nice to stay in, and what is there to see?",
    "How do I get from Fiumicino Airport to the Colosseum?",
]


def example_questions(today: date | None = None, mode: str = "plan") -> list[str]:
    """Examples with dates worked out from today, so the live examples always work. Explore mode
    has its own examples, which need no flights or stays."""
    if mode == "explore":
        return list(EXPLORE_EXAMPLES)
    today = today or date.today()
    soon, later = today + timedelta(days=14), today + timedelta(days=30)
    return [
        f"Plan a 4-night trip from London to Rome starting {soon:%d %B %Y} for 2 people with a budget of 1,500.",
        f"Flights from New York to Tokyo on {later:%d %B %Y}.",
        f"Find an Airbnb in Paris from {soon:%d %B} to {soon + timedelta(days=3):%d %B %Y} for 2 people.",
        "Sushi restaurants in Tokyo rated 4.5 or more.",
        "How do I get from Fiumicino Airport to the Colosseum?",
        f"Plan a 3-day trip from Washington to Myrtle Beach starting {later:%d %B %Y} for 1 person with a $1,400 "
        "budget.",
    ]


@st.dialog("Plan a trip", width="medium")
def trip_dialog() -> None:
    currency, today = st.session_state.currency, date.today()
    st.caption("Live flights, stays, restaurants and transport for any city worldwide, for dates from today.")
    with st.form("trip", border=False):
        origin = st.text_input("From", value="London")
        destination = st.text_input("To", value="Rome")
        start = st.date_input("Start date", value=today + timedelta(days=14), min_value=today,
                              max_value=today + timedelta(days=config.LIVE_DAYS_AHEAD))
        nights = st.number_input("Nights", min_value=1, max_value=14, value=4)
        people = st.number_input("Travellers", min_value=1, max_value=8, value=2)
        budget = st.number_input(f"Budget ({currency})", min_value=100.0, max_value=1_000_000.0, value=1500.0,
                                 step=100.0)
        stay_type = st.radio("Stay", ["Airbnb", "Hotel"], horizontal=True)
        with st.expander("Constraints (optional)"):
            house_rule = st.selectbox("Stay must allow", [None, *HOUSE_RULES], format_func=lambda v: v or "No preference")
            room_type = st.selectbox("Room type", [None, *ROOM_TYPES], format_func=lambda v: v or "No preference")
            cuisines = st.multiselect("Cuisines to include", CUISINES)
            transportation = st.selectbox("Transportation", [None, *TRANSPORT_RULES],
                                          format_func=lambda v: v or "No preference")
        submitted = st.form_submit_button("Plan my trip", type="primary", width="stretch")
    if submitted:
        try:
            st.session_state.pending_question = trip_question(
                validate_city(origin), validate_city(destination), start, int(nights), int(people), budget,
                currency, stay_type, house_rule, room_type, cuisines, transportation)
        except InputValidationError as error:
            st.error(str(error))
            return
        st.rerun()  # closes the dialog; the chat page asks the question
