"""In-memory catalog of the snapshot travel data: the 2026 city files in
data/world/ written by travel_data/fetch_world.py (US, European and Asian
cities).

Stays come from Inside Airbnb, or for smaller US cities from OpenStreetMap
(without prices); restaurants and attractions come from OpenStreetMap. Values
the sources don't publish (restaurant prices, ratings, house rules, guest
limits of OpenStreetMap stays) are None here. There are no snapshot flights or
driving routes: they are searched live, and estimated from the distance
between city centres when live data isn't available.
"""

import difflib
import json
import math
from collections import defaultdict
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

import config
from security.validation import InputValidationError, validate_city

# TravelPlanner's hard constraints, mapped to the values used in the data.
HOUSE_RULES = {
    "smoking": "No smoking",
    "parties": "No parties",
    "children under 10": "No children under 10",
    "visitors": "No visitors",
    "pets": "No pets",
}
ROOM_TYPES = {
    "entire room": "Entire home/apt",
    "private room": "Private room",
    "shared room": "Shared room",
    "not shared room": None,  # anything except a shared room
}
TRANSPORT_RULES = ("no flight", "no self-driving")
SELF_DRIVING_SEATS = 5  # TravelPlanner's rule: one car per 5 travellers
TAXI_SEATS = 4  # and one taxi per 4
ROOM_GUESTS_IF_UNKNOWN = 2  # OpenStreetMap stays have no guest limit: a room is assumed to sleep 2
# Inside Airbnb and the OpenStreetMap stays call some rooms "Hotel room": a private room in
# TravelPlanner's room types.
ROOM_TYPE_ALIASES = {"Hotel room": "Private room"}

EARTH_RADIUS_KM = 6371.0
ROUTE_DETOUR_FACTOR = 1.05  # real flight paths are a little longer than great-circle distance
TAXI_AND_CLIMB_HOURS = 0.5
MIN_FLIGHT_KM = 150
ROAD_DETOUR_FACTOR = 1.25  # roads are about a quarter longer than the straight line
AVERAGE_DRIVING_KMH = 80


@dataclass(frozen=True)
class CityInfo:
    name: str
    country: str
    region: str  # "North America", "Europe" or "Asia"
    latitude: float | None
    longitude: float | None
    data_note: str


@dataclass(frozen=True)
class Attraction:
    name: str
    city: str
    address: str
    phone: str
    website: str
    latitude: float | None = None
    longitude: float | None = None
    kind: str = ""


@dataclass(frozen=True)
class Restaurant:
    name: str
    city: str
    average_cost: float | None  # None: no price in the data
    cuisines: tuple[str, ...]
    rating: float | None


@dataclass(frozen=True)
class Accommodation:
    name: str
    city: str
    price: float | None  # None: OpenStreetMap stays have no prices
    room_type: str
    house_rules: tuple[str, ...] | None  # None: the source doesn't publish house rules
    minimum_nights: int
    maximum_occupancy: int | None  # None: the source doesn't publish a guest limit
    rating: float | None

    def allows(self, rule: str) -> bool:
        """Only a stay whose published rules don't forbid it counts as allowing it."""
        return self.house_rules is not None and HOUSE_RULES[rule] not in self.house_rules

    def matches_room_type(self, room_type: str) -> bool:
        if room_type == "not shared room":
            return self.room_type != ROOM_TYPES["shared room"]
        return self.room_type == ROOM_TYPES[room_type]

    def rooms_needed(self, people: int) -> int:
        return math.ceil(people / max(self.maximum_occupancy or ROOM_GUESTS_IF_UNKNOWN, 1))


@dataclass(frozen=True)
class GroundRoute:
    """A drive or taxi ride between two cities, estimated from the distance between their centres."""
    mode: str  # "self-driving" or "taxi"
    origin: str
    destination: str
    duration: str
    distance_km: float
    cost: float | None  # per vehicle; None: no fare data (taxis, and driving outside the US)

    def vehicles_needed(self, people: int) -> int:
        return math.ceil(people / (SELF_DRIVING_SEATS if self.mode == "self-driving" else TAXI_SEATS))


def great_circle_km(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    lat1, lon1, lat2, lon2 = map(math.radians, (lat1, lon1, lat2, lon2))
    h = math.sin((lat2 - lat1) / 2) ** 2 + math.cos(lat1) * math.cos(lat2) * math.sin((lon2 - lon1) / 2) ** 2
    return 2 * EARTH_RADIUS_KM * math.asin(math.sqrt(h))


def estimate_flight_hours(distance_km: float) -> float:
    """Gate-to-gate time: average speed is lower on short flights because climb
    and descent take up a larger share of the trip."""
    average_speed_kmh = 650 if distance_km < 1500 else 820
    return distance_km * ROUTE_DETOUR_FACTOR / average_speed_kmh + TAXI_AND_CLIMB_HOURS


def _hours_text(hours: float) -> str:
    minutes = round(hours * 60 / 5) * 5
    return f"{minutes // 60}h {minutes % 60:02d}m"


@dataclass
class TravelCatalog:
    # Places and city details are keyed by lower-case city name.
    attractions: dict[str, list[Attraction]]
    restaurants: dict[str, list[Restaurant]]
    accommodations: dict[str, list[Accommodation]]
    cities: dict[str, str]  # lower-case name -> display name
    city_info: dict[str, CityInfo]  # lower-case name -> details
    cuisines: tuple[str, ...]

    def city_name(self, city: str) -> str | None:
        return self.cities.get(" ".join(str(city).split()).lower())

    def require_city(self, city: str) -> str:
        """The display name of a known city, or an error that suggests close matches."""
        name = self.city_name(validate_city(city))
        if name:
            return name
        close = difflib.get_close_matches(str(city).title(), self.cities.values(), n=3, cutoff=0.75)
        hint = f" Did you mean {', '.join(close)}?" if close else ""
        raise InputValidationError(f"'{city}' isn't in the snapshot data.{hint} "
                                   "It covers 245 US, European and Asian cities; live searches work anywhere.")

    def data_note(self, city: str) -> str:
        info = self.city_info.get(city.lower())
        return info.data_note if info else "No snapshot data for this city; only live data."

    def place_cities(self) -> list[str]:
        keys = set(self.attractions) | set(self.restaurants) | set(self.accommodations)
        return sorted(self.cities[key] for key in keys)

    def cities_by_region(self) -> dict[str, list[str]]:
        regions: dict[str, list[str]] = defaultdict(list)
        for name in self.place_cities():
            regions[self.city_info[name.lower()].region].append(name)
        return dict(regions)

    def _distance_km(self, origin: str, destination: str) -> tuple[float, CityInfo, CityInfo] | None:
        a, b = self.city_info.get(origin.lower()), self.city_info.get(destination.lower())
        if not a or not b or None in (a.latitude, b.latitude):
            return None
        return great_circle_km(a.latitude, a.longitude, b.latitude, b.longitude), a, b

    def estimate_flight(self, origin: str, destination: str) -> dict | None:
        """Distance and nonstop flight time between two city centres, or None when a
        city has no coordinates or the cities are too close to fly between."""
        found = self._distance_km(origin, destination)
        if not found or found[0] < MIN_FLIGHT_KM:
            return None
        distance = found[0]
        return {"distance_km": round(distance), "estimated_nonstop_duration": _hours_text(estimate_flight_hours(distance)),
                "price": None}

    def estimate_drive(self, mode: str, origin: str, destination: str) -> GroundRoute | None:
        """A drive or taxi ride from the distance between two city centres. Driving in the
        US is costed at the IRS mileage rate; taxis and driving elsewhere have no cost."""
        found = self._distance_km(origin, destination)
        if not found:
            return None
        distance, a, b = found
        road_km = round(distance * ROAD_DETOUR_FACTOR, 1)
        us = a.country == b.country == "United States"
        cost = (round(road_km / config.KM_PER_MILE * config.IRS_MILEAGE_RATE_USD, 2)
                if mode == "self-driving" and us else None)
        return GroundRoute(mode, a.name, b.name, _hours_text(road_km / AVERAGE_DRIVING_KMH), road_km, cost)

    def find_place(self, kind: str, name: str, cities: list[str]):
        """Find a restaurant, attraction or accommodation by name in one of the given
        cities. Accepts the "Name, City" form as well as a bare name."""
        places = {"restaurant": self.restaurants, "attraction": self.attractions,
                  "accommodation": self.accommodations}[kind]
        text = " ".join(str(name).split())
        candidates = [(text, city) for city in cities]
        if ", " in text:
            bare, suffix = text.rsplit(", ", 1)
            if self.city_name(suffix):
                candidates.insert(0, (bare, suffix))
        for bare, city in candidates:
            for place in places.get(city.lower(), []):
                if place.name.lower() == bare.lower():
                    return place
        return None


def _number(value, default: float | None = 0.0) -> float | None:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return default
    return default if math.isnan(number) else number


def _data_note(data: dict) -> str:
    city = data["city"]
    if data.get("stays_source", "Inside Airbnb") == "OpenStreetMap":
        stays = "places to stay from OpenStreetMap (no prices: use a live stay search for prices"
    else:
        stays = f"places to stay from Inside Airbnb (scraped {data['airbnb_scrape_date']}"
        if data["currency"] != "USD":
            stays += f"; prices converted from {data['currency']} to USD at ECB rates of {data['rates_date']}"
    return (f"{city}: {stays}); restaurants and attractions from OpenStreetMap ({data['fetched_at']}). "
            "Restaurant prices and snapshot flights are not available; flights and drives without live data "
            "are estimated from the distance.")


class _Builder:
    def __init__(self) -> None:
        self.attractions: dict[str, list[Attraction]] = defaultdict(list)
        self.restaurants: dict[str, list[Restaurant]] = defaultdict(list)
        self.accommodations: dict[str, list[Accommodation]] = defaultdict(list)
        self.cities: dict[str, str] = {}
        self.city_info: dict[str, CityInfo] = {}
        self._seen: set[tuple[str, str, str]] = set()

    def _is_new(self, kind: str, name: str, city: str) -> bool:
        key = (kind, name.lower(), city.lower())
        if key in self._seen:
            return False
        self._seen.add(key)
        return True

    def add_city(self, data: dict) -> None:
        city = " ".join(data["city"].split())
        self.cities[city.lower()] = city
        self.city_info[city.lower()] = CityInfo(city, data["country"], data["region"], data["latitude"],
                                                data["longitude"], _data_note(data))
        for record in data.get("accommodations", []):
            if self._is_new("accommodation", record["name"], city):
                occupancy = record.get("maximum_occupancy")
                self.accommodations[city.lower()].append(Accommodation(
                    record["name"], city, _number(record.get("price"), None),
                    ROOM_TYPE_ALIASES.get(record["room_type"], record["room_type"]), None,
                    int(record.get("minimum_nights") or 1), int(occupancy) if occupancy else None,
                    _number(record.get("rating"), None)))
        for record in data.get("restaurants", []):
            if self._is_new("restaurant", record["name"], city):
                self.restaurants[city.lower()].append(Restaurant(
                    record["name"], city, None, tuple(record.get("cuisines", [])), None))
        for record in data.get("attractions", []):
            if self._is_new("attraction", record["name"], city):
                self.attractions[city.lower()].append(Attraction(
                    record["name"], city, record.get("address", ""), record.get("phone", ""),
                    record.get("website", ""), record.get("latitude"), record.get("longitude"),
                    record.get("kind", "")))

    def build(self) -> TravelCatalog:
        cuisines = sorted({c for places in self.restaurants.values() for r in places for c in r.cuisines})
        return TravelCatalog(dict(self.attractions), dict(self.restaurants), dict(self.accommodations),
                             self.cities, self.city_info, tuple(cuisines))


def build_catalog(world_dir: Path = config.WORLD_DIR) -> TravelCatalog:
    """The catalog of every city file in world_dir."""
    paths = sorted(world_dir.glob("*.json")) if world_dir.exists() else []
    if not paths:
        raise FileNotFoundError(f"No city data found in {world_dir}. Run: python -m travel_data.fetch_world")
    builder = _Builder()
    for path in paths:
        builder.add_city(json.loads(path.read_text(encoding="utf-8")))
    return builder.build()


@lru_cache(maxsize=1)
def load_catalog() -> TravelCatalog:
    return build_catalog()
