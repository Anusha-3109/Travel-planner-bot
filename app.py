"""TripMate: a Streamlit travel planning chatbot with RAG and tool calling.

Run with:  streamlit run app.py
"""

import json
from dataclasses import asdict
from datetime import date, datetime, timedelta

import streamlit as st

import config
from agent.agent import AgentError, run_agent
from live.budget import SessionBudget, use_budget
from live.status import ServiceStatus, live_status
from rag.ingest import build_index, ensure_index
from rag.retriever import available_cities
from security.rate_limit import RateLimiter
from security.validation import InputValidationError, validate_city
from travel_data.catalog import HOUSE_RULES, ROOM_TYPES, TRANSPORT_RULES, load_catalog

st.set_page_config(page_title="TripMate travel planner", page_icon="✈️", layout="wide")

EXAMPLE_QUESTIONS = [
    "Plan a 3-day trip from Washington to Myrtle Beach, March 13-15, 2022, for 1 person with a $1,400 budget.",
    "Which flights go from St. Petersburg to Rockford on 2022-03-16?",
    "Find Indian restaurants in Myrtle Beach under $50 per person.",
    "Plan a 5-day trip from London to Rome for 2 people with a $2,500 budget, starting 2026-11-10.",
    "Find a private room in Tokyo for 2 nights and some sushi restaurants nearby.",
]


@st.cache_resource(show_spinner="Updating the knowledge base (the first run embeds every place and takes a while)...")
def _prepare_index() -> int:
    return ensure_index()


@st.cache_data(ttl=300, show_spinner=False)
def _live_status() -> list[ServiceStatus]:
    # Re-checked every 5 minutes. The SerpApi check is free and doesn't use a search.
    return live_status()


def _render_live_status() -> None:
    st.markdown("**Live data**")
    for service in _live_status():
        icon = "✅" if service.configured and service.working is not False else "⚠️" if service.configured else "⚪"
        st.caption(f"{icon} **{service.name}** ({service.provides}): {service.detail}")
    budget: SessionBudget = st.session_state.live_budget
    used = " · ".join(f"{name} {budget.used.get(name, 0)}/{limit}" for name, limit in budget.limits.items())
    st.caption(f"Live searches this chat: {used}. Repeated searches are reused from the cache for free.")


def _show_markdown(text: str) -> None:
    # Streamlit treats text between two "$" signs as LaTeX, which garbles prices like "$1,200 ... $78".
    st.markdown(text.replace("$", r"\$"))


def _init_state() -> None:
    st.session_state.setdefault("messages", [])
    st.session_state.setdefault("rate_limiter", RateLimiter())
    st.session_state.setdefault("live_budget", SessionBudget())
    st.session_state.setdefault("token_totals", {"input_tokens": 0, "output_tokens": 0, "total_tokens": 0})


def _render_details(message: dict) -> None:
    tool_calls = message.get("tool_calls") or []
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
        st.caption(f"Tokens: {usage['input_tokens']} in · {usage['output_tokens']} out")


def _ask(question: str) -> None:
    limiter: RateLimiter = st.session_state.rate_limiter
    if not limiter.try_acquire():
        st.warning(f"You're sending messages too quickly. Try again in {limiter.seconds_until_available()} seconds.")
        return

    history = [{"role": m["role"], "content": m["content"]} for m in st.session_state.messages]
    with st.chat_message("user"):
        _show_markdown(question)

    with st.chat_message("assistant"):
        with st.status("Planning...", expanded=False) as status:
            try:
                with use_budget(st.session_state.live_budget):
                    result = run_agent(question, history=history, on_step=lambda text: status.update(label=text))
            except (InputValidationError, AgentError) as error:
                status.update(label="Couldn't answer", state="error")
                st.error(str(error))
                return
            except Exception:
                status.update(label="Something went wrong", state="error")
                st.error("Something unexpected went wrong. Please try again.")
                return
            status.update(label=f"Done · {len(result.tool_calls)} tool call(s)", state="complete")

        message = {
            "role": "assistant",
            "content": result.answer,
            "tool_calls": [asdict(call) for call in result.tool_calls],
            "sources": result.sources,
            "retrieval_queries": result.retrieval_queries,
            "token_usage": result.token_usage,
        }
        _show_markdown(result.answer)
        _render_details(message)

    for key, value in result.token_usage.items():
        st.session_state.token_totals[key] += value
    st.session_state.messages.append({"role": "user", "content": question})
    st.session_state.messages.append(message)


def _trip_question(origin: str, destination: str, start: date, days: int, people: int, budget: float,
                   house_rule: str | None, room_type: str | None, cuisines: list[str],
                   transportation: str | None) -> str:
    end = start + timedelta(days=days - 1)
    question = (
        f"Plan a {days}-day trip from {origin} to {destination}, {start:%Y-%m-%d} to {end:%Y-%m-%d}, "
        f"for {people} {'person' if people == 1 else 'people'} with a budget of ${budget:,.0f}."
    )
    rules = []
    if house_rule:
        rules.append(f"the place to stay must allow {house_rule}")
    if room_type:
        rules.append(f"the room type must be {room_type}")
    if cuisines:
        rules.append(f"meals must include {', '.join(cuisines)} cuisine")
    if transportation:
        rules.append(f"transportation: {transportation}")
    return question + (f" Constraints: {'; '.join(rules)}." if rules else "")


def _export_markdown(messages: list[dict]) -> str:
    lines = [f"# TripMate conversation ({datetime.now():%Y-%m-%d %H:%M})", ""]
    for message in messages:
        lines += [f"## {message['role'].title()}", "", message["content"], ""]
        for source in message.get("sources") or []:
            lines.append(f"- Source: {source['source']}")
    return "\n".join(lines)


def _sidebar() -> str | None:
    with st.sidebar:
        st.header("✈️ Trip planner")
        regions = load_catalog().cities_by_region()
        st.caption(
            f"US: {len(regions.get('North America', []))} cities (TravelPlanner, March 2022, with flight and "
            f"restaurant prices). Europe and Asia: {', '.join(regions.get('Europe', []) + regions.get('Asia', []))} "
            "(Airbnb stays from September 2026; no restaurant or flight prices)."
        )
        with st.form("trip"):
            origin = st.text_input("From", value="Washington")
            destination = st.text_input("To", value="Myrtle Beach")
            start = st.date_input("Start date", value=date(2022, 3, 13),
                                  min_value=date(2022, 1, 1), max_value=date(2027, 12, 31))
            days = st.selectbox("Trip length (days)", [3, 5, 7])
            people = st.number_input("Travellers", min_value=1, max_value=8, value=1)
            budget = st.number_input("Budget (USD)", min_value=100.0, max_value=1_000_000.0, value=1400.0, step=100.0)
            with st.expander("Constraints (optional)"):
                house_rule = st.selectbox("Stay must allow", [None, *HOUSE_RULES], format_func=lambda v: v or "No preference")
                room_type = st.selectbox("Room type", [None, *ROOM_TYPES], format_func=lambda v: v or "No preference")
                cuisines = st.multiselect("Cuisines to include", ["American", "Chinese", "French", "Indian",
                                                                  "Italian", "Japanese", "Mediterranean", "Mexican",
                                                                  "Spanish", "Thai"])
                transportation = st.selectbox("Transportation", [None, *TRANSPORT_RULES],
                                              format_func=lambda v: v or "No preference")
            submitted = st.form_submit_button("Plan my trip", type="primary", use_container_width=True)
        question = None
        if submitted:
            try:
                catalog = load_catalog()
                question = _trip_question(
                    catalog.require_city(validate_city(origin)), catalog.require_city(validate_city(destination)),
                    start, int(days), int(people), budget, house_rule, room_type, cuisines, transportation)
            except InputValidationError as error:
                st.error(str(error))

        st.divider()
        _render_live_status()

        st.divider()
        totals = st.session_state.token_totals
        st.caption(f"Model: `{config.OPENROUTER_MODEL}`")
        st.caption(f"Session tokens: {totals['input_tokens']:,} in · {totals['output_tokens']:,} out")

        if st.session_state.messages:
            st.download_button("Export chat (Markdown)", _export_markdown(st.session_state.messages),
                               file_name="tripmate_chat.md", use_container_width=True)
            st.download_button("Export chat (JSON)", json.dumps(st.session_state.messages, indent=2),
                               file_name="tripmate_chat.json", use_container_width=True)
            if st.button("Clear chat", use_container_width=True):
                st.session_state.messages = []
                st.session_state.live_budget = SessionBudget()  # a new chat gets a fresh live search limit
                st.rerun()

        with st.expander("Admin"):
            if st.button("Rebuild knowledge base"):
                progress = st.progress(0.0, text="Re-indexing places...")
                count = build_index(on_progress=lambda done, total: progress.progress(
                    done / total, text=f"Indexed {done:,} of {total:,} places"))
                _prepare_index.clear()
                st.success(f"Indexed {count:,} places.")

        with st.expander("ℹ️ How to use"):
            st.markdown(
                "- Fill in the trip form and press **Plan my trip**, or ask anything in the chat.\n"
                "- Expand **Tool calls** under an answer to see the flights, places, costs and checks it used.\n"
                "- Expand **Sources** to see the places the knowledge base search returned.\n"
                "- US data is a March 2022 snapshot, so prices and schedules are not live. US flights exist only "
                "for March-April 2022 dates.\n"
                "- European and Asian cities have current Airbnb prices, but restaurant and flight costs are missing "
                "and left out of totals."
            )
    return question


def main() -> None:
    _init_state()
    st.title("TripMate ✈️")
    st.caption("Plan a day-by-day trip in the US, Europe or Asia: transport, meals, attractions and stays, within your budget.")

    if not config.OPENROUTER_API_KEY:
        st.error("OPENROUTER_API_KEY is not set. Copy `.env.example` to `.env`, add your key, and restart the app.")
        st.stop()
    try:
        _prepare_index()
    except Exception as error:
        st.error(f"Couldn't build the knowledge base: {error}")
        st.stop()

    form_question = _sidebar()

    for message in st.session_state.messages:
        with st.chat_message(message["role"]):
            _show_markdown(message["content"])
            if message["role"] == "assistant":
                _render_details(message)

    example_question = None
    if not st.session_state.messages:
        st.markdown("**Try one of these:**")
        columns = st.columns(2)
        for index, example in enumerate(EXAMPLE_QUESTIONS):
            if columns[index % 2].button(example, key=f"example-{index}", use_container_width=True):
                example_question = example

    question = st.chat_input("Ask for a trip plan, flights, restaurants or places to stay...") or form_question or example_question
    if question:
        _ask(question)
        if len(st.session_state.messages) == 2:
            st.rerun()  # redraw without the example buttons once the chat has started


main()
