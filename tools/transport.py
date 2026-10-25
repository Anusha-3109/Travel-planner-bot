"""Flight, self-driving and taxi lookup.

Flights are live first: for today or a later date, with a SerpApi key set,
search_flights asks Google Flights (via SerpApi) for current flights and
prices between any two cities with an airport. Otherwise, or if the live
search fails, it falls back to snapshot data:
- US routes in the TravelPlanner data: real March 2022 flights with prices.
- Any other pair of cities with known coordinates: an estimated nonstop flight
  time from the distance between the city centres, with no price.
Self-driving and taxi options come from the TravelPlanner snapshot (US only).
"""

import json

from langchain_core.tools import tool

import config
from live.flights import is_live_date, search_live_flights, too_far_ahead
from live.http import LiveDataError
from security.validation import InputValidationError, validate_date, validate_people
from travel_data.catalog import load_catalog


def _live_flights(origin_city: str, destination_city: str, day: str, passengers: int) -> tuple[dict | None, str]:
    """Live results, or None and the reason live data isn't used."""
    if not config.SERPAPI_API_KEY:
        return None, "Live flights are off (no SerpApi key), so snapshot data is shown."
    if not is_live_date(day):
        return None, "The date is in the past, so live flights aren't available and snapshot data is shown."
    if too_far_ahead(day):
        return None, ("The date is more than about 11 months ahead; airlines don't sell fares that far out yet, so "
                      "snapshot data is shown.")
    try:
        return search_live_flights(origin_city, destination_city, day, passengers), ""
    except (LiveDataError, InputValidationError) as error:
        return None, f"Live flight search failed ({error}), so snapshot data is shown."


def _snapshot(origin_city: str, destination_city: str, day: str, include_flights: bool) -> dict:
    catalog = load_catalog()
    origin = catalog.require_city(origin_city)
    destination = catalog.require_city(destination_city)
    result: dict = {"route": f"{origin} → {destination}"}
    ground = [catalog.ground.get((mode, origin.lower(), destination.lower())) for mode in ("self-driving", "taxi")]
    result["ground_options"] = [
        {"mode": g.mode, "duration": g.duration, "distance_km": g.distance_km, "cost_per_vehicle": g.cost,
         "seats_per_vehicle": 5 if g.mode == "self-driving" else 4, "source": "snapshot (TravelPlanner, March 2022)"}
        for g in ground if g
    ]
    notes = list(dict.fromkeys([catalog.data_note(origin), catalog.data_note(destination)]))
    if include_flights:
        flights = sorted(catalog.flights.get((origin.lower(), destination.lower(), day), []),
                         key=lambda f: (f.price, f.departure))
        result["flights_source"] = "snapshot (TravelPlanner, March 2022)"
        result["flight_count"] = len(flights)
        result["flights"] = [
            {"flight_number": f.number, "price_per_person": f.price, "departure": f.departure,
             "arrival": f.arrival, "duration": f.duration, "distance_miles": f.distance_miles}
            for f in flights[: config.MAX_RESULTS_SHOWN]
        ]
        if not flights:
            dates = catalog.flight_dates(origin, destination)
            if dates:
                result["other_dates_with_flights"] = dates
            estimate = catalog.estimate_flight(origin, destination)
            if estimate:
                result["estimated_flight"] = estimate
                notes.append("The estimated flight is a nonstop time from the distance between city centres. It has "
                             "no price and no schedule.")
    result["notes"] = notes
    return result


def find_transport(origin_city: str, destination_city: str, date: str, passengers: int = 1) -> dict:
    day = validate_date(date)
    passengers = validate_people(passengers)
    live, reason = _live_flights(origin_city, destination_city, day, passengers)
    try:
        snapshot = _snapshot(origin_city, destination_city, day, include_flights=live is None)
    except InputValidationError:
        if live is None:
            raise
        snapshot = {"route": f"{origin_city} → {destination_city}", "ground_options": [], "notes": []}

    result = {"route": snapshot["route"], "date": day, "passengers": passengers}
    if live:
        result.update({"flights_source": f"live ({live['provider']}, checked {live['checked_at']})",
                       "flight_count": live["flight_count"], "flights_shown": live["flights_shown"],
                       "airlines": live["airlines"],
                       "airports_searched": live["airports_searched"]})
        if live["price_insights"]:
            result["price_insights"] = live["price_insights"]
        notes = [live["note"]]
    else:
        result.update({key: snapshot[key] for key in ("flights_source", "flight_count", "flights",
                                                      "other_dates_with_flights", "estimated_flight") if key in snapshot})
        notes = [reason]
    result["ground_options"] = snapshot["ground_options"]
    notes += snapshot["notes"]
    notes.append("Self-driving and taxi costs are per vehicle (snapshot data, US only).")
    result["note"] = " ".join(n for n in notes if n)
    return result


@tool
def search_flights(origin_city: str, destination_city: str, date: str, passengers: int = 1) -> str:
    """Find one-way flights between two cities on a date (YYYY-MM-DD), cheapest first.
    For today or later: live flights from Google Flights, grouped by airline
    (cheapest airline first), with flight numbers, times, stops and current
    prices per person in USD, for cities worldwide; each flight has an id to
    use in plans. For past dates, or if live
    search is unavailable: TravelPlanner's March 2022 US flights, or an estimated
    flight time with no price. Also returns US self-driving and taxi options.
    Search each leg of a round trip separately."""
    try:
        return json.dumps(find_transport(origin_city, destination_city, date, passengers))
    except InputValidationError as error:
        return json.dumps({"error": str(error)})
