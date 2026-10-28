"""Result cards: the app draws flights, stays, restaurants, local transport and the
trip cost from the tools' own results, so they look the same in every answer and
every price is the tool's, not the model's wording.

Each card reads the JSON a tool returned (already screened by security.tool_output).
Results that can't be read, and tools without a card, are skipped.

Cards with a live result's id also take the next step: "Use this flight", "Use this stay",
"Add to the plan" (a restaurant at a chosen day and meal) and "Use this route" send a short
follow-up as the user's next message, naming the option by its id, so the planner swaps exactly
that item and the cost tool uses its exact live price. follow_up() writes those messages.
"""

import json
from contextvars import ContextVar

import streamlit as st

from frontend.i18n import t

COLUMNS = 3
FLIGHTS_PER_AIRLINE = 3
SEARCH_TOOLS = ("search_flights", "search_accommodations", "search_restaurants", "get_local_transport")
PLAN_TOOLS = ("calculate_trip_cost", "check_constraints")
MEALS = ("breakfast", "lunch", "dinner")
NAME_CHARS = 80  # option names in a follow-up are cut to this, as they come from outside services

# For the message being drawn: its key prefix (so buttons are unique per message), the latest plan
# (or None) and a counter. A context variable, as each session's script runs in its own thread.
_ACTIONS: ContextVar[dict | None] = ContextVar("card_actions", default=None)


def _name(text: object) -> str:
    return " ".join(str(text or "").split())[:NAME_CHARS]


def follow_up(kind: str, item: dict, data: dict, plan: dict | None, day: int | None = None,
              meal: str | None = None) -> str:
    """The message a card's button sends: which option, by its id, and what to do with it."""
    item_id = item.get("id")
    if kind == "flight":
        what = t("follow.flight", numbers=_name(" + ".join(item.get("flight_numbers") or [])), id=item_id)
        leg = t("follow.leg", route=_name(data.get("route")), date=data.get("date"))
        return t("follow.use_flight" if plan else "follow.plan_with", what=what, leg=leg)
    if kind == "stay":
        what = t("follow.stay", name=_name(item.get("name")), id=item_id)
        return t("follow.use_stay", what=what) if plan else t("follow.plan_with", what=what, leg="")
    if kind == "restaurant":
        return t("follow.restaurant", name=_name(item.get("name")), id=item_id, meal=t(f"meal.{meal}"), day=day)
    if kind == "transit":
        return t("follow.transit", name=_name(item.get("summary")), id=item_id, origin=_name(data.get("from")),
                 destination=_name(data.get("to")))
    raise ValueError(f"No follow-up for {kind}")


def _send(text: str) -> None:
    st.session_state.pending_question = text  # the chat asks it on this rerun


def _key(kind: str, item: dict) -> str:
    actions = _ACTIONS.get()
    actions["count"] += 1
    return f"{actions['prefix']}-{kind}-{item.get('id')}-{actions['count']}"


def _action(kind: str, item: dict, data: dict, label: str) -> None:
    """The card's next-step button (nothing without a live id or outside a chat message)."""
    actions = _ACTIONS.get()
    if actions is None or not item.get("id"):
        return
    plan = actions["plan"]
    if kind == "stay" and plan and plan.get("stay") == item["id"]:
        st.button(t("card.in_plan"), key=_key(kind, item), icon=":material/check:", disabled=True, width="stretch")
        return
    if kind == "flight" and not plan:
        label = t("card.plan_flight")
    if kind == "stay" and not plan:
        label = t("card.plan_stay")
    st.button(label, key=_key(kind, item), icon=":material/swap_horiz:", width="stretch",
              on_click=_send, args=(follow_up(kind, item, data, plan),))


def _restaurant_action(place: dict, data: dict) -> None:
    """A restaurant goes into the plan at a day and meal the user picks."""
    actions = _ACTIONS.get()
    plan = actions and actions["plan"]
    if not plan or not place.get("id"):
        return
    days = [d.get("day") for d in plan.get("days") or [] if isinstance(d.get("day"), int)]
    if not days:
        return
    key = _key("restaurant", place)
    with st.popover(t("card.add_to_plan"), icon=":material/add:", width="stretch"):
        day = st.selectbox(t("card.day_label"), days, key=f"{key}-day", format_func=lambda d: t("card.day", day=d))
        meal = st.selectbox(t("card.meal_label"), MEALS, index=2, key=f"{key}-meal",
                            format_func=lambda m: t(f"meal.{m}"))
        if st.button(t("card.add"), key=f"{key}-add", type="primary", width="stretch"):
            _send(follow_up("restaurant", place, data, plan, day, meal))
            st.rerun()


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
        st.badge(t("card.live"), icon=":material/bolt:", color="green")
    elif source.startswith("estimate"):
        st.badge(t("card.estimate"), icon=":material/straighten:", color="orange")
    elif source:
        st.badge(t("card.snapshot"), icon=":material/history:", color="gray")


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
        return t("card.nonstop")
    via = ", ".join(flight.get("layovers") or [])
    return (t("card.stop") if stops == 1 else t("card.stops", count=stops)) + (" " + t("card.via", places=via) if via else "")


def _airline_card(group: dict, data: dict) -> None:
    flights = group.get("flights") or []
    cheapest = flights[0].get("price_text") if flights else None
    st.markdown(f"**{_md(group.get('airline') or t('card.flights'))}**")
    st.caption(t("card.flight_count", count=group.get("flight_count", len(flights)))
               + (" · " + t("card.from", price=_md(cheapest)) if cheapest else ""))
    for flight in flights[:FLIGHTS_PER_AIRLINE]:
        _flight_line(flight, data)
    if len(flights) > FLIGHTS_PER_AIRLINE:
        st.space("stretch")
        with st.popover(t("card.more", count=len(flights) - FLIGHTS_PER_AIRLINE), width="stretch"):
            for flight in flights[FLIGHTS_PER_AIRLINE:]:
                _flight_line(flight, data)


def _flight_line(flight: dict, data: dict) -> None:
    number = " + ".join(flight.get("flight_numbers") or [])
    st.markdown(f"{_md(flight.get('departs') or '?')} → {_md(flight.get('arrives') or '?')}  \n"
                f"**{_md(flight.get('price_text') or t('card.price_not_shown'))}**")
    st.caption(" · ".join(p for p in (number, f"{flight.get('from_airport')} → {flight.get('to_airport')}",
                                      flight.get("duration"), _stops(flight)) if p))
    _action("flight", flight, data, t("card.use_flight"))


def _estimated_flight_card(estimate: dict) -> None:
    st.markdown(f"**{t('card.estimated_flight')}**")
    st.markdown(t("card.about", duration=estimate.get("estimated_nonstop_duration")) +
                f"  \n**{t('card.no_price_data')}**")
    st.caption(t("card.distance_note", km=f"{estimate.get('distance_km'):,}"))


def _shown(data: dict, shown_key: str, found_key: str) -> str:
    """The heading's "10 of 11 shown" part, when a tool shows fewer results than it found."""
    shown, found = data.get(shown_key), data.get(found_key)
    return " · " + t("card.shown", shown=shown, found=found) if isinstance(shown, int) and isinstance(found, int) and shown < found else ""


def flight_cards(data: dict) -> None:
    st.markdown(f"##### :material/flight: {t('card.flights')} · {_md(data.get('route', ''))} · {data.get('date', '')}"
                + _shown(data, "flights_shown", "flight_count"))
    _source_badge(data.get("flights_source"))
    if data.get("airlines"):
        _grid(data["airlines"], lambda group: _airline_card(group, data))
    elif isinstance(data.get("estimated_flight"), dict):
        _grid([data["estimated_flight"]], _estimated_flight_card)
    else:
        st.caption(t("card.no_flights"))
    if data.get("ground_options"):
        st.caption(t("card.by_road"))
        _grid(data["ground_options"], _ground_card)


# Stays

def _live_stay_card(stay: dict, data: dict) -> None:
    st.markdown(f"**{_md(stay.get('name'))}**")
    st.caption(_md(stay.get("kind") or stay.get("provider") or ""))
    st.markdown(t("card.per_night", price=_md(stay.get("per_night_text", "n/a"))) + "  \n**"
                + t("card.total", price=_md(stay.get("total_text", "n/a"))) + "**")
    st.caption(f"⭐ {_md(stay.get('rating_text', t('card.no_rating')))}")
    if stay.get("cancellation_text"):
        st.badge(stay["cancellation_text"], icon=":material/event_available:", color="green")
    label = t("card.view_airbnb") if stay.get("provider") == "Airbnb" else t("card.view_hotel")
    _link(label, stay.get("link"))
    _action("stay", stay, data, t("card.use_stay"))


def _snapshot_stay_card(stay: dict) -> None:
    st.markdown(f"**{_md(stay.get('name'))}**")
    st.caption(_md(stay.get("room_type") or ""))
    nightly = stay.get("price_per_night")
    if isinstance(nightly, (int, float)):
        total = "  \n**" + t("card.total", price=_md(_usd(stay["total_cost"]))) + "**" if "total_cost" in stay else ""
        st.markdown(t("card.per_night", price=_md(_usd(nightly))) + total)
    else:
        st.markdown(t("card.no_snapshot_price"))
    guests = stay.get("maximum_occupancy")
    details = [f"⭐ {stay.get('rating')}" if isinstance(stay.get("rating"), (int, float)) else "",
               t("card.up_to_guests", count=guests) if isinstance(guests, int) else "",
               t("card.min_nights", count=stay.get("minimum_nights"))]
    st.caption(" · ".join(d for d in details if d))


def stay_cards(data: dict) -> None:
    dates = f" · {data['check_in']} {t('card.to')} {data['check_out']}" if data.get("check_in") else ""
    st.markdown(f"##### :material/hotel: {t('card.stays')} · {_md(data.get('city', ''))}{dates}"
                + _shown(data, "stays_shown", "stay_count"))
    _source_badge(data.get("stays_source"))
    if data.get("stays"):
        _grid(data["stays"], lambda stay: _live_stay_card(stay, data))
    elif data.get("accommodations"):
        _grid(data["accommodations"], _snapshot_stay_card)
    else:
        st.caption(t("card.no_stays"))


# Restaurants

def _live_restaurant_card(place: dict, data: dict) -> None:
    st.markdown(f"**{_md(place.get('name'))}**")
    st.caption(_md(place.get("address") or ""))
    st.markdown(f"⭐ {_md(place.get('rating_text', t('card.no_rating')))}  \n"
                f"{_md(place.get('price_text', t('card.price_not_listed')))}")
    if place.get("open_now") is True:
        st.badge(t("card.open_now"), color="green")
    elif place.get("open_now") is False:
        st.badge(t("card.closed_now"), color="red")
    _link(t("card.map"), place.get("maps_link"))
    _restaurant_action(place, data)


def _snapshot_restaurant_card(place: dict) -> None:
    st.markdown(f"**{_md(place.get('name'))}**")
    st.caption(", ".join(place.get("cuisines") or []))
    cost = place.get("average_cost_per_person")
    st.markdown(f"⭐ {place.get('rating')}  \n{_md(_usd(cost)) if isinstance(cost, (int, float)) else t('card.price_na')} "
                + t("card.per_person"))


def restaurant_cards(data: dict) -> None:
    cuisine = (data.get("filters") or {}).get("cuisine")
    st.markdown(f"##### :material/restaurant: {t('card.restaurants')} · {_md(data.get('city', ''))}"
                + (f" · {_md(cuisine)}" if cuisine else ""))
    _source_badge(data.get("restaurants_source"))
    places = data.get("restaurants") or []
    if not places:
        st.caption(t("card.no_restaurants"))
    elif "rating_text" in places[0] or "maps_link" in places[0]:
        _grid(places, lambda place: _live_restaurant_card(place, data))
    else:
        _grid(places, _snapshot_restaurant_card)


# Local transport

def _transit_card(option: dict, data: dict) -> None:
    changes = option.get("transfers") or 0
    st.markdown(f"**{_md(option.get('summary'))}**")
    st.caption(f"{option.get('duration')} · " + (t("card.no_changes") if not changes else t("card.changes", count=changes)))
    st.markdown(_md(option.get("fare_text", "")))
    st.space("stretch")
    with st.popover(t("card.steps"), width="stretch"):  # a popover, as expanders can't sit inside the plan's expander
        st.markdown("\n".join(f"1. {_md(step)}" for step in option.get("steps") or []))
    if (_ACTIONS.get() or {}).get("plan"):
        _action("transit", option, data, t("card.use_route"))


def _drive_card(driving: dict) -> None:
    st.markdown(f"**{t('card.by_car')}**")
    st.caption(f"{driving.get('duration')} · {driving.get('distance_km')} km")
    st.markdown(_md(driving.get("cost_text", "")))
    st.caption(t("card.no_taxi_fare"))


def _ground_card(option: dict) -> None:
    st.markdown(f"**{_md(str(option.get('mode', '')).title())}**")
    st.caption(f"{option.get('duration')} · {option.get('distance_km')} km")
    cost = option.get("cost_per_vehicle")
    st.markdown(_md(option.get("cost_text") or (t("card.per_vehicle", price=_usd(cost)) if cost is not None
                                                 else t("card.no_fare"))))


def transport_cards(data: dict) -> None:
    st.markdown(f"##### :material/directions_transit: {t('card.getting_around')} · {_md(data.get('from', ''))} → "
                f"{_md(data.get('to', ''))}"
                + (f" · {_md(data['departure_time'])}" if data.get("departure_time") else ""))
    _source_badge(data.get("transport_source"))
    cards = [(lambda o: _transit_card(o, data), o) for o in data.get("public_transport") or []]
    if data.get("driving"):
        cards.append((_drive_card, data["driving"]))
    cards += [(_ground_card, g) for g in data.get("ground_options") or []]
    _grid(cards, lambda card: card[0](card[1]))
    st.caption(_md(data.get("timetable_note") or t("card.timetable")))


# Trip cost and checks

COST_TYPES = ("transportation", "accommodation", "meals", "attractions")  # labels: card.cost.<type>


def cost_card(cost: dict, checks: dict | None = None) -> None:
    with st.container(border=True):
        st.markdown(f"##### :material/payments: {t('card.trip_cost', count=cost.get('people', ''))}")
        totals = cost.get("totals_text") or {}
        with st.container(horizontal=True):
            st.metric(t("card.total_metric"), cost.get("total_text") or "n/a", border=True)
            if cost.get("budget") is not None:
                remaining = cost.get("remaining_budget") or 0
                st.metric(t("card.budget"), cost.get("budget_text"), border=True)
                st.metric(t("card.left") if remaining >= 0 else t("card.over_budget"), cost.get("remaining_text"),
                          delta=t("card.within_budget") if remaining >= 0 else t("card.over_budget_delta"),
                          delta_color="normal" if remaining >= 0 else "inverse", border=True)
        st.caption(" · ".join(f"{t('card.cost.' + key)}: {_md(totals[key])}" for key in COST_TYPES if totals.get(key)))
        unpriced = cost.get("unpriced_items") or []
        if unpriced:
            st.warning(t("card.unpriced", count=len(unpriced)), icon=":material/info:")
        if checks:
            failed = [c for c in checks.get("hard_constraints", []) + checks.get("commonsense_checks", [])
                      if not c.get("passed")]
            if not failed:
                st.badge(t("card.all_checks"), icon=":material/check_circle:", color="green")
            for check in failed:
                st.badge(f"{check.get('check')}: {check.get('detail')}", icon=":material/error:", color="red")
        with st.expander(t("card.breakdown")):
            for line in cost.get("items") or []:
                price = line.get("cost_text") or t("card.no_price")
                st.markdown(f"- {t('card.day', day=line.get('day'))} · {_md(line.get('item'))} · **{_md(price)}**")
            for item in unpriced:
                st.markdown(f"- {_md(item)} · *{t('card.no_price_italic')}*")


RENDERERS = {"search_flights": flight_cards, "search_accommodations": stay_cards,
             "search_restaurants": restaurant_cards, "get_local_transport": transport_cards}


def _latest(tool_calls: list[dict], name: str) -> dict | None:
    for call in reversed(tool_calls):
        if call.get("name") == name and (data := _output(call)):
            return data
    return None


def render_result_cards(tool_calls: list[dict], key: str | None = None, plan: dict | None = None) -> None:
    """Cards for one answer's tool results. In a full plan the cost card comes first and the
    search results sit in a collapsed section; otherwise the search results are shown directly.
    With a key (one per chat message), cards get their next-step buttons, using plan (the latest
    costed plan in the chat, or None) to word them."""
    token = _ACTIONS.set({"prefix": key, "plan": plan, "count": 0} if key else None)
    try:
        _draw_cards(tool_calls)
    finally:
        _ACTIONS.reset(token)


def _draw_cards(tool_calls: list[dict]) -> None:
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
            with st.expander(t("card.options_found_one") if len(searches) == 1
                             else t("card.options_found", count=len(searches))):
                for render, data in searches:
                    render(data)
        return
    for render, data in searches:
        render(data)
