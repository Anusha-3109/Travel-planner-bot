"""Find the airports that serve a city, for live flight searches.

Uses the OurAirports file (data/ourairports/airports.csv, public domain,
updated daily). Only airports with scheduled passenger service are used.

- Cities in the catalog with a known centre: the large airports within 60 km
  that are in the same country as the closest one (so Hong Kong doesn't pick
  up Shenzhen). If there is none, the closest medium airport.
- Other cities: airports whose municipality has that name; US catalog cities
  stay in the US (St. Petersburg, FL is not St. Petersburg, Russia).
- A 3-letter airport code such as "JFK" is accepted as is.
"""

import csv
import re
from collections import defaultdict
from dataclasses import dataclass
from functools import lru_cache

import config
from security.validation import InputValidationError, validate_city
from travel_data.catalog import great_circle_km, load_catalog

AIRPORTS_CSV = config.DATA_DIR / "ourairports" / "airports.csv"
MAX_AIRPORTS = 3
METRO_RADIUS_KM = 60
# Older or English names that differ from the airport data.
CITY_ALIASES = {"bangalore": "bengaluru", "bombay": "mumbai", "calcutta": "kolkata", "madras": "chennai",
                "peking": "beijing", "saigon": "ho chi minh city", "canton": "guangzhou"}


@dataclass(frozen=True)
class Airport:
    code: str
    name: str
    municipality: str
    country: str
    kind: str  # "large_airport" or "medium_airport"
    latitude: float
    longitude: float


@lru_cache(maxsize=1)
def _airports() -> tuple[list[Airport], dict[str, Airport]]:
    if not AIRPORTS_CSV.exists():
        raise InputValidationError("Airport data is missing. Download data/ourairports/airports.csv first.")
    airports = []
    with open(AIRPORTS_CSV, encoding="utf-8", newline="") as file:
        for row in csv.DictReader(file):
            if (row["scheduled_service"] == "yes" and len(row["iata_code"]) == 3
                    and row["type"] in ("large_airport", "medium_airport")):
                airports.append(Airport(row["iata_code"].upper(), row["name"], row["municipality"], row["iso_country"],
                                        row["type"], float(row["latitude_deg"]), float(row["longitude_deg"])))
    return airports, {a.code: a for a in airports}


def _normalise(text: str) -> str:
    return " ".join(re.sub(r"[^\w\s]", " ", text.lower().replace(".", "")).split())


def _rank(airports: list[Airport]) -> list[Airport]:
    large = [a for a in airports if a.kind == "large_airport"]
    return (large or airports)[:MAX_AIRPORTS]


def airports_for(city: str) -> list[Airport]:
    """The main airports for a city name or airport code, closest first."""
    all_airports, by_code = _airports()
    text = " ".join(str(city).split())
    if len(text) == 3 and text.upper() in by_code:
        return [by_code[text.upper()]]
    name = validate_city(text)

    catalog = load_catalog()
    info = catalog.city_info.get(name.lower())
    if info and info.latitude is not None:
        nearby = sorted(((great_circle_km(info.latitude, info.longitude, a.latitude, a.longitude), a)
                         for a in all_airports), key=lambda pair: pair[0])
        nearby = [(distance, a) for distance, a in nearby if distance <= METRO_RADIUS_KM]
        if nearby:
            closest_large = next((a for _, a in nearby if a.kind == "large_airport"), nearby[0][1])
            return _rank([a for _, a in nearby if a.country == closest_large.country])

    # The city as a word in the airport's town or name: "New Delhi" for Delhi,
    # "Sarasota/Bradenton", "Sydney (Mascot)", "St. Petersburg Clearwater International".
    word = f" {_normalise(CITY_ALIASES.get(name.lower(), name))} "
    matches = [a for a in all_airports
               if word in f" {_normalise(a.municipality)} " or word in f" {_normalise(a.name)} "]
    if info and info.country == "United States":
        matches = [a for a in matches if a.country == "US"]
    if matches:
        # Several countries can share a city name; pick the one with the most large airports.
        countries = defaultdict(int)
        for airport in matches:
            countries[airport.country] += airport.kind == "large_airport"
        country = max(countries, key=countries.get)
        return _rank(sorted((a for a in matches if a.country == country), key=lambda a: a.kind != "large_airport"))
    raise InputValidationError(f"No airport with scheduled flights found for '{city}'. "
                               "Try a nearby larger city or an airport code such as JFK.")
