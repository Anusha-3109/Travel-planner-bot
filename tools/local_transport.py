"""Getting around: public transport, driving and taxis between two places.

Live from Google Routes when a Google Maps key is set: public transport routes
with lines, stops and times, plus driving time and distance (Google gives no
taxi fares). Without live data, two cities in the TravelPlanner data still get
their March 2022 self-driving and taxi options.
"""

import json
import re
import datetime as dt

from langchain_core.tools import tool

import config
from live.http import LiveDataError
from live.routes import search_local_transport
from security.validation import InputValidationError, validate_city, validate_date, validate_place
from travel_data.catalog import load_catalog


def _snapshot(origin: str, destination: str) -> list[dict]:
    catalog = load_catalog()
    a, b = catalog.city_name(origin), catalog.city_name(destination)
    if not a or not b:
        return []
    routes = [catalog.ground.get((mode, a.lower(), b.lower())) for mode in ("self-driving", "taxi")]
    return [{"mode": r.mode, "duration": r.duration, "distance_km": r.distance_km, "cost_per_vehicle": r.cost,
             "seats_per_vehicle": 5 if r.mode == "self-driving" else 4} for r in routes if r]


DEFAULT_TIME = dt.time(10, 0)  # when only a date is given


def _travel_time(day: str | None, clock: str | None) -> dt.datetime | None:
    """The local travel time from a YYYY-MM-DD date and an optional HH:MM time."""
    if not day:
        if clock:
            raise InputValidationError("A travel time needs a travel date too (YYYY-MM-DD).")
        return None
    when = dt.date.fromisoformat(validate_date(day))
    if not clock:
        return dt.datetime.combine(when, DEFAULT_TIME)
    match = re.match(r"^([01]?\d|2[0-3]):([0-5]\d)$", str(clock).strip())
    if not match:
        raise InputValidationError(f"'{clock}' isn't a valid time. Use the 24-hour HH:MM format, e.g. 14:30.")
    return dt.datetime.combine(when, dt.time(int(match.group(1)), int(match.group(2))))


def find_local_transport(origin: str, destination: str, city: str | None = None, date: str | None = None,
                         time: str | None = None) -> dict:
    origin, destination = validate_place(origin, "Origin"), validate_place(destination, "Destination")
    city = validate_city(city) if city else None
    depart_at = _travel_time(date, time)
    if not config.GOOGLE_MAPS_API_KEY:
        reason = "Live public transport is off (no Google Maps key)."
    else:
        try:
            live = search_local_transport(origin, destination, city, depart_at)
        except LiveDataError as error:
            reason = f"Live route search failed ({error})."
        else:
            live["transport_source"] = f"live ({live['provider']}, checked {live['checked_at']})"
            return live
    snapshot = _snapshot(origin, destination)
    if not snapshot:
        raise InputValidationError(f"{reason} No snapshot routes exist between these places either.")
    return {"transport_source": "snapshot (TravelPlanner, March 2022)", "from": origin, "to": destination,
            "public_transport": [], "ground_options": snapshot,
            "note": f"{reason} Showing March 2022 self-driving and taxi data; costs are per vehicle."}


@tool
def get_local_transport(origin: str, destination: str, city: str | None = None, date: str | None = None,
                        time: str | None = None) -> str:
    """How to get between two places, for example an airport and a hotel, or a
    hotel and a museum, in any city. Returns up to three public transport routes
    (fastest first) with step-by-step directions: lines, where to get on and
    off, stops, times, walking and the fare when published; plus driving time and
    distance for a taxi or car (no taxi fares). Give place names or addresses;
    city helps when a place name is ambiguous. Each route has an id for plans.
    date (YYYY-MM-DD) and time (24-hour HH:MM, local) search public transport for
    the travel day, up to 100 days ahead; for an airport transfer use the flight's
    arrival date and time. Without them, times come from today's timetable."""
    try:
        return json.dumps(find_local_transport(origin, destination, city, date, time))
    except InputValidationError as error:
        return json.dumps({"error": str(error)})
