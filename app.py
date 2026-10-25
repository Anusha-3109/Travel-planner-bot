"""TripMate: a Streamlit travel planning chatbot with RAG and tool calling.

Run with:  streamlit run app.py
"""

import json
from dataclasses import asdict
from datetime import date, datetime, timedelta

import streamlit as st

import config
from agent.agent import AgentError, run_agent
from agent.llm import model_name
from live import fx
from live.budget import SessionBudget, use_budget
from live.status import ServiceStatus, live_status
from rag.ingest import build_index, ensure_index
from security.rate_limit import RateLimiter
from security.redaction import protect_logs
from security.validation import InputValidationError, validate_city
from travel_data.catalog import HOUSE_RULES, ROOM_TYPES, TRANSPORT_RULES
from trip_form import CURRENCIES, example_questions, trip_question
from ui_cards import render_result_cards

st.set_page_config(page_title="TripMate travel planner", page_icon="✈️", layout="wide")
protect_logs()


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


def _cost_text(cost_usd: float | None) -> str:
    """A model cost such as "$0.0021 (≈ EUR 0.0019)"; costs are tiny, so four decimals."""
    if cost_usd is None:
        return "not reported"
    text = r"\$" + f"{cost_usd:,.4f}"  # escaped: Streamlit reads text between two "$" as LaTeX
    currency = st.session_state.get("currency", "USD")
    if currency != "USD":
        try:
            text += f" (≈ {currency} {fx.get_rates().convert(cost_usd, 'USD', currency):,.4f})"
        except Exception:  # no exchange rate: the USD cost alone is enough
            pass
    return text


def _show_markdown(text: str) -> None:
    # Streamlit treats text between two "$" signs as LaTeX, which garbles prices like "$1,200 ... $78".
    st.markdown(text.replace("$", r"\$"))


def _init_state() -> None:
    st.session_state.setdefault("messages", [])
    st.session_state.setdefault("rate_limiter", RateLimiter())
    st.session_state.setdefault("live_budget", SessionBudget())
    st.session_state.setdefault("currency", "USD")
    st.session_state.setdefault("token_totals", {"input_tokens": 0, "output_tokens": 0, "total_tokens": 0,
                                                 "cost_usd": 0.0})
    st.session_state.setdefault("model", config.OPENROUTER_MODEL)


def _render_details(message: dict) -> None:
    tool_calls = message.get("tool_calls") or []
    render_result_cards(tool_calls)
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
                   f"Cost: {_cost_text(usage.get('cost_usd'))}")


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
                    result = run_agent(question, history=history, on_step=lambda text: status.update(label=text),
                                       currency=st.session_state.currency, cards=True,
                                       model=st.session_state.model)
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
            "model": result.model,
        }
        _show_markdown(result.answer)
        _render_details(message)

    totals = st.session_state.token_totals
    for key in ("input_tokens", "output_tokens", "total_tokens"):
        totals[key] += result.token_usage.get(key, 0)
    cost = result.token_usage.get("cost_usd")
    totals["cost_usd"] = None if cost is None or totals["cost_usd"] is None else totals["cost_usd"] + cost
    st.session_state.messages.append({"role": "user", "content": question})
    st.session_state.messages.append(message)


def _show_session_totals(slot) -> None:
    totals = st.session_state.token_totals
    slot.caption(f"Session: {totals['input_tokens']:,} tokens in · {totals['output_tokens']:,} out · "
                 f"cost {_cost_text(totals['cost_usd'])}")


def _model_label(model: str) -> str:
    name, input_price, output_price = config.MODELS[model]
    return name if input_price is None else f"{name} (${input_price:g} / ${output_price:g})"


def _export_markdown(messages: list[dict]) -> str:
    lines = [f"# TripMate conversation ({datetime.now():%Y-%m-%d %H:%M})", ""]
    for message in messages:
        lines += [f"## {message['role'].title()}", "", message["content"], ""]
        for source in message.get("sources") or []:
            lines.append(f"- Source: {source['source']}")
    return "\n".join(lines)


def _sidebar() -> tuple[str | None, object]:
    with st.sidebar:
        st.header("✈️ Trip planner")
        st.session_state.currency = st.selectbox(
            "Currency", CURRENCIES, index=CURRENCIES.index(st.session_state.currency),
            help="Budgets and trip totals use this currency, at today's exchange rate.")
        currency = st.session_state.currency
        st.caption("Live flights, stays, restaurants and transport for any city worldwide, for dates from today.")
        today = date.today()
        with st.form("trip"):
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
                cuisines = st.multiselect("Cuisines to include", ["American", "Chinese", "French", "Indian",
                                                                  "Italian", "Japanese", "Mediterranean", "Mexican",
                                                                  "Spanish", "Thai"])
                transportation = st.selectbox("Transportation", [None, *TRANSPORT_RULES],
                                              format_func=lambda v: v or "No preference")
            submitted = st.form_submit_button("Plan my trip", type="primary", width="stretch")
        question = None
        if submitted:
            try:
                question = trip_question(
                    validate_city(origin), validate_city(destination), start, int(nights), int(people), budget,
                    currency, stay_type, house_rule, room_type, cuisines, transportation)
            except InputValidationError as error:
                st.error(str(error))

        st.divider()
        _render_live_status()

        st.divider()
        models = list(config.MODELS)
        st.session_state.model = st.selectbox(
            "Model", models, index=models.index(st.session_state.model) if st.session_state.model in models else 0,
            format_func=lambda m: _model_label(m),
            help="Prices are USD per million tokens (input / output). Claude Haiku 5.5 was tested on full trip "
                 "plans; other models may follow the answer formats less closely.")
        session_totals = st.empty()  # filled again after each answer, as the sidebar is drawn before it
        _show_session_totals(session_totals)

        if st.session_state.messages:
            st.download_button("Export chat (Markdown)", _export_markdown(st.session_state.messages),
                               file_name="tripmate_chat.md", width="stretch")
            st.download_button("Export chat (JSON)", json.dumps(st.session_state.messages, indent=2),
                               file_name="tripmate_chat.json", width="stretch")
            if st.button("Clear chat", width="stretch"):
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
            current = len(list(config.WORLD_DIR.glob("*.json"))) if config.WORLD_DIR.exists() else 0
            st.markdown(
                "- Fill in the trip form and press **Plan my trip**, or ask anything in the chat. Ask for "
                "\"a table\" to get results as tables.\n"
                "- **Live** (dates from today on, any city): flights from Google Flights, Airbnb and hotel stays, "
                "restaurants with price ranges and ratings from Google Maps, and public transport and driving "
                "routes. In the US, driving has an estimated cost at the IRS 2026 mileage rate. Live prices can "
                "change before booking.\n"
                "- **Not available live:** taxi fares, most public transport fares, attraction entry prices and "
                "some restaurant prices. They're listed as unpriced and left out of totals.\n"
                f"- **Snapshot** (fallback and past dates): Inside Airbnb stays (September 2026) and OpenStreetMap "
                f"restaurants and attractions for {current} cities in the US, Europe and Asia, and the TravelPlanner "
                "dataset (March 2022) for other US cities and for US flights and driving routes.\n"
                "- Expand **Tool calls** under an answer to see what was searched, and **Sources** for places from "
                "the knowledge base."
            )
    return question, session_totals


def main() -> None:
    _init_state()
    st.title("TripMate ✈️")
    st.caption("Plan a day-by-day trip anywhere: live flights, stays, restaurants and public transport, "
               "costed against your budget.")

    if not config.OPENROUTER_API_KEY:
        st.error("OPENROUTER_API_KEY is not set. Copy `.env.example` to `.env`, add your key, and restart the app.")
        st.stop()
    try:
        _prepare_index()
    except Exception as error:
        st.error(f"Couldn't build the knowledge base: {error}")
        st.stop()

    form_question, session_totals = _sidebar()

    for message in st.session_state.messages:
        with st.chat_message(message["role"]):
            _show_markdown(message["content"])
            if message["role"] == "assistant":
                _render_details(message)

    example_question = None
    if not st.session_state.messages:
        st.markdown("**Try one of these:**")
        columns = st.columns(2)
        for index, example in enumerate(example_questions()):
            if columns[index % 2].button(example, key=f"example-{index}", width="stretch"):
                example_question = example

    question = st.chat_input("Ask for a trip plan, flights, restaurants or places to stay...") or form_question or example_question
    if question:
        _ask(question)
        _show_session_totals(session_totals)
        if len(st.session_state.messages) == 2:
            st.rerun()  # redraw without the example buttons once the chat has started


main()
