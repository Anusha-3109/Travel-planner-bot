"""In-memory catalog of all travel data: US cities from TravelPlanner, plus
European and Asian cities fetched by travel_data/fetch_world.py.

Every TravelPlanner query ships its own bundle of reference data (the
*_ref_info.jsonl files): attractions, restaurants and accommodations in the
destination, flights on each travel date, and self-driving and taxi routes.
The bundles overlap heavily, so they are merged and de-duplicated here. The
world cities (data/world/*.json) are added on top. Some values are missing for
them (restaurant prices, ratings and house rules), and those are None here.
"""

import difflib
import json
import math
import re
import statistics
from collections import defaultdict
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

import config
from security.validation import InputValidationError, validate_city

SPLITS = ("train", "validation", "test")
US_DATA_NOTE = "TravelPlanner snapshot data (US cities, March 2022), not live schedules or prices."

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
SELF_DRIVING_SEATS = 5  # TravelPlanner costs one car per 5 travellers
TAXI_SEATS = 4  # and one taxi per 4

EARTH_RADIUS_KM = 6371.0
ROUTE_DETOUR_FACTOR = 1.05  # real flight paths are a little longer than great-circle distance
TAXI_AND_CLIMB_HOURS = 0.5
MIN_FLIGHT_KM = 150
# US city centres come from the median position of each city's attractions. For two
# cities TravelPlanner's attractions are in the wrong place ("Washington" lists Seattle
# sights and "Manchester" lists Manchester, England), while its flights and drives use
# Washington, D.C. and Manchester, NH. tests/test_travel_data.py checks every city's
# centre against the flight distances in the data, which is how these were found.
US_CENTRE_OVERRIDES = {"washington": (38.9072, -77.0369), "manchester": (42.9956, -71.4548)}

_GROUND_PATTERN = re.compile(
    r"^(?P<mode>self-driving|taxi), from (?P<origin>.+?) to (?P<destination>.+?), "
    r"duration: (?P<duration>.+?), distance: (?P<distance>[\d.]+) km, cost: (?P<cost>[\d.]+)$"
)


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
    price: float
    room_type: str
    house_rules: tuple[str, ...] | None  # None: the source doesn't publish house rules
    minimum_nights: int
    maximum_occupancy: int
    rating: float | None

    def allows(self, rule: str) -> bool:
        """Only a stay whose published rules don't forbid it counts as allowing it."""
        return self.house_rules is not None and HOUSE_RULES[rule] not in self.house_rules

    def matches_room_type(self, room_type: str) -> bool:
        if room_type == "not shared room":
            return self.room_type != ROOM_TYPES["shared room"]
        return self.room_type == ROOM_TYPES[room_type]

    def rooms_needed(self, people: int) -> int:
        return math.ceil(people / max(self.maximum_occupancy, 1))


@dataclass(frozen=True)
class Flight:
    number: str
    origin: str
    destination: str
    date: str
    price: float
    departure: str
    arrival: str
    duration: str
    distance_miles: float  # TravelPlanner gives flight distances in miles


@dataclass(frozen=True)
class GroundRoute:
    mode: str  # "self-driving" or "taxi"
    origin: str
    destination: str
    duration: str
    distance_km: float
    cost: float

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


@dataclass
class TravelCatalog:
    # Places are keyed by lower-case city; flights and routes by lower-case city names.
    attractions: dict[str, list[Attraction]]
    restaurants: dict[str, list[Restaurant]]
    accommodations: dict[str, list[Accommodation]]
    flights: dict[tuple[str, str, str], list[Flight]]  # (origin, destination, date)
    flights_by_number: dict[str, Flight]
    ground: dict[tuple[str, str, str], GroundRoute]  # (mode, origin, destination)
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
        raise InputValidationError(f"'{city}' isn't in the travel data.{hint} "
                                   "It covers US cities and selected European and Asian cities.")

    def data_note(self, city: str) -> str:
        info = self.city_info.get(city.lower())
        return info.data_note if info else US_DATA_NOTE

    def place_cities(self) -> list[str]:
        keys = set(self.attractions) | set(self.restaurants) | set(self.accommodations)
        return sorted(self.cities[key] for key in keys)

    def cities_by_region(self) -> dict[str, list[str]]:
        regions: dict[str, list[str]] = defaultdict(list)
        for name in self.place_cities():
            regions[self.city_info[name.lower()].region].append(name)
        return dict(regions)

    def flight_dates(self, origin: str, destination: str) -> list[str]:
        origin, destination = origin.lower(), destination.lower()
        return sorted(date for (o, d, date), flights in self.flights.items()
                      if o == origin and d == destination and flights)

    def estimate_flight(self, origin: str, destination: str) -> dict | None:
        """Distance and nonstop flight time between two city centres, or None when a
        city has no coordinates or the cities are too close to fly between."""
        a, b = self.city_info.get(origin.lower()), self.city_info.get(destination.lower())
        if not a or not b or None in (a.latitude, b.latitude):
            return None
        distance = great_circle_km(a.latitude, a.longitude, b.latitude, b.longitude)
        if distance < MIN_FLIGHT_KM:
            return None
        hours = estimate_flight_hours(distance)
        minutes = round(hours * 60 / 5) * 5
        return {"distance_km": round(distance), "estimated_nonstop_duration": f"{minutes // 60}h {minutes % 60:02d}m",
                "price": None}

    def find_place(self, kind: str, name: str, cities: list[str]):
        """Find a restaurant, attraction or accommodation by name in one of the given
        cities. Accepts TravelPlanner's "Name, City" form as well as a bare name."""
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


def _text(value) -> str:
    return "" if value is None or (isinstance(value, float) and math.isnan(value)) else str(value).strip()


def _split(value, separator: str) -> tuple[str, ...]:
    return tuple(part.strip() for part in _text(value).split(separator) if part.strip())


class _Builder:
    def __init__(self) -> None:
        self.attractions: dict[str, list[Attraction]] = defaultdict(list)
        self.restaurants: dict[str, list[Restaurant]] = defaultdict(list)
        self.accommodations: dict[str, list[Accommodation]] = defaultdict(list)
        self.flights: dict[tuple[str, str, str], list[Flight]] = {}
        self.ground: dict[tuple[str, str, str], GroundRoute] = {}
        self.cities: dict[str, str] = {}
        self.city_info: dict[str, CityInfo] = {}
        self._seen: set[tuple[str, str, str]] = set()

    def _city(self, name: str) -> str:
        name = _text(name)
        self.cities.setdefault(name.lower(), name)
        return name

    def _is_new(self, kind: str, name: str, city: str) -> bool:
        key = (kind, name.lower(), city.lower())
        if key in self._seen:
            return False
        self._seen.add(key)
        return True

    # --- TravelPlanner bundles -------------------------------------------------

    def add_bundle(self, bundle: dict) -> None:
        for description, value in bundle.items():
            kind = description.split(" ", 1)[0]
            if kind in ("Self-driving", "Taxi"):
                self._add_ground(value)
            elif not isinstance(value, list):
                continue  # "There is no flight from ..." and similar notices
            elif kind == "Flight":
                self._add_flights(value)
            else:
                for record in value:
                    getattr(self, f"_add_{kind.lower()}", lambda _: None)(record)

    def _add_attractions(self, record: dict) -> None:
        name, city = _text(record.get("Name")), self._city(record.get("City"))
        if name and self._is_new("attraction", name, city):
            self.attractions[city.lower()].append(Attraction(
                name, city, _text(record.get("Address")), _text(record.get("Phone")), _text(record.get("Website")),
                _number(record.get("Latitude"), None), _number(record.get("Longitude"), None)))

    def _add_restaurants(self, record: dict) -> None:
        name, city = _text(record.get("Name")), self._city(record.get("City"))
        if name and self._is_new("restaurant", name, city):
            self.restaurants[city.lower()].append(Restaurant(
                name, city, _number(record.get("Average Cost")), _split(record.get("Cuisines"), ","),
                _number(record.get("Aggregate Rating"))))

    def _add_accommodations(self, record: dict) -> None:
        name, city = _text(record.get("NAME")), self._city(record.get("city"))
        if name and self._is_new("accommodation", name, city):
            self.accommodations[city.lower()].append(Accommodation(
                name, city, _number(record.get("price")), _text(record.get("room type")),
                _split(record.get("house_rules"), " & "), int(_number(record.get("minimum nights"), 1)),
                int(_number(record.get("maximum occupancy"), 1)), _number(record.get("review rate number"))))

    def _add_flights(self, records: list[dict]) -> None:
        for record in records:
            flight = Flight(
                _text(record.get("Flight Number")), self._city(record.get("OriginCityName")),
                self._city(record.get("DestCityName")), _text(record.get("FlightDate")), _number(record.get("Price")),
                _text(record.get("DepTime")), _text(record.get("ArrTime")), _text(record.get("ActualElapsedTime")),
                _number(record.get("Distance")))
            key = (flight.origin.lower(), flight.destination.lower(), flight.date)
            flights = self.flights.setdefault(key, [])
            if flight.number not in {f.number for f in flights}:
                flights.append(flight)

    def _add_ground(self, value) -> None:
        match = _GROUND_PATTERN.match(_text(value))
        if not match:
            return  # "No valid information." means the route can't be driven
        route = GroundRoute(match["mode"], self._city(match["origin"]), self._city(match["destination"]),
                            match["duration"], _number(match["distance"]), _number(match["cost"]))
        self.ground.setdefault((route.mode, route.origin.lower(), route.destination.lower()), route)

    # --- World cities ----------------------------------------------------------

    def add_world_city(self, data: dict) -> None:
        city = self._city(data["city"])
        self.city_info[city.lower()] = CityInfo(
            city, data["country"], data["region"], data["latitude"], data["longitude"],
            f"{city}: places to stay from Inside Airbnb (scraped {data['airbnb_scrape_date']}; prices converted from "
            f"{data['currency']} to USD at ECB rates of {data['rates_date']}); restaurants and attractions from "
            f"OpenStreetMap ({data['fetched_at']}). Restaurant prices and flight prices are not available.")
        for record in data.get("accommodations", []):
            if self._is_new("accommodation", record["name"], city):
                self.accommodations[city.lower()].append(Accommodation(
                    record["name"], city, float(record["price"]), record["room_type"], None,
                    int(record["minimum_nights"]), int(record["maximum_occupancy"]), _number(record.get("rating"), None)))
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
        flights_by_number: dict[str, Flight] = {}
        for flights in self.flights.values():
            for flight in flights:
                flights_by_number.setdefault(flight.number.upper(), flight)
        # US cities: the centre is the median position of the city's attractions.
        for key, name in self.cities.items():
            if key in self.city_info:
                continue
            points = [(a.latitude, a.longitude) for a in self.attractions.get(key, []) if a.latitude is not None]
            latitude = statistics.median(p[0] for p in points) if points else None
            longitude = statistics.median(p[1] for p in points) if points else None
            latitude, longitude = US_CENTRE_OVERRIDES.get(key, (latitude, longitude))
            self.city_info[key] = CityInfo(name, "United States", "North America", latitude, longitude, US_DATA_NOTE)
        cuisines = sorted({c for places in self.restaurants.values() for r in places for c in r.cuisines})
        return TravelCatalog(dict(self.attractions), dict(self.restaurants), dict(self.accommodations),
                             self.flights, flights_by_number, self.ground, self.cities, self.city_info,
                             tuple(cuisines))


def build_catalog(data_dir: Path = config.TRAVELPLANNER_DIR, world_dir: Path = config.WORLD_DIR) -> TravelCatalog:
    paths = [data_dir / f"{split}_ref_info.jsonl" for split in SPLITS]
    missing = [path.name for path in paths if not path.exists()]
    if missing:
        raise FileNotFoundError(
            f"TravelPlanner data not found ({', '.join(missing)}). Run: python -m travel_data.download")
    builder = _Builder()
    for path in paths:
        with open(path, encoding="utf-8") as file:
            for line in file:
                if line.strip():
                    builder.add_bundle(json.loads(line))
    # World cities are optional: without them the catalog is US-only.
    for path in sorted(world_dir.glob("*.json")) if world_dir.exists() else []:
        builder.add_world_city(json.loads(path.read_text(encoding="utf-8")))
    return builder.build()


@lru_cache(maxsize=1)
def load_catalog() -> TravelCatalog:
    return build_catalog()
