"""Trip cost and constraint checks for a day-by-day plan.

The plan follows TravelPlanner's format: each day has a city, optional
transportation, three meals, attractions and a place to stay. Every item is
looked up in the catalog by name, so costs come from the data, never from the
model. Costs follow TravelPlanner's rules: flights and meals are per person,
cars seat 5, taxis seat 4, and a group larger than a stay's occupancy books
several rooms. Attractions have no prices in the data, so they cost 0.

Live results from the search tools (flights, stays, restaurants, public
transport) are referred to by their id, such as "flight-165d3381", and costed
from the price stored with that id: flights and transit fares per person, a
live stay's nightly price for the whole booking, and a live restaurant's
estimated cost per person (the middle of Google's price range).

Some prices don't exist (estimated flights, many restaurants outside the US,
transit fares Google doesn't publish). Those items are listed as unpriced
rather than guessed, and the budget check says it is incomplete. Totals can be
shown in any currency at today's exchange rate.
"""

import json
import math
from collections import Counter
from dataclasses import dataclass
from typing import Literal

from langchain_core.tools import tool
from pydantic import BaseModel, Field

from live import fx, items
from live.http import LiveDataError
from security.validation import InputValidationError, validate_budget, validate_people
from travel_data.catalog import SELF_DRIVING_SEATS, TAXI_SEATS, load_catalog

HouseRule = Literal["smoking", "parties", "children under 10", "visitors", "pets"]
RoomType = Literal["entire room", "private room", "shared room", "not shared room"]
TransportRule = Literal["no flight", "no self-driving"]


class Transport(BaseModel):
    mode: Literal["flight", "self-driving", "taxi", "transit"]
    item_id: str | None = Field(
        default=None, description="The id of a live flight ('flight-...') from search_flights or a public "
                                  "transport route ('transit-...') from get_local_transport.")
    flight_number: str | None = Field(
        default=None, description="For snapshot US flights from search_flights, e.g. 'F3792603'. Leave item_id "
                                  "and flight_number empty for an estimated flight.")
    origin: str | None = Field(default=None, description="Required for self-driving, taxi and estimated flights.")
    destination: str | None = Field(default=None, description="Required for self-driving, taxi and estimated flights.")


@dataclass(frozen=True)
class EstimatedFlight:
    origin: str
    destination: str
    distance_km: int


# Live items, looked up by id, with the attributes the cost and check code uses
# for catalog items.
@dataclass(frozen=True)
class LiveFlight:
    number: str
    origin: str
    destination: str
    price: float | None  # per person
    checked_at: str


@dataclass(frozen=True)
class LiveTransit:
    summary: str
    origin: str
    destination: str
    fare: float | None  # per person
    checked_at: str
    mode: str = "transit"


@dataclass(frozen=True)
class LiveDrive:
    """A live driving route; its cost (per car, US only) is an IRS-rate estimate."""
    mode: str  # "self-driving" or "taxi"
    origin: str
    destination: str
    cost: float | None  # per car; None for taxis and outside the US
    checked_at: str

    def vehicles_needed(self, people: int) -> int:
        return math.ceil(people / (SELF_DRIVING_SEATS if self.mode == "self-driving" else TAXI_SEATS))


@dataclass(frozen=True)
class LiveRestaurant:
    name: str
    city: str
    average_cost: float | None  # estimated per person
    cuisines: tuple[str, ...]
    checked_at: str


@dataclass(frozen=True)
class LiveStay:
    name: str
    city: str
    price: float | None  # per night for the whole booking
    kind: str  # e.g. "Apartment in Trevi", "Room in Monti", "hotel"
    guests: int
    checked_at: str
    house_rules: None = None  # live sources don't publish house rules
    minimum_nights: int = 0  # live results already fit the booked dates

    def allows(self, rule: str) -> bool:
        return False

    def matches_room_type(self, room_type: str) -> bool:
        kind = self.kind.lower()
        shared = kind.startswith("shared")
        private = kind.startswith(("room in", "private room")) or kind == "hotel"
        if room_type == "not shared room":
            return not shared
        if room_type == "shared room":
            return shared
        if room_type == "private room":
            return private
        return not private and not shared  # entire room: a whole apartment, home or condo

    def rooms_needed(self, people: int) -> int:
        return 1  # one booking covers the searched guests


LIVE_PREFIXES = ("flight-", "transit-", "stay-", "restaurant-", "drive-")


_SOURCE_PREFIXES = ("restaurant: ", "attraction: ", "accommodation: ")


def _clean_name(name: str) -> str:
    """Drop a citation prefix such as 'restaurant: ' that models copy from search results."""
    text = " ".join(str(name).split())
    for prefix in _SOURCE_PREFIXES:
        if text.lower().startswith(prefix):
            return text[len(prefix):]
    return text


def _is_live_id(text: str | None) -> bool:
    return bool(text) and str(text).strip().lower().startswith(LIVE_PREFIXES)


def _live_by_name(name: str, kind: str):
    """A live item the search tools returned under this name, if any."""
    text = " ".join(str(name).split())
    candidates = [text, text.rsplit(", ", 1)[0]] if ", " in text else [text]
    for candidate in candidates:
        item_id = items.lookup_by_name(kind, candidate)
        if item_id:
            return _live_item(item_id, kind)
    return None


def _live_item(item_id: str, kind: str, mode: str = "self-driving"):
    """A live item by id as one of the Live* objects, or None if it is unknown or expired."""
    if not str(item_id).strip().lower().startswith(f"{kind}-"):
        return None
    data = items.lookup(item_id)
    if not data:
        return None
    checked = data.get("checked_at", "")
    if kind == "flight":
        return LiveFlight(" ".join(data.get("flight_numbers") or []) or "flight", data.get("origin_city", ""),
                          data.get("destination_city", ""), data.get("price_per_person"), checked)
    if kind == "drive":
        cost = data.get("cost_per_car_usd") if mode == "self-driving" else None  # no taxi fare data
        return LiveDrive(mode, data.get("origin", ""), data.get("destination", ""), cost, checked)
    if kind == "transit":
        return LiveTransit(data.get("summary", "public transport"), data.get("origin", ""),
                           data.get("destination", ""), data.get("fare_per_person_usd"), checked)
    if kind == "restaurant":
        cuisines = (data["cuisine"],) if data.get("cuisine") else ()
        return LiveRestaurant(data.get("name", ""), data.get("city", ""), data.get("estimated_cost_per_person_usd"),
                              cuisines, checked)
    return LiveStay(data.get("name", ""), data.get("city", ""), data.get("price_per_night"), data.get("kind") or "",
                    int(data.get("guests") or 1), checked)


class DayPlan(BaseModel):
    day: int = Field(ge=1, le=30)
    city: str = Field(description="The city where the day's meals, attractions and stay are.")
    transportation: Transport | None = None
    breakfast: str | None = Field(default=None, description="Restaurant name, or a live restaurant id ('restaurant-...')")
    lunch: str | None = Field(default=None, description="Restaurant name, or a live restaurant id")
    dinner: str | None = Field(default=None, description="Restaurant name, or a live restaurant id")
    attractions: list[str] = Field(default_factory=list)
    accommodation: str | None = Field(
        default=None, description="Name of the place to stay that night, or a live stay id ('stay-...')")
    local_transport: list[Transport] = Field(
        default_factory=list, description="Local trips that day besides the main transport, such as the airport "
                                          "transfer: public transport by its 'transit-...' id, or a car or taxi by "
                                          "its 'drive-...' id, both from get_local_transport.")


class TripConstraints(BaseModel):
    house_rule: HouseRule | None = Field(default=None, description="Something the stay must allow")
    room_type: RoomType | None = None
    cuisines: list[str] = Field(default_factory=list, description="Cuisines that must appear among the meals")
    transportation: TransportRule | None = None


class TripPlan(BaseModel):
    people: int = Field(ge=1, le=20)
    budget: float | None = Field(default=None, description="Total budget for the whole group, in `currency`")
    currency: str = Field(default="USD", description="Currency for the budget and the totals, e.g. USD, EUR, INR")
    stay: str | None = Field(
        default=None, description="The place to stay for the whole trip (a live stay id or name). Used every night "
                                  "except the last day, unless a day sets its own accommodation.")
    days: list[DayPlan] = Field(min_length=1, max_length=30)
    constraints: TripConstraints = Field(default_factory=TripConstraints)


def _as_plan(plan: TripPlan | dict) -> TripPlan:
    return plan if isinstance(plan, TripPlan) else TripPlan.model_validate(plan)


def _day_cities(day: DayPlan) -> list[str]:
    catalog = load_catalog()
    names = [day.city]
    if day.transportation:
        names += [day.transportation.origin or "", day.transportation.destination or ""]
        flight = catalog.flights_by_number.get((day.transportation.flight_number or "").upper())
        if flight:
            names += [flight.origin, flight.destination]
    return list(dict.fromkeys(c for c in (catalog.city_name(n) for n in names if n) if c))


def _resolve_transport(transport: Transport, day: int, catalog, unknown: list[str]):
    """One transport leg as a catalog or live object, or None (and a note in unknown) if it can't be found."""
    if transport.item_id:
        kind = {"transit": "transit", "self-driving": "drive", "taxi": "drive"}.get(transport.mode, "flight")
        found = _live_item(transport.item_id, kind, transport.mode)
        if not found:
            unknown.append(f"day {day}: {kind} id '{transport.item_id}' (unknown or expired; search again)")
        return found
    if transport.mode == "transit":
        unknown.append(f"day {day}: public transport needs an id from get_local_transport")
        return None
    origin, destination = catalog.city_name(transport.origin or ""), catalog.city_name(transport.destination or "")
    if transport.mode == "flight" and not transport.flight_number:
        estimate = catalog.estimate_flight(origin, destination) if origin and destination else None
        if not estimate:
            unknown.append(f"day {day}: flight from '{transport.origin}' to '{transport.destination}'")
            return None
        return EstimatedFlight(origin, destination, estimate["distance_km"])
    if transport.mode == "flight":
        flight = (catalog.flights_by_number.get((transport.flight_number or "").upper())
                  or _live_by_name(transport.flight_number or "", "flight"))
        if not flight:
            unknown.append(f"day {day}: flight '{transport.flight_number}'")
        return flight
    route = catalog.ground.get((transport.mode, (origin or "").lower(), (destination or "").lower()))
    if not route:
        unknown.append(f"day {day}: {transport.mode} from '{transport.origin}' to '{transport.destination}'")
    return route


def _resolve(plan: TripPlan) -> dict:
    """Look up every item in the plan. Returns the matched catalog objects per day
    and a list of items that couldn't be found."""
    catalog = load_catalog()
    days, unknown = [], []
    last_day = max(day.day for day in plan.days)
    for day in plan.days:
        if plan.stay and not day.accommodation and day.day != last_day:
            day = day.model_copy(update={"accommodation": plan.stay})
        day = day.model_copy(update={
            "breakfast": day.breakfast and _clean_name(day.breakfast), "lunch": day.lunch and _clean_name(day.lunch),
            "dinner": day.dinner and _clean_name(day.dinner),
            "accommodation": day.accommodation and _clean_name(day.accommodation),
            "attractions": [_clean_name(a) for a in day.attractions]})
        cities = _day_cities(day)
        resolved = {"day": day.day, "cities": cities, "transport": None, "meals": [], "attractions": [],
                    "accommodation": None}
        names = [day.breakfast, day.lunch, day.dinner, day.accommodation, *day.attractions]
        if not cities and any(n and not _is_live_id(n) for n in names):
            unknown.append(f"day {day.day}: city '{day.city}' (not in the snapshot data; use live ids)")
        if day.transportation:
            resolved["transport"] = _resolve_transport(day.transportation, day.day, catalog, unknown)
        resolved["local"] = [found for leg in day.local_transport
                             if (found := _resolve_transport(leg, day.day, catalog, unknown)) is not None]
        for meal in ("breakfast", "lunch", "dinner"):
            name = getattr(day, meal)
            if name:
                live = _is_live_id(name)
                restaurant = (_live_item(name, "restaurant") if live else
                              _live_by_name(name, "restaurant") or catalog.find_place("restaurant", name, cities))
                resolved["meals"].append((meal, restaurant))
                if not restaurant:
                    where = "unknown or expired id; search again" if live else f"not found in {', '.join(cities) or day.city}"
                    unknown.append(f"day {day.day}: {meal} '{name}' ({where})")
        for name in day.attractions:
            attraction = catalog.find_place("attraction", name, cities)
            resolved["attractions"].append(attraction)
            if not attraction:
                unknown.append(f"day {day.day}: attraction '{name}' (not found in {', '.join(cities) or day.city})")
        if day.accommodation:
            live = _is_live_id(day.accommodation)
            stay = (_live_item(day.accommodation, "stay") if live
                    else _live_by_name(day.accommodation, "stay")
                    or catalog.find_place("accommodation", day.accommodation, cities))
            resolved["accommodation"] = stay
            if not stay:
                where = "unknown or expired id; search again" if live else f"not found in {', '.join(cities) or day.city}"
                unknown.append(f"day {day.day}: accommodation '{day.accommodation}' ({where})")
        days.append(resolved)
    return {"days": days, "unknown_items": unknown}


def compute_cost(plan: TripPlan | dict, resolved: dict | None = None) -> dict:
    plan = _as_plan(plan)
    people = validate_people(plan.people)
    budget = validate_budget(plan.budget) if plan.budget is not None else None
    resolved = resolved or _resolve(plan)

    lines, unpriced = [], []
    totals_usd = {"transportation": 0.0, "accommodation": 0.0, "meals": 0.0, "attractions": 0.0}

    def add(day: int, group: str, description: str, unit_cost: float | None, quantity: int, source: str,
            estimate: str | None = None) -> None:
        if unit_cost is None:
            unpriced.append(f"day {day}: {description}")
            return
        cost = round(unit_cost * quantity, 2)
        line = {"day": day, "type": group, "item": description, "unit_cost_usd": unit_cost, "quantity": quantity,
                "cost_usd": cost, "source": source}
        if estimate:
            line["estimate"] = estimate
        lines.append(line)
        totals_usd[group] += cost

    def label(item) -> str:
        checked = getattr(item, "checked_at", None)
        return f"live (checked {checked})" if checked is not None else "snapshot"

    def add_transport(n: int, transport) -> None:
        if transport is None:
            return
        if isinstance(transport, EstimatedFlight):
            add(n, "transportation",
                f"Flight {transport.origin} → {transport.destination} (~{transport.distance_km:,} km, no price data)",
                None, people, "estimate")
        elif isinstance(transport, LiveTransit):
            add(n, "transportation", f"Public transport {transport.summary}, {transport.origin} → {transport.destination}"
                + ("" if transport.fare is not None else " (fare not published)"), transport.fare, people, label(transport))
        elif hasattr(transport, "number"):
            add(n, "transportation", f"Flight {transport.number}, {transport.origin} → {transport.destination}",
                transport.price, people, label(transport))
        else:
            note = ""
            if isinstance(transport, LiveDrive):
                note = " (IRS-rate estimate)" if transport.cost is not None else " (no fare data)"
            add(n, "transportation", f"{transport.mode.title()}, {transport.origin} → {transport.destination}{note}",
                transport.cost, transport.vehicles_needed(people), label(transport),
                estimate="IRS 2026 mileage rate, fuel and running costs" if note == " (IRS-rate estimate)" else None)

    for day in resolved["days"]:
        n = day["day"]
        for transport in [day["transport"], *day["local"]]:
            add_transport(n, transport)
        for meal, restaurant in day["meals"]:
            if restaurant:
                add(n, "meals", f"{meal.title()}: {restaurant.name}, {restaurant.city}"
                    + ("" if restaurant.average_cost is not None else " (price not listed)"),
                    restaurant.average_cost, people, label(restaurant),
                    estimate="middle of Google's price range per person" if isinstance(restaurant, LiveRestaurant) else None)
        stay = day["accommodation"]
        if stay:
            add(n, "accommodation", f"{stay.name}, {stay.city} (1 night)", stay.price, stay.rooms_needed(people),
                label(stay))

    currency, rates, notes = (plan.currency or "USD").strip().upper(), None, []
    if currency != "USD":
        try:
            rates = fx.get_rates()
            rates.code(currency)
            notes.append(rates.note())
        except LiveDataError:
            notes.append(f"Exchange rates are unavailable, so totals are in USD instead of {currency}.")
            currency = "USD"

    def to_currency(amount_usd: float) -> float:
        return rates.convert(amount_usd, "USD", currency) if rates else round(amount_usd, 2)

    def money(amount: float | None) -> str | None:
        return None if amount is None else f"{currency} {amount:,.2f}"

    for line in lines:
        line["cost"] = to_currency(line["cost_usd"])
        line["cost_text"] = money(line["cost"])
    total_usd = round(sum(totals_usd.values()), 2)
    total = to_currency(total_usd)
    catalog = load_catalog()
    cities = list(dict.fromkeys(c for day in resolved["days"] for c in day["cities"]))
    notes = [*dict.fromkeys(catalog.data_note(c) for c in cities), *notes]
    if any(line["source"].startswith("live") for line in lines):
        notes.append("Live prices can change before booking.")
    return {
        "people": people,
        "currency": currency,
        "items": lines,
        "totals": {key: to_currency(value) for key, value in totals_usd.items()},
        "total_cost": total,
        "total_cost_usd": total_usd,
        "budget": budget,
        "within_budget": None if budget is None else total <= budget,
        "remaining_budget": None if budget is None else round(budget - total, 2),
        "totals_text": {key: money(to_currency(value)) for key, value in totals_usd.items()},
        "total_text": money(total),
        "budget_text": money(budget),
        "remaining_text": None if budget is None else money(round(budget - total, 2)),
        "unpriced_items": unpriced,
        "budget_check_complete": not unpriced,
        "unknown_items": resolved["unknown_items"],
        "note": " ".join([*notes, f"Totals in {currency}. Attractions have no prices in the data. Unpriced and "
                                  "unknown items are not included in the total."]),
    }


def _check(name: str, passed: bool, detail: str) -> dict:
    return {"check": name, "passed": passed, "detail": detail}


def check_plan(plan: TripPlan | dict) -> dict:
    plan = _as_plan(plan)
    resolved = _resolve(plan)
    cost = compute_cost(plan, resolved)
    days = resolved["days"]
    stays = [d["accommodation"] for d in days if d["accommodation"]]
    meals = [r for d in days for _, r in d["meals"] if r]
    transports = [d["transport"] for d in days if d["transport"] is not None]
    modes = {"flight" if isinstance(t, EstimatedFlight) or hasattr(t, "number") else t.mode for t in transports}
    rules = plan.constraints

    hard = []
    if plan.budget is not None:
        detail = (f"Priced total {cost['currency']} {cost['total_cost']:,.2f} against a budget of "
                  f"{cost['currency']} {cost['budget']:,.2f}.")
        if cost["unpriced_items"]:
            detail += f" Not included (no price data): {len(cost['unpriced_items'])} item(s), so the real total is higher."
        hard.append(_check("budget", cost["within_budget"], detail))
    if rules.house_rule:
        bad = sorted({s.name for s in stays if s.house_rules is not None and not s.allows(rules.house_rule)})
        unknown_rules = sorted({s.name for s in stays if s.house_rules is None})
        detail = f"Must allow {rules.house_rule}."
        if bad:
            detail += f" Not allowed at: {', '.join(bad)}."
        if unknown_rules:
            detail += f" House rules not published for: {', '.join(unknown_rules)}."
        hard.append(_check("house rule", not bad and not unknown_rules, detail))
    if rules.room_type:
        bad = sorted({s.name for s in stays if not s.matches_room_type(rules.room_type)})
        hard.append(_check("room type", not bad, f"Must be {rules.room_type}."
                           + (f" Wrong type: {', '.join(bad)}." if bad else "")))
    if rules.cuisines:
        served = {c.lower() for r in meals for c in r.cuisines}
        missing = [c for c in rules.cuisines if c.lower() not in served]
        hard.append(_check("cuisine", not missing, f"Must include {', '.join(rules.cuisines)}."
                           + (f" Missing: {', '.join(missing)}." if missing else "")))
    if rules.transportation:
        banned = "flight" if rules.transportation == "no flight" else "self-driving"
        hard.append(_check("transportation", banned not in modes, f"Must not use {banned}."))

    meal_counts = Counter((r.name, r.city) for r in meals)
    repeated_meals = sorted(f"{name}, {city}" for (name, city), n in meal_counts.items() if n > 1)
    attraction_counts = Counter((a.name, a.city) for d in days for a in d["attractions"] if a)
    repeated_attractions = sorted(f"{name}, {city}" for (name, city), n in attraction_counts.items() if n > 1)
    nights = Counter((s.name, s.city) for s in stays)
    short_stays = sorted(f"{s.name} needs {s.minimum_nights} nights, plan has {nights[(s.name, s.city)]}"
                         for s in set(stays) if nights[(s.name, s.city)] < s.minimum_nights)
    missing_nights = [d["day"] for d in days[:-1] if not d["accommodation"]]
    too_small = sorted({f"{s.name} was searched for {s.guests}" for s in stays
                        if isinstance(s, LiveStay) and s.guests < plan.people})

    commonsense = [
        _check("all items found in the data", not resolved["unknown_items"],
               "; ".join(resolved["unknown_items"]) or "Every flight, route and place was found."),
        _check("no repeated restaurants", not repeated_meals, ", ".join(repeated_meals) or "Each restaurant is used once."),
        _check("no repeated attractions", not repeated_attractions,
               ", ".join(repeated_attractions) or "Each attraction is visited once."),
        _check("minimum nights", not short_stays, "; ".join(short_stays) or "Every stay meets its minimum nights."),
        _check("a place to stay every night", not missing_nights,
               f"No accommodation on day(s) {missing_nights}." if missing_nights else "Every night is covered."),
        _check("stays fit the group", not too_small,
               f"{'; '.join(too_small)} guest(s), but the plan has {plan.people}; search again for the group."
               if too_small else "Every stay fits the number of people."),
        _check("non-conflicting transportation", not {"flight", "self-driving"} <= modes,
               "Uses both flights and self-driving." if {"flight", "self-driving"} <= modes
               else "Transport modes are consistent."),
    ]
    return {
        "passed": all(c["passed"] for c in hard + commonsense),
        "hard_constraints": hard,
        "commonsense_checks": commonsense,
        "cost": {k: cost[k] for k in ("currency", "totals", "total_cost", "budget", "remaining_budget",
                                      "budget_check_complete")},
    }


def _error(error: Exception) -> str:
    return json.dumps({"error": str(error)})


@tool
def calculate_trip_cost(plan: TripPlan) -> str:
    """Add up the cost of a day-by-day plan. Use the ids of live results
    (flight-, stay-, restaurant-, transit-) from the search tools, or exact
    snapshot names and flight numbers. Flights, meals and transit fares are per
    person; a live stay's nightly price covers the whole booking; snapshot cars
    seat 5 and taxis 4. currency sets the budget's and the totals' currency.
    Returns a line-by-line breakdown marked live or snapshot, the total, whether
    it fits the budget, and items with no price (they aren't in the total)."""
    try:
        return json.dumps(compute_cost(plan))
    except InputValidationError as error:
        return _error(error)


@tool
def check_constraints(plan: TripPlan) -> str:
    """Check a finished day-by-day plan before presenting it. Hard constraints:
    budget, house rule, room type, required cuisines and banned transport.
    Commonsense checks: every item and live id exists, no repeated restaurants or
    attractions, minimum nights met, a stay every night except the last, live
    stays fit the group, and no mixing of flights with self-driving."""
    try:
        return json.dumps(check_plan(plan))
    except InputValidationError as error:
        return _error(error)
