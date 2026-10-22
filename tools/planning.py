"""Trip cost and constraint checks for a day-by-day plan.

The plan follows TravelPlanner's format: each day has a city, optional
transportation, three meals, attractions and a place to stay. Every item is
looked up in the catalog by name, so costs come from the data, never from the
model. Costs follow TravelPlanner's rules: flights and meals are per person,
cars seat 5, taxis seat 4, and a group larger than a stay's occupancy books
several rooms. Attractions have no prices in the data, so they cost 0.

Outside the US data some prices don't exist (flights to and from European and
Asian cities, and their restaurants). Those items are listed as unpriced
rather than guessed, and the budget check says it is incomplete.
"""

import json
from collections import Counter
from dataclasses import dataclass
from typing import Literal

from langchain_core.tools import tool
from pydantic import BaseModel, Field

from security.validation import InputValidationError, validate_budget, validate_people
from travel_data.catalog import load_catalog

HouseRule = Literal["smoking", "parties", "children under 10", "visitors", "pets"]
RoomType = Literal["entire room", "private room", "shared room", "not shared room"]
TransportRule = Literal["no flight", "no self-driving"]


class Transport(BaseModel):
    mode: Literal["flight", "self-driving", "taxi"]
    flight_number: str | None = Field(
        default=None, description="For US flights from search_flights, e.g. 'F3792603'. Leave empty for an "
                                  "estimated flight (routes involving European or Asian cities).")
    origin: str | None = Field(default=None, description="Required for self-driving, taxi and estimated flights.")
    destination: str | None = Field(default=None, description="Required for self-driving, taxi and estimated flights.")


@dataclass(frozen=True)
class EstimatedFlight:
    origin: str
    destination: str
    distance_km: int


class DayPlan(BaseModel):
    day: int = Field(ge=1, le=30)
    city: str = Field(description="The city where the day's meals, attractions and stay are.")
    transportation: Transport | None = None
    breakfast: str | None = Field(default=None, description="Restaurant name")
    lunch: str | None = Field(default=None, description="Restaurant name")
    dinner: str | None = Field(default=None, description="Restaurant name")
    attractions: list[str] = Field(default_factory=list)
    accommodation: str | None = Field(default=None, description="Name of the place to stay that night")


class TripConstraints(BaseModel):
    house_rule: HouseRule | None = Field(default=None, description="Something the stay must allow")
    room_type: RoomType | None = None
    cuisines: list[str] = Field(default_factory=list, description="Cuisines that must appear among the meals")
    transportation: TransportRule | None = None


class TripPlan(BaseModel):
    people: int = Field(ge=1, le=20)
    budget: float | None = Field(default=None, description="Total budget in USD for the whole group")
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


def _resolve(plan: TripPlan) -> dict:
    """Look up every item in the plan. Returns the matched catalog objects per day
    and a list of items that couldn't be found."""
    catalog = load_catalog()
    days, unknown = [], []
    for day in plan.days:
        cities = _day_cities(day)
        resolved = {"day": day.day, "cities": cities, "transport": None, "meals": [], "attractions": [],
                    "accommodation": None}
        if not cities:
            unknown.append(f"day {day.day}: city '{day.city}'")
        transport = day.transportation
        if transport and transport.mode == "flight" and not transport.flight_number:
            origin, destination = catalog.city_name(transport.origin or ""), catalog.city_name(transport.destination or "")
            estimate = catalog.estimate_flight(origin, destination) if origin and destination else None
            resolved["transport"] = EstimatedFlight(origin, destination, estimate["distance_km"]) if estimate else None
            if not estimate:
                unknown.append(f"day {day.day}: flight from '{transport.origin}' to '{transport.destination}'")
        elif transport and transport.mode == "flight":
            flight = catalog.flights_by_number.get((transport.flight_number or "").upper())
            resolved["transport"] = flight
            if not flight:
                unknown.append(f"day {day.day}: flight '{transport.flight_number}'")
        elif transport:
            origin, destination = catalog.city_name(transport.origin or ""), catalog.city_name(transport.destination or "")
            route = catalog.ground.get((transport.mode, (origin or "").lower(), (destination or "").lower()))
            resolved["transport"] = route
            if not route:
                unknown.append(f"day {day.day}: {transport.mode} from '{transport.origin}' to '{transport.destination}'")
        for meal in ("breakfast", "lunch", "dinner"):
            name = getattr(day, meal)
            if name:
                restaurant = catalog.find_place("restaurant", name, cities)
                resolved["meals"].append((meal, restaurant))
                if not restaurant:
                    unknown.append(f"day {day.day}: {meal} '{name}' (not found in {', '.join(cities) or day.city})")
        for name in day.attractions:
            attraction = catalog.find_place("attraction", name, cities)
            resolved["attractions"].append(attraction)
            if not attraction:
                unknown.append(f"day {day.day}: attraction '{name}' (not found in {', '.join(cities) or day.city})")
        if day.accommodation:
            stay = catalog.find_place("accommodation", day.accommodation, cities)
            resolved["accommodation"] = stay
            if not stay:
                unknown.append(f"day {day.day}: accommodation '{day.accommodation}' "
                               f"(not found in {', '.join(cities) or day.city})")
        days.append(resolved)
    return {"days": days, "unknown_items": unknown}


def compute_cost(plan: TripPlan | dict, resolved: dict | None = None) -> dict:
    plan = _as_plan(plan)
    people = validate_people(plan.people)
    budget = validate_budget(plan.budget) if plan.budget is not None else None
    resolved = resolved or _resolve(plan)

    items, unpriced = [], []
    totals = {"transportation": 0.0, "accommodation": 0.0, "meals": 0.0, "attractions": 0.0}

    def add(day: int, group: str, description: str, unit_cost: float | None, quantity: int) -> None:
        if unit_cost is None:
            unpriced.append(f"day {day}: {description}")
            return
        cost = round(unit_cost * quantity, 2)
        items.append({"day": day, "type": group, "item": description, "unit_cost": unit_cost,
                      "quantity": quantity, "cost": cost})
        totals[group] += cost

    for day in resolved["days"]:
        transport = day["transport"]
        if isinstance(transport, EstimatedFlight):
            add(day["day"], "transportation",
                f"Flight {transport.origin} → {transport.destination} (~{transport.distance_km:,} km, no price data)",
                None, people)
        elif transport is not None and hasattr(transport, "number"):
            add(day["day"], "transportation", f"Flight {transport.number}, {transport.origin} → {transport.destination}",
                transport.price, people)
        elif transport is not None:
            add(day["day"], "transportation", f"{transport.mode.title()}, {transport.origin} → {transport.destination}",
                transport.cost, transport.vehicles_needed(people))
        for meal, restaurant in day["meals"]:
            if restaurant:
                add(day["day"], "meals", f"{meal.title()}: {restaurant.name}, {restaurant.city}",
                    restaurant.average_cost, people)
        stay = day["accommodation"]
        if stay:
            add(day["day"], "accommodation", f"{stay.name}, {stay.city} (1 night)", stay.price, stay.rooms_needed(people))

    total = round(sum(totals.values()), 2)
    catalog = load_catalog()
    cities = list(dict.fromkeys(c for day in resolved["days"] for c in day["cities"]))
    notes = list(dict.fromkeys(catalog.data_note(c) for c in cities))
    return {
        "people": people,
        "items": items,
        "totals": {key: round(value, 2) for key, value in totals.items()},
        "total_cost": total,
        "budget": budget,
        "within_budget": None if budget is None else total <= budget,
        "remaining_budget": None if budget is None else round(budget - total, 2),
        "unpriced_items": unpriced,
        "budget_check_complete": not unpriced,
        "unknown_items": resolved["unknown_items"],
        "note": " ".join([*notes, "All prices in USD. Attractions have no prices in the data. Unpriced and unknown "
                                  "items are not included in the total."]),
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
        detail = f"Priced total ${cost['total_cost']:,.2f} against a budget of ${cost['budget']:,.2f}."
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

    commonsense = [
        _check("all items found in the data", not resolved["unknown_items"],
               "; ".join(resolved["unknown_items"]) or "Every flight, route and place was found."),
        _check("no repeated restaurants", not repeated_meals, ", ".join(repeated_meals) or "Each restaurant is used once."),
        _check("no repeated attractions", not repeated_attractions,
               ", ".join(repeated_attractions) or "Each attraction is visited once."),
        _check("minimum nights", not short_stays, "; ".join(short_stays) or "Every stay meets its minimum nights."),
        _check("a place to stay every night", not missing_nights,
               f"No accommodation on day(s) {missing_nights}." if missing_nights else "Every night is covered."),
        _check("non-conflicting transportation", not {"flight", "self-driving"} <= modes,
               "Uses both flights and self-driving." if {"flight", "self-driving"} <= modes
               else "Transport modes are consistent."),
    ]
    return {
        "passed": all(c["passed"] for c in hard + commonsense),
        "hard_constraints": hard,
        "commonsense_checks": commonsense,
        "cost": {k: cost[k] for k in ("totals", "total_cost", "budget", "remaining_budget")},
    }


def _error(error: Exception) -> str:
    return json.dumps({"error": str(error)})


@tool
def calculate_trip_cost(plan: TripPlan) -> str:
    """Add up the cost of a day-by-day plan from the data: flights and meals per
    person, cars per 5 travellers, taxis per 4, rooms per night by occupancy. Use
    exact names and flight numbers from the search tools. Returns a line-by-line
    breakdown, the total, whether it fits the budget, and any items with no
    price in the data (estimated flights, restaurants outside the US)."""
    try:
        return json.dumps(compute_cost(plan))
    except InputValidationError as error:
        return _error(error)


@tool
def check_constraints(plan: TripPlan) -> str:
    """Check a finished day-by-day plan before presenting it. Hard constraints:
    budget, house rule, room type, required cuisines and banned transport.
    Commonsense checks: every item exists in the data and in that day's city, no
    repeated restaurants or attractions, minimum nights met, a stay every night
    except the last, and no mixing of flights with self-driving."""
    try:
        return json.dumps(check_plan(plan))
    except InputValidationError as error:
        return _error(error)
