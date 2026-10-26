"""The chat page: the conversation, result cards, the trip form and the example questions.

An empty chat shows the hero (logo and tagline) and the Plan / Explore box; after the first
message the page shows the conversation with the usual chat box at the bottom.
"""

import json
import time
from dataclasses import asdict
from datetime import date, timedelta
from pathlib import Path

import streamlit as st

import config
import history
import trips
from agent.agent import AgentError, run_agent
from agent.llm import model_name
from live.budget import use_budget
from security.rate_limit import RateLimiter
from security.validation import InputValidationError, validate_city
from travel_data.catalog import HOUSE_RULES, ROOM_TYPES, TRANSPORT_RULES
from trip_form import PLACEHOLDERS, example_questions, trip_question
from ui.common import PAGES, cost_text, mode_key, set_mode, show_markdown
from ui_cards import render_result_cards

LOGO = Path(__file__).resolve().parents[1] / "assets" / "logo.svg"
TAGLINE = "Your travel planner with live prices, costed against your budget"
MODE_LABELS = {"plan": ":material/auto_awesome: Plan", "explore": ":material/explore: Explore"}
MODE_HELP = {"plan": "A full trip: flights, a stay, restaurants, transport, the cost against your budget and the "
                     "checks.",
             "explore": "Ideas and places: sights, restaurants and getting around. No flight or stay searches, so "
                        "it's quicker and uses no live search quota."}
# The Plan / Explore box: a rounded card with pill-shaped mode buttons (Streamlit has no setting for this).
COMPOSER_CSS = """<style>
.st-key-composer { border: 1px solid #2c2f36; border-radius: 18px; padding: 0.75rem; background-color: #1d1f24; }
.st-key-composer [data-testid="stButtonGroup"] button { border-radius: 999px; }
.st-key-composer textarea { font-size: 1rem; }
</style>"""
# Feature tiles on an empty chat: (icon, title, text, action). Actions: "ask:<mode>" asks the first example of
# that mode, "page:<name>" opens a page, None is coming soon.
TILES = [
    (":material/auto_awesome:", "AI planning", "Describe a trip: TripMate builds a costed plan, day by day.",
     "ask:plan"),
    (":material/calendar_month:", "Day-by-day plan", "Your saved trips as timelines: times, places and prices.",
     "page:trips"),
    (":material/route:", "Route planning", "Every stop of a saved trip on a map.", "page:trips"),
    (":material/hotel:", "Booking", "Find Airbnbs and hotels with live prices, and book on their sites.",
     "ask:booking"),
    (":material/explore:", "Discover", "Sights, food and neighbourhoods in 245 cities.", "ask:explore"),
    (":material/savings:", "Budget tracker", "Planned against spent, split between travellers.", None),
    (":material/backpack:", "Packing list", "A checklist made for your trip.", None),
    (":material/description:", "Documents", "Tickets, visas and vouchers, by day.", None),
    (":material/book:", "Journal", "Notes and photos for each day.", None),
]
CUISINES = ["American", "Chinese", "French", "Indian", "Italian", "Japanese", "Mediterranean", "Mexican", "Spanish",
            "Thai"]


def refusal_reason(error: Exception) -> str:
    """Why the input guard turned a question away, for the dashboard."""
    text = str(error).lower()
    if "instruction" in text:
        return "prompt injection"
    if "too long" in text or "characters" in text:
        return "too long"
    if "empty" in text:
        return "empty question"
    return "invalid input"


def _save_trip_button(index: int) -> None:
    """Under an answer with a costed plan: save it as a trip and open the trip page."""
    if not trips.find_plan(trips.tool_calls([st.session_state.messages[index]])):
        return
    if st.button("Save as trip", key=f"save-trip-{index}", icon=":material/luggage:", type="primary"):
        trip = trips.build_trip(st.session_state.messages, index)
        trip_id = history.save_trip(trip, st.session_state.chat_id)
        st.switch_page(PAGES["trip"], query_params={"trip": trip_id})


def _render_details(message: dict, index: int | None = None) -> None:
    tool_calls = message.get("tool_calls") or []
    render_result_cards(tool_calls)
    if index is not None:
        _save_trip_button(index)
    sources = message.get("sources") or []
    queries = message.get("retrieval_queries") or []
    if tool_calls:
        with st.expander(f"🛠️ Tool calls ({len(tool_calls)})"):
            for call in tool_calls:
                st.markdown(f"**`{call['name']}`** with arguments")
                st.json(call["args"])
                try:
                    st.json(json.loads(call["output"]))
                except (json.JSONDecodeError, TypeError):
                    st.text(call["output"][:3000])
    if sources:
        with st.expander(f"📚 Sources ({len(sources)})"):
            if queries:
                st.caption("Search queries after query translation: " + " · ".join(f"“{q}”" for q in queries))
            for source in sources:
                st.markdown(f"**{source['source']}** — {source.get('section') or ''} (RRF score {source.get('rrf_score')})")
                st.caption(source["content"][:600])
    usage = message.get("token_usage")
    if usage and usage.get("total_tokens"):
        answered_by = f"Answered by {model_name(message['model'])} · " if message.get("model") else ""
        st.caption(f"{answered_by}Tokens: {usage['input_tokens']:,} in · {usage['output_tokens']:,} out · "
                   f"Cost: {cost_text(usage.get('cost_usd'))}")


def _save(question: str, message: dict) -> None:
    """Adds the exchange to the session and the saved chat (a new chat starts with its first question)."""
    st.session_state.messages += [{"role": "user", "content": question, "mode": st.session_state.mode}, message]
    if st.session_state.chat_id is None:
        st.session_state.chat_id = history.create_chat(question, st.session_state.mode)
        st.query_params["chat"] = st.session_state.chat_id
    history.save_messages(st.session_state.chat_id, st.session_state.messages)


def ask(question: str) -> None:
    model, mode = st.session_state.model, st.session_state.mode
    limiter: RateLimiter = st.session_state.rate_limiter
    if not limiter.try_acquire():
        history.log_request(st.session_state.chat_id, model, "limit", "sending too quickly", mode=mode)
        st.warning(f"You're sending messages too quickly. Try again in {limiter.seconds_until_available()} seconds.")
        return

    conversation = [{"role": m["role"], "content": m["content"]} for m in st.session_state.messages]
    budget = st.session_state.live_budget
    searches_before = dict(budget.used)
    started = time.monotonic()
    with st.chat_message("user"):
        show_markdown(question)

    with st.chat_message("assistant"):
        with st.status("Planning...", expanded=False) as status:
            try:
                with use_budget(budget):
                    result = run_agent(question, history=conversation, on_step=lambda text: status.update(label=text),
                                       currency=st.session_state.currency, cards=True, model=model, mode=mode)
            except InputValidationError as error:
                status.update(label="Couldn't answer", state="error")
                st.error(str(error))
                history.log_request(st.session_state.chat_id, model, "refused", refusal_reason(error),
                                    time.monotonic() - started, mode=mode)
                return
            except AgentError as error:
                status.update(label="Couldn't answer", state="error")
                st.error(str(error))
                history.log_request(st.session_state.chat_id, model, "error", str(error)[:200],
                                    time.monotonic() - started, mode=mode)
                return
            except Exception:
                status.update(label="Something went wrong", state="error")
                st.error("Something unexpected went wrong. Please try again.")
                history.log_request(st.session_state.chat_id, model, "error", "unexpected error",
                                    time.monotonic() - started, mode=mode)
                return
            status.update(label=f"Done · {len(result.tool_calls)} tool call(s)", state="complete")

        message = {
            "role": "assistant",
            "content": result.answer,
            "tool_calls": [asdict(call) for call in result.tool_calls],
            "sources": result.sources,
            "retrieval_queries": result.retrieval_queries,
            "token_usage": result.token_usage,
            "model": result.model,
        }
        show_markdown(result.answer)
        _render_details(message)

    _save(question, message)
    searches = {name: budget.used.get(name, 0) - searches_before.get(name, 0) for name in budget.used}
    history.log_request(st.session_state.chat_id, model, "answered", seconds=time.monotonic() - started,
                        usage=result.token_usage, tools=[c.name for c in result.tool_calls], searches=searches,
                        mode=mode)


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


def _mode_picker() -> None:
    """Plan or Explore. A new chat (or another chat) starts from the chat's own mode."""
    choice = st.segmented_control("Mode", list(MODE_LABELS), format_func=MODE_LABELS.get,
                                  default=st.session_state.mode, label_visibility="collapsed",
                                  key=mode_key(st.session_state.chat_id))
    if choice and choice != st.session_state.mode:
        st.session_state.mode = choice
        if st.session_state.chat_id:
            history.set_chat_mode(st.session_state.chat_id, choice)


def _hero() -> None:
    st.space("medium")
    with st.container(horizontal_alignment="center"):
        st.image(str(LOGO), width=260)  # st.html would strip an inline SVG, st.image draws the file
    st.html(f'<p style="text-align:center;font-size:1.15rem;margin:0.25rem 0 1.25rem;">{TAGLINE}</p>')


def _composer() -> str | None:
    """The Plan / Explore box on an empty chat. Returns a question when one is sent."""
    with st.container(key="composer"):
        _mode_picker()
        with st.form("composer-form", border=False, clear_on_submit=True):
            text = st.text_area("Your trip", placeholder=PLACEHOLDERS[st.session_state.mode], height=110,
                                label_visibility="collapsed")
            with st.container(horizontal=True, horizontal_alignment="right", vertical_alignment="center"):
                st.caption(MODE_HELP[st.session_state.mode])
                sent = st.form_submit_button("Send", icon=":material/arrow_upward:", type="primary")
    if st.button("Fill in the trip form instead", icon=":material/edit_note:", type="tertiary"):
        trip_dialog()
    return text.strip() if sent and text.strip() else None


def _examples() -> str | None:
    st.markdown("**Try one of these**")
    columns = st.columns(2)
    for index, example in enumerate(example_questions(mode=st.session_state.mode)):
        if columns[index % 2].button(example, key=f"example-{st.session_state.mode}-{index}", width="stretch"):
            return example
    return None


def _ask_from_tile(target: str) -> None:
    """A tile's starter question: the first example of its mode, or the stay example for Booking."""
    mode = "explore" if target == "explore" else "plan"
    set_mode(mode)
    examples = example_questions(mode=mode)
    st.session_state.pending_question = examples[2] if target == "booking" else examples[0]


def _tiles() -> None:
    """What TripMate can do, as tiles; the last ones are coming soon."""
    st.markdown("**What TripMate can do**")
    for number, (icon, title, text, action) in enumerate(TILES):
        if number % 3 == 0:
            columns = st.columns(3)  # a new row, so the tiles in a row line up
        with columns[number % 3].container(border=True, height="stretch"):
            st.markdown(f"{icon} **{title}**")
            st.caption(text)
            st.space("stretch")
            if action is None:
                st.badge("Coming soon", color="gray")
            elif action.startswith("page:"):
                if st.button("Open", key=f"tile-{number}", type="tertiary", icon=":material/arrow_forward:"):
                    st.switch_page(PAGES[action.split(":")[1]])
            else:
                # A callback, so the Plan / Explore switch can be changed before it's drawn again.
                st.button("Try it", key=f"tile-{number}", type="tertiary", icon=":material/arrow_forward:",
                          on_click=_ask_from_tile, args=(action.split(":")[1],))


def render() -> None:
    st.html(COMPOSER_CSS)
    if st.session_state.chat_id:
        st.query_params["chat"] = st.session_state.chat_id  # keeps the chat open after a refresh

    if not st.session_state.messages:
        _hero()
        question = _composer() or _examples() or st.session_state.pop("pending_question", None)
        _tiles()
    else:
        title, mode, button = st.columns([3, 2, 1], vertical_alignment="center")
        title.markdown("### TripMate")
        with mode:
            _mode_picker()
        if button.button("Plan a trip", icon=":material/flight_takeoff:", width="stretch"):
            trip_dialog()
        for index, message in enumerate(st.session_state.messages):
            with st.chat_message(message["role"]):
                show_markdown(message["content"])
                if message["role"] == "assistant":
                    _render_details(message, index)
        placeholder = ("Ask for a trip plan, flights, restaurants or places to stay..."
                       if st.session_state.mode == "plan" else "Ask about places, food or getting around...")
        question = st.chat_input(placeholder) or st.session_state.pop("pending_question", None)

    if question:
        before = len(st.session_state.messages)
        ask(question)
        if len(st.session_state.messages) > before:
            st.rerun()  # answered: redraw the sidebar history and drop the example buttons (errors stay shown)
