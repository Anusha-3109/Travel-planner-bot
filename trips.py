"""Builds a saved trip from a chat's costed plan.

A trip comes only from tool results, never from the model's text: the plan the
agent passed to calculate_trip_cost, that tool's prices, the check results, and
the search results the plan's ids point to (flight times, transit steps, stay
links, restaurant ratings). Places in the snapshot data add map positions.
"""

import json
from collections import Counter
from datetime import date, timedelta

from travel_data.catalog import load_catalog

KIND_ICONS = {"flight": ":material/flight:", "transit": ":material/train:", "drive": ":material/directions_car:",
              "stay": ":material/hotel:", "meal": ":material/restaurant:", "attraction": ":material/photo_camera:"}


def _output(call: dict) -> dict | None:
    try:
        data = json.loads(call.get("output") or "")
    except (json.JSONDecodeError, TypeError):
        return None
    return data if isinstance(data, dict) and "error" not in data else None


def tool_calls(messages: list[dict], upto: int | None = None) -> list[dict]:
    """Every tool call in the chat, up to and including message number upto."""
    chosen = messages if upto is None else messages[:upto + 1]
    return [call for message in chosen for call in message.get("tool_calls") or []]


def find_plan(calls: list[dict]) -> tuple[dict, dict, dict | None] | None:
    """The last costed plan: (plan, cost result, check result or None)."""
    cost = next(((c["args"].get("plan"), _output(c)) for c in reversed(calls)
                 if c.get("name") == "calculate_trip_cost" and _output(c)), None)
    if not cost or not isinstance(cost[0], dict):
        return None
    checks = next((_output(c) for c in reversed(calls) if c.get("name") == "check_constraints" and _output(c)), None)
    return cost[0], cost[1], checks


def index_results(calls: list[dict]) -> dict[str, dict]:
    """Every search result with an id, by id. _type says what it is (flight, stay, meal, transit, drive),
    and flights also get their search's date and cities."""
    found: dict[str, dict] = {}
    for call in calls:
        data = _output(call) or {}
        route = (data.get("route") or "").split(" → ")
        for group in data.get("airlines") or []:
            for flight in group.get("flights") or []:
                found[flight["id"]] = {**flight, "airline": group.get("airline"), "date": data.get("date"),
                                       "_type": "flight", "origin_city": route[0] if len(route) == 2 else None,
                                       "destination_city": route[-1] if len(route) == 2 else None}
        for stay in data.get("stays") or []:
            found[stay["id"]] = {**stay, "_type": "stay", "check_in": data.get("check_in"),
                                 "check_out": data.get("check_out")}
        for place in data.get("restaurants") or []:
            if place.get("id"):
                found[place["id"]] = {**place, "_type": "meal"}
        for option in data.get("public_transport") or []:
            found[option["id"]] = {**option, "_type": "transit"}
        drives = [data.get("driving") or {}] + [g for g in data.get("ground_options") or [] if g.get("id")]
        for drive in drives:
            if drive.get("id"):
                found[drive["id"]] = {**drive, "_type": "drive", "from": data.get("from"), "to": data.get("to")}
    return found


def _by_name(index: dict[str, dict], name: str | None, kind: str) -> dict | None:
    if not name:
        return None
    if name in index:
        return index[name]
    return next((r for r in index.values() if r["_type"] == kind and (r.get("name") or "").lower() == name.lower()),
                None)


def _transport_item(leg: dict, index: dict[str, dict]) -> dict:
    record = index.get(leg.get("item_id") or "")
    mode = leg.get("mode")
    if record and record["_type"] == "flight":
        number = " + ".join(record.get("flight_numbers") or [])
        return {"kind": "flight", "time": record.get("departs"),
                "title": f"{record.get('airline') or 'Flight'} {number}".strip(),
                "detail": f"{record.get('from_airport')} → {record.get('to_airport')} · {record.get('departs')} → "
                          f"{record.get('arrives')} · {record.get('duration')}", "price": record.get("price_text")}
    if record and record["_type"] == "transit":
        return {"kind": "transit", "time": None, "title": record.get("summary"),
                "detail": f"{record.get('origin')} → {record.get('destination')} · {record.get('duration')}",
                "price": record.get("fare_text"), "steps": record.get("steps") or []}
    if record and record["_type"] == "drive":
        return {"kind": "drive", "time": None, "title": "Taxi" if mode == "taxi" else "By car",
                "detail": f"{record.get('from') or leg.get('origin')} → {record.get('to') or leg.get('destination')} · "
                          f"{record.get('duration')} · {record.get('distance_km')} km",
                "price": record.get("cost_text")}
    kind = {"flight": "flight", "transit": "transit"}.get(mode, "drive")
    label = {"flight": "Flight (estimated)", "self-driving": "Drive (estimated)", "taxi": "Taxi (estimated)",
             "transit": "Public transport"}.get(mode, mode or "Transport")
    return {"kind": kind, "time": None, "title": label,
            "detail": f"{leg.get('origin') or ''} → {leg.get('destination') or ''}".strip(" →"), "price": None}


def _stay_record(name: str | None, index: dict[str, dict]) -> dict | None:
    record = _by_name(index, name, "stay")
    if record:
        return record
    return {"_type": "stay", "name": name} if name else None


def trip_dates(plan: dict, index: dict[str, dict]) -> tuple[date | None, date | None]:
    """Start and end from the plan's flights and stay, when it has them."""
    days: list[date] = []
    for day in plan.get("days") or []:
        for leg in [day.get("transportation") or {}, *(day.get("local_transport") or [])]:
            record = index.get(leg.get("item_id") or "")
            if record and record.get("date"):
                days.append(date.fromisoformat(record["date"]))
    stay = _stay_record(plan.get("stay"), index) or {}
    for key in ("check_in", "check_out"):
        if stay.get(key):
            days.append(date.fromisoformat(stay[key]))
    if not days:
        return None, None
    start = min(days)
    last_day = max((d.get("day", 1) for d in plan.get("days") or []), default=1)
    return start, max(max(days), start + timedelta(days=last_day - 1))


def build_trip(messages: list[dict], message_index: int) -> dict | None:
    """The trip for the costed plan in messages[message_index], or None if it has no costed plan."""
    calls = tool_calls(messages, message_index)
    found = find_plan(tool_calls([messages[message_index]]))
    if not found:
        return None
    plan, cost, checks = found
    index = index_results(calls)
    catalog = load_catalog()
    days = sorted(plan.get("days") or [], key=lambda d: d.get("day", 0))
    cities = Counter(d.get("city") for d in days if d.get("city"))
    first = days[0].get("transportation") or {} if days else {}
    origin_record = index.get(first.get("item_id") or "") or {}
    origin = first.get("origin") or origin_record.get("origin_city")
    destination = cities.most_common(1)[0][0] if cities else "Trip"
    start, end = trip_dates(plan, index)
    unpriced = cost.get("unpriced_items") or []

    timeline = []
    for day in days:
        number, items = day.get("day"), []
        for leg in [day.get("transportation"), *(day.get("local_transport") or [])]:
            if leg:
                items.append(_transport_item(leg, index))
        stay_name = day.get("accommodation") or (plan.get("stay") if number != (days[-1].get("day")) else None)
        for meal in ("breakfast", "lunch", "dinner"):
            if day.get(meal):
                record = _by_name(index, day[meal], "meal") or {}
                items.append({"kind": "meal", "time": None, "title": f"{meal.title()}: {record.get('name') or day[meal]}",
                              "detail": " · ".join(p for p in (record.get("rating_text") and f"⭐ {record['rating_text']}",
                                                               record.get("address")) if p),
                              "price": record.get("price_text"), "link": record.get("maps_link")})
        for name in day.get("attractions") or []:
            place = catalog.find_place("attraction", name, [day.get("city") or destination])
            items.append({"kind": "attraction", "time": None, "title": getattr(place, "name", name),
                          "detail": getattr(place, "address", "") or "", "price": None,
                          "link": getattr(place, "website", "") or None})
        if stay_name:
            stay = _stay_record(stay_name, index) or {}
            items.append({"kind": "stay", "time": None, "title": stay.get("name") or stay_name,
                          "detail": stay.get("kind") or "", "price": stay.get("per_night_text") and
                          f"{stay['per_night_text']} / night", "link": stay.get("link")})
        timeline.append({"day": number, "city": day.get("city"),
                         "date": (start + timedelta(days=number - 1)).isoformat() if start and number else None,
                         "items": items,
                         "unpriced": [u.split(": ", 1)[-1] for u in unpriced if u.startswith(f"day {number}:")]})

    chosen = _stay_record(plan.get("stay"), index)
    stays = [{**chosen, "chosen": True}] if chosen and chosen.get("name") else []
    stays += [{**r, "chosen": False} for r in index.values()
              if r["_type"] == "stay" and not (chosen and r.get("id") == chosen.get("id"))][:6]

    points = []
    for name, kind in ((origin, "origin"), (destination, "destination")):
        info = catalog.city_info.get((name or "").lower())
        if info and info.latitude is not None:
            points.append({"name": info.name, "kind": kind, "lat": info.latitude, "lon": info.longitude})
    for day in timeline:
        for item in day["items"]:
            if item["kind"] == "attraction":
                place = catalog.find_place("attraction", item["title"], [day["city"] or destination])
                if place and place.latitude is not None:
                    points.append({"name": place.name, "kind": "attraction", "lat": place.latitude,
                                   "lon": place.longitude})

    failed = [c for c in (checks or {}).get("hard_constraints", []) + (checks or {}).get("commonsense_checks", [])
              if not c.get("passed")]
    nights = f"{len(days) - 1} night{'s' if len(days) != 2 else ''}" if len(days) > 1 else "day trip"
    return {
        "title": f"{destination}, {nights}", "origin": origin, "destination": destination,
        "start": start.isoformat() if start else None, "end": end.isoformat() if end else None,
        "people": plan.get("people"), "budget": plan.get("budget"), "currency": cost.get("currency"),
        "cost": {key: cost.get(key) for key in ("total_text", "budget_text", "remaining_text", "totals_text",
                                                "within_budget")} | {"unpriced": unpriced},
        "checks": None if checks is None else {"passed": checks.get("passed"), "failed": failed},
        "days": timeline, "stays": stays, "points": points,
    }
