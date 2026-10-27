"""The How it answers page: what happens to a question, the tools, the knowledge base,
the data sources, how prices are costed and the safety checks. It also lets you try
the knowledge-base search directly (no model, no cost)."""

import pandas as pd
import streamlit as st

from backend import config
from backend.agent.agent import TOOLS
from backend.rag.retriever import SearchPlan, retrieve
from backend.security.validation import PLACE_CATEGORIES, InputValidationError, validate_question
from frontend.pages.dashboard import knowledge_base

FLOW = """
digraph {
  rankdir=LR; bgcolor="transparent"; pad=0.2;
  node [shape=box style="rounded,filled" fillcolor="#202020" color="#f59e0b" fontcolor="#ececec"
        fontname="Helvetica" fontsize=11 margin="0.15,0.08"];
  edge [color="#8b8b8b" arrowsize=0.7];
  q [label="Your question"]; guard [label="Input guard\\n(rules)"];
  agent [label="Agent\\n(the model you picked)"]; tools [label="Tools\\nlive first, snapshot fallback"];
  screen [label="Tool results\\nscreened"]; cost [label="Cost and checks\\n(tools, not the model)"];
  answer [label="Answer\\n+ result cards"];
  q -> guard -> agent -> tools -> screen -> agent; agent -> cost -> agent; agent -> answer;
}
"""

TOOL_DETAILS = {
    "search_flights": ("Google Flights via SerpApi, grouped by airline", "Estimated flight time, no price"),
    "search_accommodations": ("Airbnb or Google Hotels via SerpApi, with booking links",
                              "2026 snapshot stays (Inside Airbnb prices for 50 cities)"),
    "search_restaurants": ("Google Places: rating, price range, open now, map link",
                           "2026 OpenStreetMap restaurants (no prices)"),
    "get_local_transport": ("Google Routes: public transport for the travel day, driving with US car cost",
                            "Drive estimated from the distance"),
    "search_destination_options": ("—", "RAG search over the knowledge base"),
    "calculate_trip_cost": ("Costs a plan from live ids and snapshot names", "—"),
    "check_constraints": ("Budget, house rules, room type, cuisines, transport and common-sense checks", "—"),
}


def tool_table() -> pd.DataFrame:
    rows = []
    for tool in TOOLS:
        live, fallback = TOOL_DETAILS.get(tool.name, ("", ""))
        rows.append({"Tool": tool.name, "Live": live, "Without live data": fallback})
    return pd.DataFrame(rows)


def _try_search() -> None:
    with st.form("try-search"):
        query = st.text_input("Search the knowledge base", value="museums for kids")
        left, right = st.columns(2)
        city = left.text_input("City (optional)", value="Chicago")
        category = right.selectbox("Category (optional)", [None, *PLACE_CATEGORIES],
                                   format_func=lambda c: c or "Any")
        submitted = st.form_submit_button("Search", icon=":material/search:")
    if not submitted:
        return
    try:
        query = validate_question(query)
    except InputValidationError as error:
        st.error(str(error))
        return
    # No query translation here, so it's free: the question is searched as typed, with your filters.
    result = retrieve(query, category=category, city=city or None, plan=SearchPlan(queries=[query]))
    if not result.documents:
        st.caption("No places matched. Check the city name, or try without a city.")
    for rank, document in enumerate(result.documents, 1):
        with st.container(border=True):
            st.markdown(f"**{rank}. {document.metadata.get('name')}** · {document.metadata.get('category')} · "
                        f"{document.metadata.get('city')}")
            st.caption(f"{document.page_content[:300]}  \nDistance {document.metadata.get('distance')} · "
                       f"RRF score {document.metadata.get('rrf_score')}")


def render() -> None:
    st.title("How it answers")
    st.caption("What happens to your question, where the data comes from, and how TripMate keeps prices and "
               "plans honest.")

    st.subheader("From question to answer")
    st.graphviz_chart(FLOW, width="stretch")
    st.markdown(
        f"1. **Input guard.** Your message is checked for length, control characters and prompt-injection patterns "
        "before any model sees it.\n"
        "2. **Agent.** The model reads the question (with today's date and your currency) and decides which tools "
        f"to call. It can take up to {config.MAX_AGENT_STEPS} steps.\n"
        "3. **Tools.** Live data first (dates from today on). If a search fails, the date is in the past or a key "
        "is missing, the tool falls back to snapshot data and says so.\n"
        "4. **Screening.** Text from outside sources is screened for injected instructions before the model reads "
        "it.\n"
        "5. **Cost and checks.** For a full plan the agent must call the cost and check tools with the ids of the "
        "results it chose, so totals use the prices the services returned, never numbers the model typed.\n"
        "6. **Answer.** The model writes the answer; the app draws every result as cards from the tools' own data.")

    st.subheader("The 7 tools")
    st.dataframe(tool_table(), hide_index=True, width="stretch")

    st.subheader("The knowledge base (RAG)")
    kb = knowledge_base()
    indexed = f"{kb['indexed']:,}" if kb["indexed"] is not None else "updating"
    left, right = st.columns(2)
    with left, st.container(border=True, height="stretch"):
        st.markdown("**What's in it**")
        st.markdown(f"- **{indexed}** places in **{kb['cities']}** cities, one document per place\n"
                    f"- {kb['attractions']:,} attractions and {kb['restaurants']:,} restaurants (OpenStreetMap)\n"
                    f"- {kb['stays']:,} stays: Inside Airbnb with prices for 50 cities, OpenStreetMap hotels "
                    "without prices for the other US cities\n"
                    "- Local embeddings (all-MiniLM-L6-v2) in Chroma: no API key, nothing sent out")
    with right, st.container(border=True, height="stretch"):
        st.markdown("**How a search works**")
        st.markdown(f"1. **Query translation:** the model rewrites the question into up to "
                    f"{config.MAX_QUERY_VARIANTS} focused searches.\n"
                    "2. **Structured retrieval:** it also picks a category and city, used as metadata filters.\n"
                    f"3. **Fusion:** each search returns {config.RETRIEVAL_K} places; reciprocal rank fusion merges "
                    "them into one ranking.\n"
                    "4. The places go to the model as sources, and are listed under **Sources** in the answer.")
    with st.expander("Try the search yourself (free: no model, no query translation)"):
        _try_search()

    st.subheader("Where the data comes from")
    st.dataframe(pd.DataFrame([
        {"Data": "Flights", "Live": "Google Flights (SerpApi), cached 1 hour",
         "Snapshot": "None: an estimated flight time without a price"},
        {"Data": "Stays", "Live": "Airbnb and Google Hotels (SerpApi), cached 6 hours",
         "Snapshot": "Inside Airbnb, September 2026 (50 cities); OpenStreetMap hotels, no prices (195 US cities)"},
        {"Data": "Restaurants", "Live": "Google Places, cached 24 hours",
         "Snapshot": "OpenStreetMap, October 2026 (no prices)"},
        {"Data": "Attractions", "Live": "—", "Snapshot": "OpenStreetMap, October 2026"},
        {"Data": "Transport", "Live": "Google Routes, cached 24 hours",
         "Snapshot": "Distance estimate between city centres"},
        {"Data": "Exchange rates", "Live": "ExchangeRate-API, ECB as backup, cached 12 hours", "Snapshot": "—"},
    ]), hide_index=True, width="stretch")

    left, right = st.columns(2)
    with left, st.container(border=True, height="stretch"):
        st.markdown("**How prices are costed**")
        st.markdown("- Flights, meals and transit fares are per person.\n"
                    "- A live stay's price covers the whole booking; snapshot stays book extra rooms for big groups.\n"
                    "- Cars seat 5 and taxis 4 (TravelPlanner's rules). US driving uses the IRS 2026 rate of "
                    f"${config.IRS_MILEAGE_RATE_USD} a mile.\n"
                    "- Prices that no source publishes (taxi fares, many transit fares, attraction tickets, snapshot "
                    "flights) are listed as **unpriced** and left out of totals, never guessed.\n"
                    "- Totals are shown in your currency at today's exchange rate.")
    with right, st.container(border=True, height="stretch"):
        st.markdown("**Safety checks**")
        st.markdown("- API keys stay in `.env` and are hidden in every log line and error message.\n"
                    "- The input guard and tool-result screening (see Settings).\n"
                    "- Every tool input the model chooses is validated like user input.\n"
                    "- Limits: a message rate limit, live searches per chat, and at most "
                    f"{config.MAX_AGENT_STEPS} agent steps per answer.\n"
                    "- Raw HTML in answers isn't rendered.")

    st.subheader("Good to know")
    st.markdown("- Ask for \"a table\" to get results as tables; otherwise answers are lists with cards below.\n"
                "- Live prices can change before booking.\n"
                "- Public transport times are for your travel day up to 100 days ahead.\n"
                "- Expand **Tool calls** under an answer to see exactly what was searched.")
