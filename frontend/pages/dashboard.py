"""The Dashboard page: what TripMate answers from, and how the chat is used.

Everything comes from the request log (history.py) and the catalog. The numbers
are worked out by plain functions (summary, per_day, ...) so they can be tested
without Streamlit; render() draws them.
"""

import statistics
from datetime import date, datetime, timedelta

import altair as alt
import pandas as pd
import streamlit as st

from backend import config
from backend.rag.vectorstore import get_vectorstore
from backend.storage import history
from backend.travel_data.catalog import load_catalog
from frontend.components.common import cached_live_status, current_owner

RANGES = {"7 days": 7, "30 days": 30, "90 days": 90, "1 year": 365}
STATUS_LABELS = {"answered": "Answered", "refused": "Turned away by the guard", "limit": "Turned away by a limit",
                 "error": "Error"}
STATUS_COLOURS = {"Answered": "#3b82f6", "Turned away by the guard": "#8b8f98", "Turned away by a limit": "#d4a017",
                  "Error": "#ef4444"}
BLUE, LIGHT_BLUE = "#3b82f6", "#9cc3ff"


# --- Numbers (no Streamlit) ------------------------------------------------------

def summary(rows: list[dict]) -> dict:
    """The headline numbers for a list of request log rows."""
    answered = [r for r in rows if r["status"] == "answered"]
    waits = [r["seconds"] for r in answered if r["seconds"] is not None]
    costs = [r["cost_usd"] for r in answered if r["cost_usd"] is not None]
    return {
        "requests": len(rows),
        "answered": len(answered),
        "answered_share": len(answered) / len(rows) if rows else None,
        "median_seconds": statistics.median(waits) if waits else None,
        "input_tokens": sum(r["input_tokens"] or 0 for r in rows),
        "output_tokens": sum(r["output_tokens"] or 0 for r in rows),
        "cost_usd": sum(costs),
        "cost_complete": len(costs) == len(answered),
        "serpapi": sum(r["serpapi"] or 0 for r in rows),
        "google": sum(r["google"] or 0 for r in rows),
    }


def _day(row: dict) -> date:
    return datetime.fromtimestamp(row["asked_at"]).date()


def days_in_range(days: int, today: date | None = None) -> list[date]:
    today = today or date.today()
    return [today - timedelta(days=n) for n in range(days - 1, -1, -1)]


def per_day(rows: list[dict], days: int, today: date | None = None) -> pd.DataFrame:
    """One row per day in the range (empty days included): requests by status, tokens, cost,
    live searches and answer times."""
    frame = pd.DataFrame({"day": days_in_range(days, today)})
    for label in STATUS_LABELS.values():
        frame[label] = 0
    for column in ("input_tokens", "output_tokens", "cost_usd", "serpapi", "google"):
        frame[column] = 0.0
    frame["p50_seconds"], frame["p95_seconds"] = None, None
    index = {day: i for i, day in enumerate(frame["day"])}
    waits: dict[int, list[float]] = {}
    for row in rows:
        i = index.get(_day(row))
        if i is None:
            continue
        frame.loc[i, STATUS_LABELS[row["status"]]] += 1
        for column in ("input_tokens", "output_tokens", "serpapi", "google"):
            frame.loc[i, column] += row[column] or 0
        frame.loc[i, "cost_usd"] += row["cost_usd"] or 0
        if row["status"] == "answered" and row["seconds"] is not None:
            waits.setdefault(i, []).append(row["seconds"])
    for i, values in waits.items():
        values = sorted(values)
        frame.loc[i, "p50_seconds"] = round(statistics.median(values), 1)
        frame.loc[i, "p95_seconds"] = round(values[min(len(values) - 1, int(0.95 * len(values)))], 1)
    return frame


def tool_counts(rows: list[dict]) -> dict[str, int]:
    counts: dict[str, int] = {}
    for row in rows:
        for tool in row["tools"]:
            counts[tool] = counts.get(tool, 0) + 1
    return dict(sorted(counts.items(), key=lambda item: -item[1]))


def guard_counts(rows: list[dict]) -> tuple[int, dict[str, int]]:
    """Questions that reached the agent, and refusals by reason."""
    refused: dict[str, int] = {}
    for row in rows:
        if row["status"] == "refused":
            refused[row["reason"] or "invalid input"] = refused.get(row["reason"] or "invalid input", 0) + 1
    reached = sum(1 for row in rows if row["status"] in ("answered", "error"))
    return reached, dict(sorted(refused.items(), key=lambda item: -item[1]))


@st.cache_data(ttl=600, show_spinner=False)
def knowledge_base() -> dict:
    catalog = load_catalog()
    stays = [s for city in catalog.accommodations.values() for s in city]
    try:
        indexed = get_vectorstore()._collection.count()
    except Exception:  # the index is being rebuilt
        indexed = None
    return {"cities": len(catalog.cities), "attractions": sum(map(len, catalog.attractions.values())),
            "restaurants": sum(map(len, catalog.restaurants.values())), "stays": len(stays),
            "priced_stays": sum(s.price is not None for s in stays), "indexed": indexed}


# --- Drawing ---------------------------------------------------------------------

def _money(amount: float) -> str:
    return r"\$" + (f"{amount:,.2f}" if amount >= 0.01 or amount == 0 else f"{amount:,.4f}")


def _compact(number: float) -> str:
    return f"{number / 1_000_000:.1f}M" if number >= 1_000_000 else f"{number / 1000:.0f}K" if number >= 1000 \
        else f"{number:,.0f}"


def _card(title: str, key: str):
    """A bordered card with a title and a "Show table" switch on the right. Returns (container, show_table)."""
    card = st.container(border=True)
    left, right = card.columns([2, 1], vertical_alignment="center")
    left.markdown(f"**{title}**")
    show = right.toggle("Show table", key=f"table-{key}", label_visibility="visible")
    return card, show


def _show(card, show_table: bool, table: pd.DataFrame, chart: alt.Chart) -> None:
    if show_table:
        card.dataframe(table, hide_index=True)
    else:
        card.altair_chart(chart)


def _bars(frame: pd.DataFrame, columns: list[str], colours: list[str], title: str, whole: bool = True) -> alt.Chart:
    """Stacked bars per day. whole: the values are counts, so the axis shows whole numbers."""
    long = frame.melt(id_vars="day", value_vars=columns, var_name="series", value_name="value")
    axis = alt.Axis(tickMinStep=1, format="~s") if whole else alt.Axis(format="$.3f")
    top = float(frame[columns].sum(axis=1).max() or 0)  # an all-zero range still gets a readable axis
    return alt.Chart(long).mark_bar().encode(
        x=alt.X("day:T", title=None, axis=alt.Axis(format="%d %b", labelAngle=0)),
        y=alt.Y("value:Q", title=None, stack=True, axis=axis,
                scale=alt.Scale(domain=[0, top]) if top > 0 else alt.Scale(domain=[0, 1 if whole else 0.01])),
        color=alt.Color("series:N", title=None, scale=alt.Scale(domain=columns, range=colours),
                        legend=alt.Legend(orient="top")),
        tooltip=[alt.Tooltip("day:T", format="%d %b %Y"), "series:N", alt.Tooltip("value:Q", title=title)],
    ).properties(height=220)


def _horizontal(counts: dict[str, int], colour: str = BLUE) -> alt.Chart:
    frame = pd.DataFrame({"name": list(counts), "count": list(counts.values())})
    return alt.Chart(frame).mark_bar(color=colour).encode(
        x=alt.X("count:Q", title=None, axis=alt.Axis(tickMinStep=1, format="d")),
        y=alt.Y("name:N", sort="-x", title=None, axis=alt.Axis(labelLimit=220)),
        tooltip=["name:N", "count:Q"]).properties(height=max(60, 28 * len(frame)))


def render() -> None:
    title, picker = st.columns([3, 2], vertical_alignment="bottom")
    with title:
        st.title("Dashboard")
        st.caption("What TripMate answers from, and how the chat is used.")
    with picker, st.container(horizontal_alignment="right"):
        choice = st.segmented_control("Range", list(RANGES), default="30 days", label_visibility="collapsed",
                                      key="dashboard-range") or "30 days"
    days = RANGES[choice]
    rows = history.requests_since(days, current_owner())
    numbers = summary(rows)

    kb = knowledge_base()
    with st.container(border=True):
        st.markdown("**Knowledge base**")
        indexed = f"{kb['indexed']:,}" if kb["indexed"] is not None else "updating"
        st.markdown(f"**{kb['cities']}** cities · **{kb['attractions']:,}** attractions · **{kb['restaurants']:,}** "
                    f"restaurants · **{kb['stays']:,}** stays ({kb['priced_stays']:,} with prices) · **{indexed}** "
                    "indexed places")
        st.caption("Inside Airbnb stays from September 2026 · OpenStreetMap places from October 2026 · live data "
                   "from Google Flights, Airbnb, Google Hotels, Google Maps and exchange rates.")

    with st.container(border=True, horizontal=True):
        share = f"{numbers['answered_share']:.0%}" if numbers["answered_share"] is not None else "–"
        wait = f"{numbers['median_seconds']:.1f} s" if numbers["median_seconds"] is not None else "–"
        tokens = numbers["input_tokens"] + numbers["output_tokens"]
        st.metric("Requests", numbers["requests"], help=f"Last {choice}")
        st.metric("Answered", share, help=f"{numbers['answered']} of {numbers['requests']}")
        st.metric("Typical wait", wait, help="Median time to answer")
        st.metric("Tokens", _compact(tokens),
                  help=f"{numbers['input_tokens']:,} in · {numbers['output_tokens']:,} out")
        st.metric("Cost", _money(numbers["cost_usd"]),
                  help="Reported by OpenRouter" + ("" if numbers["cost_complete"] else "; some answers had no cost"))

    if not rows:
        st.info(f"No questions in the last {choice}. Ask something in the chat and come back.",
                icon=":material/insights:")
        return
    frame = per_day(rows, days)

    left, right = st.columns(2)
    with left:
        card, show = _card("Requests per day", "requests")
        statuses = list(STATUS_LABELS.values())
        _show(card, show, frame[["day", *statuses]],
              _bars(frame, statuses, [STATUS_COLOURS[s] for s in statuses], "requests"))
    with right:
        card, show = _card("Time to answer", "time")
        times = frame.dropna(subset=["p50_seconds"])
        if show:
            card.dataframe(times[["day", "p50_seconds", "p95_seconds"]].rename(
                columns={"p50_seconds": "Median (s)", "p95_seconds": "Slowest 5% (s)"}), hide_index=True)
        else:
            long = times.melt(id_vars="day", value_vars=["p50_seconds", "p95_seconds"], var_name="series",
                              value_name="seconds").replace({"p50_seconds": "Median (p50)",
                                                             "p95_seconds": "Slowest 5% (p95)"})
            card.altair_chart(alt.Chart(long).mark_line(point=True).encode(
                x=alt.X("day:T", title=None, axis=alt.Axis(format="%d %b", labelAngle=0)),
                y=alt.Y("seconds:Q", title="seconds"),
                color=alt.Color("series:N", title=None, scale=alt.Scale(range=[LIGHT_BLUE, BLUE]),
                                legend=alt.Legend(orient="top")),
                tooltip=[alt.Tooltip("day:T", format="%d %b %Y"), "series:N", "seconds:Q"]).properties(height=220))
            card.caption("Answered requests only.")

    tools, guard, errors = st.columns(3)
    with tools, st.container(border=True, height="stretch"):
        st.markdown("**Tool calls**")
        counts = tool_counts(rows)
        if counts:
            st.altair_chart(_horizontal(counts))
        else:
            st.caption("No tool calls in this range.")
    with guard, st.container(border=True, height="stretch"):
        st.markdown("**How the guard sorted questions**")
        reached, refused = guard_counts(rows)
        st.markdown(f"### {reached} of {numbers['requests']}")
        st.caption("went to the agent as travel questions.")
        if refused:
            st.caption("The rest were turned away before the model saw them:")
            st.altair_chart(_horizontal(refused, "#8b8f98"))
        limited = sum(1 for r in rows if r["status"] == "limit")
        if limited:
            st.caption(f"{limited} more were turned away by the message rate limit.")
    with errors, st.container(border=True, height="stretch"):
        st.markdown("**Errors**")
        failed = [r for r in rows if r["status"] == "error"]
        if not failed:
            st.caption("No errors in this range.")
        for row in failed[-5:][::-1]:
            st.caption(f"{datetime.fromtimestamp(row['asked_at']):%d %b %H:%M} · {row['reason']}")

    left, right = st.columns(2)
    with left:
        card, show = _card("Tokens per day", "tokens")
        renamed = frame.rename(columns={"input_tokens": "Read by the model (input)",
                                        "output_tokens": "Written (output)"})
        columns = ["Read by the model (input)", "Written (output)"]
        _show(card, show, renamed[["day", *columns]], _bars(renamed, columns, [LIGHT_BLUE, BLUE], "tokens"))
    with right:
        card, show = _card("Cost per day", "cost")
        costs = frame.rename(columns={"cost_usd": "Cost (USD)"})
        _show(card, show, costs[["day", "Cost (USD)"]], _bars(costs, ["Cost (USD)"], [LIGHT_BLUE], "USD", whole=False))

    left, right = st.columns(2)
    with left:
        card, show = _card("Live searches per day", "searches")
        searches = frame.rename(columns={"serpapi": "SerpApi (flights, stays)", "google": "Google Maps"})
        columns = ["SerpApi (flights, stays)", "Google Maps"]
        _show(card, show, searches[["day", *columns]], _bars(searches, columns, [BLUE, LIGHT_BLUE], "searches"))
        card.caption("Searches that came from the cache are free and not counted.")
    with right, st.container(border=True, height="stretch"):
        st.markdown("**Live data services**")
        for service in cached_live_status():
            icon = "✅" if service.configured and service.working is not False else "⚠️" if service.configured else "⚪"
            st.caption(f"{icon} **{service.name}** ({service.provides}): {service.detail}")
        limits = " · ".join(f"{name} {limit}" for name, limit in config.SESSION_LIMITS.items())
        st.caption(f"Live searches allowed per chat: {limits}.")
