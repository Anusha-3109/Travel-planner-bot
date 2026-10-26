"""The My trips page and the trip page (plan, route, stays and Discover).

Trips are saved from a costed plan in the chat ("Save as trip"). The trip page
shows the plan as a day-by-day timeline, its stops on a map, the stays found for
it, and places to see in the destination from the knowledge base.
"""

from datetime import date

import pandas as pd
import pydeck as pdk
import streamlit as st

from backend.rag.retriever import SearchPlan, retrieve
from backend.storage import history
from frontend.components.common import PAGES, set_mode, start_new_chat
from frontend.html import render

POINT_COLOURS = {"origin": [139, 143, 152], "destination": [59, 130, 246], "attraction": [249, 115, 22]}


def _dates(trip: dict) -> str:
    if not trip.get("start"):
        return "dates not known"
    start, end = date.fromisoformat(trip["start"]), date.fromisoformat(trip["end"] or trip["start"])
    return f"{start:%d %b} to {end:%d %b %Y}"


def _summary(trip: dict) -> str:
    people = trip.get("people")
    parts = [_dates(trip), f"{people} traveller{'s' if people != 1 else ''}" if people else None,
             f"budget {trip['cost']['budget_text']}" if trip["cost"].get("budget_text") else None]
    return " · ".join(p for p in parts if p)


def my_trips() -> None:
    st.title("My trips")
    st.caption("Trips saved from a costed plan in the chat. Press **Save as trip** under a plan to add one.")
    trips = history.list_trips()
    if not trips:
        st.info("No trips yet. Plan a trip in the chat, then press Save as trip under the plan.",
                icon=":material/luggage:")
        if st.button("Plan a trip", icon=":material/auto_awesome:", type="primary"):
            st.switch_page(PAGES["chat"])
        return
    columns = st.columns(3)
    for number, trip in enumerate(trips):
        with columns[number % 3].container(border=True, height="stretch"):
            st.markdown(f"**{trip['title']}**")
            st.caption(_summary(trip))
            if trip["cost"].get("total_text"):
                st.markdown(f"Total **{trip['cost']['total_text']}**".replace("$", r"\$"))
            st.space("stretch")
            open_, delete = st.columns(2)
            if open_.button("Open", key=f"open-trip-{trip['id']}", icon=":material/open_in_new:", width="stretch"):
                st.switch_page(PAGES["trip"], query_params={"trip": trip["id"]})
            if delete.button("Delete", key=f"delete-trip-{trip['id']}", icon=":material/delete:", width="stretch"):
                history.delete_trip(trip["id"])
                st.rerun()


def _plan_tab(trip: dict) -> None:
    cost = trip["cost"]
    with st.container(border=True, horizontal=True):
        st.metric("Total", (cost.get("total_text") or "n/a").replace("$", r"\$"), border=True)
        if cost.get("budget_text"):
            st.metric("Budget", cost["budget_text"].replace("$", r"\$"), border=True)
            st.metric("Left" if cost.get("within_budget") is not False else "Over budget",
                      (cost.get("remaining_text") or "").replace("$", r"\$"), border=True)
    if cost.get("unpriced"):
        st.caption(f"{len(cost['unpriced'])} item(s) have no price data, so the real total is higher.")
    if trip.get("checks") and trip["checks"]["failed"]:
        for check in trip["checks"]["failed"]:
            st.warning(f"{check['check']}: {check['detail']}", icon=":material/error:")
    for day in trip["days"]:
        render.timeline_day(day)  # frontend/html/timeline.html


def _route_tab(trip: dict) -> None:
    points = trip.get("points") or []
    if not points:
        st.caption("No map positions for this trip's places: its cities aren't in the snapshot data.")
        return
    frame = pd.DataFrame(points)
    frame["colour"] = frame["kind"].map(POINT_COLOURS)
    legs = [{"from": [a["lon"], a["lat"]], "to": [b["lon"], b["lat"]]}
            for a, b in zip(points, points[1:]) if {a["kind"], b["kind"]} == {"origin", "destination"}]
    layers = [pdk.Layer("ScatterplotLayer", frame, get_position="[lon, lat]", get_fill_color="colour",
                        get_radius=120, radius_min_pixels=5, pickable=True)]
    if legs:
        layers.append(pdk.Layer("ArcLayer", pd.DataFrame(legs), get_source_position="from",
                                get_target_position="to", get_source_color=[139, 143, 152],
                                get_target_color=[59, 130, 246], get_width=3))
    focus = frame[frame["kind"] != "origin"] if len(frame) > 1 else frame
    view = pdk.ViewState(latitude=float(focus["lat"].mean()), longitude=float(focus["lon"].mean()),
                         zoom=11 if not legs else 4)
    st.pydeck_chart(pdk.Deck(layers=layers, initial_view_state=view, tooltip={"text": "{name}"}), height=420)
    st.caption("Grey: where you start · blue: the destination · orange: places in the plan.")
    st.dataframe(frame[["name", "kind"]].rename(columns={"name": "Stop", "kind": "Type"}), hide_index=True)


def _stays_tab(trip: dict) -> None:
    stays = trip.get("stays") or []
    if not stays:
        st.caption("No stays were searched for this trip.")
        return
    columns = st.columns(3)
    for number, stay in enumerate(stays):
        with columns[number % 3].container(border=True, height="stretch"):
            if stay.get("chosen"):
                st.badge("In the plan", icon=":material/check:", color="green")
            st.markdown(f"**{stay.get('name')}**")
            st.caption(stay.get("kind") or "")
            if stay.get("per_night_text"):
                st.markdown(f"{stay['per_night_text']} / night  \n**{stay.get('total_text')} total**"
                            .replace("$", r"\$"))
            if stay.get("rating_text"):
                st.caption(f"⭐ {stay['rating_text']}")
            if stay.get("link"):
                st.space("stretch")
                st.link_button("Book on the site", stay["link"], icon=":material/open_in_new:", width="stretch")
    st.caption("TripMate doesn't book or take payments: booking happens on Airbnb or the hotel's site.")


def _discover_tab(trip: dict) -> None:
    city = trip.get("destination")
    query = st.text_input("Look for", value="top sights and museums", key=f"discover-{trip['id']}")
    # The knowledge base directly: free, no model call.
    documents = retrieve(query or "things to see", category="attraction", city=city,
                         plan=SearchPlan(queries=[query or "things to see"]), k=9).documents
    if not documents:
        st.caption(f"No places for {city} in the snapshot data.")
    columns = st.columns(3)
    for number, document in enumerate(documents):
        with columns[number % 3].container(border=True, height="stretch"):
            st.markdown(f"**{document.metadata.get('name')}**")
            st.caption(document.page_content[:220])
    if st.button(f"Ask about {city} in Explore mode", icon=":material/explore:"):
        start_new_chat()
        set_mode("explore")
        st.session_state.pending_question = f"What are the best things to see and do in {city}?"
        st.switch_page(PAGES["chat"])


def trip_page() -> None:
    trip = history.load_trip(st.query_params.get("trip") or "")
    if trip is None:
        st.title("Trip not found")
        st.caption("It may have been deleted.")
        if st.button("Back to My trips", icon=":material/arrow_back:"):
            st.switch_page(PAGES["trips"])
        return
    st.caption("My trips")
    st.title(trip["title"])
    st.caption(_summary(trip) + (f" · from {trip['origin']}" if trip.get("origin") else ""))
    plan, route, stays, discover = st.tabs(["Plan", "Route", "Stays", "Discover"])
    with plan:
        _plan_tab(trip)
    with route:
        _route_tab(trip)
    with stays:
        _stays_tab(trip)
    with discover:
        _discover_tab(trip)
