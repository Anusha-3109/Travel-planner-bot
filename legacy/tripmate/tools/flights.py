"""Flight route lookup and flight time estimates built on OpenFlights data.

OpenFlights (https://openflights.org/data) is an open dataset of airports,
airlines and routes. The route data is a historical snapshot, so results show
which airlines have served a route, not live schedules.
"""

import csv
import json
import math
from collections import defaultdict
from dataclasses import dataclass
from functools import lru_cache

from langchain_core.tools import tool

import config
from security.validation import InputValidationError, validate_city

EARTH_RADIUS_KM = 6371.0
ROUTE_DETOUR_FACTOR = 1.05  # real flight paths are a little longer than great-circle distance
TAXI_AND_CLIMB_HOURS = 0.5
MAX_ROUTES_SHOWN = 20
METRO_RADIUS_KM = 50
_MISSING = ("", r"\N")


@dataclass(frozen=True)
class Airport:
    iata: str
    name: str
    city: str
    country: str
    lat: float
    lon: float


@dataclass
class FlightCatalog:
    airports_by_city: dict[str, list[Airport]]
    airlines: dict[str, str]
    routes: dict[tuple[str, str], dict[str, int]]  # (from, to) -> {airline code: stops}
    route_counts: dict[str, int]  # airport IATA -> number of departing routes


def _read_rows(filename: str) -> list[list[str]]:
    with open(config.OPENFLIGHTS_DIR / filename, encoding="utf-8", newline="") as file:
        return list(csv.reader(file))


@lru_cache(maxsize=1)
def load_catalog() -> FlightCatalog:
    airports_by_city: dict[str, list[Airport]] = defaultdict(list)
    for row in _read_rows("airports.dat"):
        if len(row) < 8 or row[4] in _MISSING:
            continue
        airport = Airport(row[4], row[1], row[2], row[3], float(row[6]), float(row[7]))
        airports_by_city[airport.city.lower()].append(airport)

    # Some IATA codes are shared by several "active" airlines (JL is both Japan
    # Airlines and Japan Airlines Domestic); the first entry is the main carrier.
    airlines: dict[str, str] = {}
    for row in _read_rows("airlines.dat"):
        if len(row) >= 8 and row[3] not in _MISSING and row[7] == "Y":
            airlines.setdefault(row[3], row[1])

    routes: dict[tuple[str, str], dict[str, int]] = defaultdict(dict)
    for row in _read_rows("routes.dat"):
        # Skip codeshares so each route is listed under the airline that operates it.
        if len(row) < 8 or row[0] in _MISSING or row[6] == "Y":
            continue
        stops = int(row[7]) if row[7].isdigit() else 0
        existing = routes[(row[2], row[4])].get(row[0])
        routes[(row[2], row[4])][row[0]] = stops if existing is None else min(existing, stops)

    route_counts: dict[str, int] = defaultdict(int)
    for (origin, _), carriers in routes.items():
        route_counts[origin] += len(carriers)

    return FlightCatalog(dict(airports_by_city), airlines, dict(routes), dict(route_counts))


def find_airports(city: str, country: str | None = None) -> list[Airport]:
    """Airports for a city, busiest first. City names can be ambiguous (London,
    UK and London, Canada), so without a country we pick the country whose
    airports have the most routes."""
    catalog = load_catalog()
    airports = catalog.airports_by_city.get(validate_city(city).lower(), [])
    if country:
        country = validate_city(country).lower()
        airports = [a for a in airports if a.country.lower() == country]
    elif airports:
        traffic: dict[str, int] = defaultdict(int)
        for airport in airports:
            traffic[airport.country] += catalog.route_counts.get(airport.iata, 0)
        busiest_country = max(traffic, key=traffic.get)
        airports = [a for a in airports if a.country == busiest_country]
    airports += _nearby_airports(airports)
    # Hide heliports and airfields without scheduled routes, unless that is all there is.
    served = [a for a in airports if catalog.route_counts.get(a.iata, 0) > 0]
    return sorted(served or airports, key=lambda a: catalog.route_counts.get(a.iata, 0), reverse=True)


def _nearby_airports(airports: list[Airport]) -> list[Airport]:
    """Airports with scheduled routes that serve the same metro area but are
    filed under another city name, such as Newark (EWR) for New York."""
    if not airports:
        return []
    catalog = load_catalog()
    known = {a.iata for a in airports}
    countries = {a.country for a in airports}
    return [
        candidate
        for city_airports in catalog.airports_by_city.values()
        for candidate in city_airports
        if candidate.iata not in known
        and candidate.country in countries
        and catalog.route_counts.get(candidate.iata, 0) > 0
        and any(great_circle_km(candidate, a) <= METRO_RADIUS_KM for a in airports)
    ]


def great_circle_km(a: Airport, b: Airport) -> float:
    lat1, lon1, lat2, lon2 = map(math.radians, (a.lat, a.lon, b.lat, b.lon))
    h = math.sin((lat2 - lat1) / 2) ** 2 + math.cos(lat1) * math.cos(lat2) * math.sin((lon2 - lon1) / 2) ** 2
    return 2 * EARTH_RADIUS_KM * math.asin(math.sqrt(h))


def estimate_block_hours(distance_km: float) -> float:
    """Gate-to-gate time: average speed is lower on short flights because climb
    and descent take up a larger share of the trip."""
    average_speed_kmh = 650 if distance_km < 1500 else 820
    return distance_km * ROUTE_DETOUR_FACTOR / average_speed_kmh + TAXI_AND_CLIMB_HOURS


def _format_hours(hours: float) -> str:
    total_minutes = round(hours * 60 / 5) * 5
    return f"{total_minutes // 60}h {total_minutes % 60:02d}m"


def _airport_summary(airports: list[Airport]) -> list[str]:
    return [f"{a.iata} - {a.name}, {a.city} ({a.country})" for a in airports]


def _resolve_cities(origin_city: str, destination_city: str, origin_country: str | None = None,
                    destination_country: str | None = None) -> tuple[list[Airport], list[Airport]]:
    origins = find_airports(origin_city, origin_country)
    destinations = find_airports(destination_city, destination_country)
    missing = [city for city, found in ((origin_city, origins), (destination_city, destinations)) if not found]
    if missing:
        raise InputValidationError(
            f"No airports found for: {', '.join(missing)}. Try the main city name in English, e.g. 'London' or 'New York'."
        )
    return origins, destinations


def find_routes(origin_city: str, destination_city: str, origin_country: str | None = None,
                destination_country: str | None = None) -> dict:
    origins, destinations = _resolve_cities(origin_city, destination_city, origin_country, destination_country)
    catalog = load_catalog()
    routes = []
    for origin in origins:
        for destination in destinations:
            for code, stops in catalog.routes.get((origin.iata, destination.iata), {}).items():
                routes.append({
                    "airline": catalog.airlines.get(code, code),
                    "airline_code": code,
                    "from": origin.iata,
                    "to": destination.iata,
                    "nonstop": stops == 0,
                    "distance_km": round(great_circle_km(origin, destination)),
                })
    routes.sort(key=lambda r: (not r["nonstop"], r["airline"], r["from"], r["to"]))
    return {
        "origin_airports": _airport_summary(origins),
        "destination_airports": _airport_summary(destinations),
        "route_count": len(routes),
        "airline_count": len({r["airline_code"] for r in routes}),
        "routes": routes[:MAX_ROUTES_SHOWN],
        "note": (
            "Based on the OpenFlights route snapshot, which is historical. Confirm current schedules with the airlines."
            if routes else
            "No direct routes in the OpenFlights data. A connecting flight through a hub is probably needed."
        ),
    }


def estimate_duration(origin_city: str, destination_city: str, origin_country: str | None = None,
                      destination_country: str | None = None) -> dict:
    origins, destinations = _resolve_cities(origin_city, destination_city, origin_country, destination_country)
    catalog = load_catalog()
    pairs = [(o, d) for o in origins for d in destinations]
    served = [(o, d) for o, d in pairs if catalog.routes.get((o.iata, d.iata))]
    # Prefer airport pairs that actually have a route; otherwise use the closest pair.
    origin, destination = min(served or pairs, key=lambda pair: great_circle_km(*pair))
    distance = great_circle_km(origin, destination)
    hours = estimate_block_hours(distance)
    return {
        "from_airport": f"{origin.iata} - {origin.name}",
        "to_airport": f"{destination.iata} - {destination.name}",
        "great_circle_distance_km": round(distance),
        "estimated_nonstop_duration": _format_hours(hours),
        "estimated_hours": round(hours, 2),
        "has_direct_route_in_data": bool(served),
        "note": "Estimate from distance and typical airliner speeds. Real schedules vary with wind, routing and aircraft.",
    }


@tool
def search_flight_routes(origin_city: str, destination_city: str, origin_country: str | None = None,
                         destination_country: str | None = None) -> str:
    """Find airlines that fly directly between two cities, with airport codes and
    distances. Use for questions about which airlines or airports serve a route.
    Countries are optional; pass them only when a city name is ambiguous."""
    try:
        return json.dumps(find_routes(origin_city, destination_city, origin_country, destination_country))
    except InputValidationError as error:
        return json.dumps({"error": str(error)})


@tool
def estimate_flight_duration(origin_city: str, destination_city: str, origin_country: str | None = None,
                             destination_country: str | None = None) -> str:
    """Estimate the nonstop flight time and distance between two cities. Use for
    questions about how long a flight takes. Countries are optional; pass them
    only when a city name is ambiguous."""
    try:
        return json.dumps(estimate_duration(origin_city, destination_city, origin_country, destination_country))
    except InputValidationError as error:
        return json.dumps({"error": str(error)})
