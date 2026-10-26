"""The chat page: the conversation, result cards, the trip form and the example questions.

An empty chat shows the hero (logo and tagline) and the Plan / Explore box; after the first
message the page shows the conversation with the usual chat box at the bottom.
"""

import json
import time
from dataclasses import asdict

import streamlit as st

from backend.agent.agent import AgentError, run_agent
from backend.agent.llm import model_name
from backend.live.budget import use_budget
from backend.security.rate_limit import RateLimiter
from backend.security.validation import InputValidationError
from backend.storage import history, trips
from frontend.components.cards import render_result_cards
from frontend.components.common import PAGES, cost_text, mode_key, set_mode, show_markdown
from frontend.components.trip_form import example_questions, trip_dialog
from frontend.html import render as html

TAGLINE = "Your travel planner with live prices, costed against your budget"
MODE_LABELS = {"plan": ":material/auto_awesome: Plan", "explore": ":material/explore: Explore"}
MODE_HELP = {"plan": "A full trip: flights, a stay, restaurants, transport, the cost against your budget and the "
                     "checks.",
             "explore": "Ideas and places: sights, restaurants and getting around. No flight or stay searches, so "
                        "it's quicker and uses no live search quota."}
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


def _mode_picker() -> None:
    """Plan or Explore. A new chat (or another chat) starts from the chat's own mode."""
    choice = st.segmented_control("Mode", list(MODE_LABELS), format_func=MODE_LABELS.get,
                                  default=st.session_state.mode, label_visibility="collapsed",
                                  key=mode_key(st.session_state.chat_id))
    if choice and choice != st.session_state.mode:
        st.session_state.mode = choice
        if st.session_state.chat_id:
            history.set_chat_mode(st.session_state.chat_id, choice)


def _composer() -> str | None:
    """The Plan / Explore box on an empty chat. Returns a question when one is sent."""
    with st.container(key="composer"):
        _mode_picker()
        with st.form("composer-form", border=False, clear_on_submit=True):
            text = st.text_area("Your trip", height=110, label_visibility="collapsed")
            # theme.css moves this round button into the text area's bottom-right corner.
            with st.container(key="composer-send"):
                sent = st.form_submit_button("Send", icon=":material/arrow_upward:", type="primary")
            st.caption(MODE_HELP[st.session_state.mode])
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
    if st.session_state.chat_id:
        st.query_params["chat"] = st.session_state.chat_id  # keeps the chat open after a refresh

    if not st.session_state.messages:
        html.hero(TAGLINE)
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
