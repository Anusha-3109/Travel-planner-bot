"""Result cards: the app draws flights, stays, restaurants, local transport and the
trip cost from the tools' own results, so they look the same in every answer and
every price is the tool's, not the model's wording.

Each card reads the JSON a tool returned (already screened by security.tool_output).
Results that can't be read, and tools without a card, are skipped.
"""

import json

import streamlit as st

COLUMNS = 3
FLIGHTS_PER_AIRLINE = 3
SEARCH_TOOLS = ("search_flights", "search_accommodations", "search_restaurants", "get_local_transport")
PLAN_TOOLS = ("calculate_trip_cost", "check_constraints")


def _md(text: object) -> str:
    # Streamlit treats text between two "$" signs as LaTeX, which garbles prices.
    return str(text).replace("$", r"\$")


def _usd(amount) -> str:
    if not isinstance(amount, (int, float)):
        return "n/a"
    return f"${amount:,.0f}" if float(amount).is_integer() else f"${amount:,.2f}"


def _output(call: dict) -> dict | None:
    try:
        data = json.loads(call.get("output") or "")
    except (json.JSONDecodeError, TypeError):
        return None
    return data if isinstance(data, dict) and "error" not in data else None


def _source_badge(source: str | None) -> None:
    source = source or ""
    if source.startswith("live"):
        st.badge("Live", icon=":material/bolt:", color="green")
    elif source:
        st.badge("Snapshot", icon=":material/history:", color="gray")


def _grid(items: list, draw) -> None:
    """Equal-height bordered cards, COLUMNS per row."""
    for start in range(0, len(items), COLUMNS):
        columns = st.columns(COLUMNS)
        for column, item in zip(columns, items[start:start + COLUMNS]):
            with column.container(border=True, height="stretch"):
                draw(item)


def _link(label: str, url: str | None) -> None:
    if url:
        st.space("stretch")
        st.link_button(label, url, icon=":material/open_in_new:", width="stretch")


# Flights

def _stops(flight: dict) -> str:
    stops = flight.get("stops") or 0
    if not stops:
        return "Nonstop"
    via = ", ".join(flight.get("layovers") or [])
    return f"{stops} stop{'s' if stops > 1 else ''}" + (f" via {via}" if via else "")


def _airline_card(group: dict) -> None:
    flights = group.get("flights") or []
    cheapest = flights[0].get("price_text") if flights else None
    st.markdown(f"**{_md(group.get('airline') or 'Flights')}**")
    st.caption(f"{group.get('flight_count', len(flights))} flight(s)" + (f" · from {_md(cheapest)}" if cheapest else ""))
    for flight in flights[:FLIGHTS_PER_AIRLINE]:
        _flight_line(flight)
    if len(flights) > FLIGHTS_PER_AIRLINE:
        st.space("stretch")
        with st.popover(f"{len(flights) - FLIGHTS_PER_AIRLINE} more", width="stretch"):
            for flight in flights[FLIGHTS_PER_AIRLINE:]:
                _flight_line(flight)


def _flight_line(flight: dict) -> None:
    number = " + ".join(flight.get("flight_numbers") or [])
    st.markdown(f"{_md(flight.get('departs') or '?')} → {_md(flight.get('arrives') or '?')}  \n"
                f"**{_md(flight.get('price_text') or 'Price not shown')}**")
    st.caption(" · ".join(p for p in (number, f"{flight.get('from_airport')} → {flight.get('to_airport')}",
                                      flight.get("duration"), _stops(flight)) if p))


def _snapshot_flight_card(flight: dict) -> None:
    st.markdown(f"**Flight {_md(flight.get('flight_number'))}**")
    st.markdown(f"{flight.get('departure')} → {flight.get('arrival')}  \n**{_md(_usd(flight.get('price_per_person')))} "
                "per person**")
    st.caption(" · ".join(p for p in (flight.get("duration"), f"{flight.get('distance_miles')} miles") if p))


def flight_cards(data: dict) -> None:
    st.markdown(f"##### :material/flight: Flights · {_md(data.get('route', ''))} · {data.get('date', '')}")
    _source_badge(data.get("flights_source"))
    if data.get("airlines"):
        _grid(data["airlines"], _airline_card)
    elif data.get("flights"):
        _grid(data["flights"], _snapshot_flight_card)
    else:
        st.caption("No flights found for this date.")


# Stays

def _live_stay_card(stay: dict) -> None:
    st.markdown(f"**{_md(stay.get('name'))}**")
    st.caption(_md(stay.get("kind") or stay.get("provider") or ""))
    st.markdown(f"{_md(stay.get('per_night_text', 'n/a'))} / night  \n**{_md(stay.get('total_text', 'n/a'))} total**")
    st.caption(f"⭐ {_md(stay.get('rating_text', 'No rating'))}")
    if stay.get("cancellation_text"):
        st.badge(stay["cancellation_text"], icon=":material/event_available:", color="green")
    label = "View on Airbnb" if stay.get("provider") == "Airbnb" else "View hotel"
    _link(label, stay.get("link"))


def _snapshot_stay_card(stay: dict) -> None:
    st.markdown(f"**{_md(stay.get('name'))}**")
    st.caption(_md(stay.get("room_type") or ""))
    total = f"  \n**{_md(_usd(stay['total_cost']))} total**" if "total_cost" in stay else ""
    st.markdown(f"{_md(_usd(stay.get('price_per_night')))} / night{total}")
    st.caption(f"⭐ {stay.get('rating')} · up to {stay.get('maximum_occupancy')} guests · "
               f"min {stay.get('minimum_nights')} night(s)")


def stay_cards(data: dict) -> None:
    dates = f" · {data['check_in']} to {data['check_out']}" if data.get("check_in") else ""
    st.markdown(f"##### :material/hotel: Stays · {_md(data.get('city', ''))}{dates}")
    _source_badge(data.get("stays_source"))
    if data.get("stays"):
        _grid(data["stays"], _live_stay_card)
    elif data.get("accommodations"):
        _grid(data["accommodations"], _snapshot_stay_card)
    else:
        st.caption("No stays match these filters.")


# Restaurants

def _live_restaurant_card(place: dict) -> None:
    st.markdown(f"**{_md(place.get('name'))}**")
    st.caption(_md(place.get("address") or ""))
    st.markdown(f"⭐ {_md(place.get('rating_text', 'No rating'))}  \n{_md(place.get('price_text', 'Price not listed'))}")
    if place.get("open_now") is True:
        st.badge("Open now", color="green")
    elif place.get("open_now") is False:
        st.badge("Closed now", color="red")
    _link("Map", place.get("maps_link"))


def _snapshot_restaurant_card(place: dict) -> None:
    st.markdown(f"**{_md(place.get('name'))}**")
    st.caption(", ".join(place.get("cuisines") or []))
    cost = place.get("average_cost_per_person")
    st.markdown(f"⭐ {place.get('rating')}  \n{_md(_usd(cost)) if isinstance(cost, (int, float)) else 'Price n/a'} "
                "per person")


def restaurant_cards(data: dict) -> None:
    cuisine = (data.get("filters") or {}).get("cuisine")
    st.markdown(f"##### :material/restaurant: Restaurants · {_md(data.get('city', ''))}"
                + (f" · {_md(cuisine)}" if cuisine else ""))
    _source_badge(data.get("restaurants_source"))
    places = data.get("restaurants") or []
    if not places:
        st.caption("No restaurants match these filters.")
    elif "rating_text" in places[0] or "maps_link" in places[0]:
        _grid(places, _live_restaurant_card)
    else:
        _grid(places, _snapshot_restaurant_card)


# Local transport

def _transit_card(option: dict) -> None:
    changes = option.get("transfers") or 0
    st.markdown(f"**{_md(option.get('summary'))}**")
    st.caption(f"{option.get('duration')} · {'no changes' if not changes else f'{changes} change(s)'}")
    st.markdown(_md(option.get("fare_text", "")))
    st.space("stretch")
    with st.popover("Steps", width="stretch"):  # a popover, as expanders can't sit inside the plan's expander
        st.markdown("\n".join(f"1. {_md(step)}" for step in option.get("steps") or []))


def _drive_card(driving: dict) -> None:
    st.markdown("**By car or taxi**")
    st.caption(f"{driving.get('duration')} · {driving.get('distance_km')} km")
    st.markdown(_md(driving.get("cost_text", "")))
    st.caption("Taxis: no fare data")


def _ground_card(option: dict) -> None:
    st.markdown(f"**{_md(str(option.get('mode', '')).title())}**")
    st.caption(f"{option.get('duration')} · {option.get('distance_km')} km")
    st.markdown(f"{_md(_usd(option.get('cost_per_vehicle')))} per vehicle")


def transport_cards(data: dict) -> None:
    st.markdown(f"##### :material/directions_transit: Getting around · {_md(data.get('from', ''))} → "
                f"{_md(data.get('to', ''))}")
    _source_badge(data.get("transport_source"))
    cards = [(_transit_card, o) for o in data.get("public_transport") or []]
    if data.get("driving"):
        cards.append((_drive_card, data["driving"]))
    cards += [(_ground_card, g) for g in data.get("ground_options") or []]
    _grid(cards, lambda card: card[0](card[1]))
    st.caption("Departure times come from the current timetable and will differ on the travel day.")


# Trip cost and checks

COST_TYPES = {"transportation": "Transport", "accommodation": "Stay", "meals": "Meals", "attractions": "Attractions"}


def cost_card(cost: dict, checks: dict | None = None) -> None:
    with st.container(border=True):
        st.markdown(f"##### :material/payments: Trip cost · {cost.get('people', '')} traveller(s)")
        totals = cost.get("totals_text") or {}
        with st.container(horizontal=True):
            st.metric("Total", cost.get("total_text") or "n/a", border=True)
            if cost.get("budget") is not None:
                remaining = cost.get("remaining_budget") or 0
                st.metric("Budget", cost.get("budget_text"), border=True)
                st.metric("Left" if remaining >= 0 else "Over budget", cost.get("remaining_text"),
                          delta="within budget" if remaining >= 0 else "over budget",
                          delta_color="normal" if remaining >= 0 else "inverse", border=True)
        st.caption(" · ".join(f"{label}: {_md(totals[key])}" for key, label in COST_TYPES.items() if totals.get(key)))
        unpriced = cost.get("unpriced_items") or []
        if unpriced:
            st.warning(f"{len(unpriced)} item(s) have no price data, so the real total is higher.",
                       icon=":material/info:")
        if checks:
            failed = [c for c in checks.get("hard_constraints", []) + checks.get("commonsense_checks", [])
                      if not c.get("passed")]
            if not failed:
                st.badge("All checks passed", icon=":material/check_circle:", color="green")
            for check in failed:
                st.badge(f"{check.get('check')}: {check.get('detail')}", icon=":material/error:", color="red")
        with st.expander("Cost breakdown"):
            for line in cost.get("items") or []:
                price = line.get("cost_text") or "no price"
                st.markdown(f"- Day {line.get('day')} · {_md(line.get('item'))} · **{_md(price)}**")
            for item in unpriced:
                st.markdown(f"- {_md(item)} · *no price data*")


RENDERERS = {"search_flights": flight_cards, "search_accommodations": stay_cards,
             "search_restaurants": restaurant_cards, "get_local_transport": transport_cards}


def _latest(tool_calls: list[dict], name: str) -> dict | None:
    for call in reversed(tool_calls):
        if call.get("name") == name and (data := _output(call)):
            return data
    return None


def render_result_cards(tool_calls: list[dict]) -> None:
    """Cards for one answer's tool results. In a full plan the cost card comes first and the
    search results sit in a collapsed section; otherwise the search results are shown directly."""
    searches, seen = [], set()
    for call in tool_calls:
        data = _output(call) if call.get("name") in RENDERERS else None
        key = (call.get("name"), call.get("output"))
        if data and key not in seen:  # the same search twice is shown once
            seen.add(key)
            searches.append((RENDERERS[call["name"]], data))
    cost = _latest(tool_calls, "calculate_trip_cost")
    if cost:
        cost_card(cost, _latest(tool_calls, "check_constraints"))
        if searches:
            with st.expander(f"Options found ({len(searches)} search{'es' if len(searches) > 1 else ''})"):
                for render, data in searches:
                    render(data)
        return
    for render, data in searches:
        render(data)
