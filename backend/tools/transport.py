"""Flight, self-driving and taxi lookup between cities.

Flights are live: for today or a later date, with a SerpApi key set,
search_flights asks Google Flights (via SerpApi) for current flights and
prices between any two cities with an airport. Otherwise, or if the live
search fails, it gives an estimated nonstop flight time from the distance
between the city centres, with no price.

Self-driving and taxi options come from Google Routes (live driving time and
distance, with an IRS-rate cost per car in the US). Without live data they are
estimated from the distance between the city centres. Taxis have no fares.
"""

import json

from langchain_core.tools import tool

from backend import config
from backend.live.flights import is_live_date, search_live_flights, too_far_ahead
from backend.live.http import LiveDataError
from backend.live.routes import search_live_drive
from backend.security.validation import InputValidationError, validate_date, validate_people
from backend.travel_data.catalog import SELF_DRIVING_SEATS, TAXI_SEATS, load_catalog


def _live_flights(origin_city: str, destination_city: str, day: str, passengers: int) -> tuple[dict | None, str]:
    """Live results, or None and the reason live data isn't used."""
    if not config.SERPAPI_API_KEY:
        return None, "Live flights are off (no SerpApi key), so only an estimated flight time is shown."
    if not is_live_date(day):
        return None, "The date is in the past, so live flights aren't available; an estimated flight time is shown."
    if too_far_ahead(day):
        return None, ("The date is more than about 11 months ahead; airlines don't sell fares that far out yet, so "
                      "an estimated flight time is shown.")
    try:
        return search_live_flights(origin_city, destination_city, day, passengers), ""
    except (LiveDataError, InputValidationError) as error:
        return None, f"Live flight search failed ({error}); an estimated flight time is shown."


def _ground_options(origin: str, destination: str) -> tuple[list[dict], str]:
    """A car and a taxi between two cities: live from Google Routes, or estimated from the distance."""
    if config.GOOGLE_MAPS_API_KEY:
        try:
            drive = search_live_drive(origin, destination)
        except LiveDataError:
            drive = None
        if drive:
            source = f"live (Google Routes, checked {drive['checked_at']})"
            car = {"mode": "self-driving", "id": drive["id"], "duration": drive["duration"],
                   "distance_km": drive["distance_km"], "cost_per_vehicle": drive.get("estimated_cost_per_car_usd"),
                   "cost_text": drive["cost_text"], "seats_per_vehicle": SELF_DRIVING_SEATS, "source": source}
            taxi = {"mode": "taxi", "id": drive["id"], "duration": drive["duration"],
                    "distance_km": drive["distance_km"], "cost_per_vehicle": None, "cost_text": "No taxi fare data",
                    "seats_per_vehicle": TAXI_SEATS, "source": source}
            return [car, taxi], "Driving times are live from Google Routes; US car costs are IRS-rate estimates."
    catalog = load_catalog()
    options = []
    for mode in ("self-driving", "taxi"):
        route = catalog.estimate_drive(mode, origin, destination)
        if route:
            options.append({"mode": mode, "duration": route.duration, "distance_km": route.distance_km,
                            "cost_per_vehicle": route.cost,
                            "seats_per_vehicle": SELF_DRIVING_SEATS if mode == "self-driving" else TAXI_SEATS,
                            "source": "estimate from the distance between the city centres"})
    note = ("Driving options are estimated from the distance between the city centres (no live route data); US "
            "car costs use the IRS mileage rate and taxis have no fares." if options else "")
    return options, note


def find_transport(origin_city: str, destination_city: str, date: str, passengers: int = 1) -> dict:
    day = validate_date(date)
    passengers = validate_people(passengers)
    live, reason = _live_flights(origin_city, destination_city, day, passengers)
    catalog = load_catalog()
    origin = catalog.city_name(origin_city) or origin_city
    destination = catalog.city_name(destination_city) or destination_city
    if live is None:  # an estimate needs both cities' centres
        origin, destination = catalog.require_city(origin_city), catalog.require_city(destination_city)

    result = {"route": f"{origin} → {destination}", "date": day, "passengers": passengers}
    if live:
        result.update({"flights_source": f"live ({live['provider']}, checked {live['checked_at']})",
                       "flight_count": live["flight_count"], "flights_shown": live["flights_shown"],
                       "airlines": live["airlines"],
                       "airports_searched": live["airports_searched"]})
        if live["price_insights"]:
            result["price_insights"] = live["price_insights"]
        notes = [live["note"]]
    else:
        result.update({"flights_source": "estimate", "flight_count": 0})
        estimate = catalog.estimate_flight(origin, destination)
        if estimate:
            result["estimated_flight"] = estimate
        notes = [reason, "The estimated flight is a nonstop time from the distance between city centres. It has no "
                         "price and no schedule." if estimate else "The cities are too close for a flight."]
    result["ground_options"], ground_note = _ground_options(origin, destination)
    notes.append(ground_note)
    result["note"] = " ".join(n for n in notes if n)
    return result


@tool
def search_flights(origin_city: str, destination_city: str, date: str, passengers: int = 1) -> str:
    """Find one-way flights between two cities on a date (YYYY-MM-DD), cheapest first.
    For today or later: live flights from Google Flights, grouped by airline
    (cheapest airline first), with flight numbers, times, stops and current
    prices per person in USD, for cities worldwide; each flight has an id to
    use in plans. If live search is unavailable: an estimated flight time with
    no price. Also returns self-driving and taxi options (live driving time and
    distance, with a drive- id for plans). Search each leg of a round trip separately."""
    try:
        return json.dumps(find_transport(origin_city, destination_city, date, passengers))
    except InputValidationError as error:
        return json.dumps({"error": str(error)})
