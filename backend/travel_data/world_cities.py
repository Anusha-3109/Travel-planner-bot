"""Cities with 2026 snapshot data.

16 European and Asian cities and 34 US areas with Inside Airbnb stays, and the
smaller US cities from TravelPlanner (data/us_cities.json), which have no
Inside Airbnb data: their stays are OpenStreetMap hotels, motels and guest
houses without prices. Each city has a centre point
(used for OpenStreetMap searches, for keeping Airbnb listings near the city
and for flight distance estimates), the currency its Inside Airbnb prices are
listed in, and the Inside Airbnb scrape to use.

Some Inside Airbnb areas are wider than one city (a county, a metro area or a
whole state such as Hawaii). For those, max_km keeps only listings within that
distance of the centre. Taipei has Inside Airbnb data but is left out because
the ECB publishes no rate for the Taiwan dollar.
"""

import json
from dataclasses import dataclass
from pathlib import Path

AIRBNB_BASE = "https://data.insideairbnb.com"
US = "United States"
US_CITIES_FILE = Path(__file__).resolve().parents[2] / "data" / "us_cities.json"


@dataclass(frozen=True)
class WorldCity:
    name: str
    country: str
    region: str  # "Europe", "Asia" or "North America"
    latitude: float
    longitude: float
    currency: str
    airbnb_path: str  # <country>/<region>/<city>/<scrape date>; empty: no Inside Airbnb data
    max_km: float | None = None  # keep only listings this close to the centre

    @property
    def slug(self) -> str:
        return self.name.lower().replace(" ", "-")

    @property
    def listings_url(self) -> str:
        return f"{AIRBNB_BASE}/{self.airbnb_path}/data/listings.csv.gz"

    @property
    def scrape_date(self) -> str:
        return self.airbnb_path.rsplit("/", 1)[-1]


def _us(name: str, latitude: float, longitude: float, path: str, max_km: float | None = None) -> WorldCity:
    return WorldCity(name, US, "North America", latitude, longitude, "USD", f"united-states/{path}", max_km)


EUROPE_AND_ASIA = (
    WorldCity("London", "United Kingdom", "Europe", 51.5074, -0.1278, "GBP", "united-kingdom/england/london/2026-09-17"),
    WorldCity("Paris", "France", "Europe", 48.8566, 2.3522, "EUR", "france/ile-de-france/paris/2026-09-16"),
    WorldCity("Rome", "Italy", "Europe", 41.9028, 12.4964, "EUR", "italy/lazio/rome/2026-09-17"),
    WorldCity("Barcelona", "Spain", "Europe", 41.3874, 2.1686, "EUR", "spain/catalonia/barcelona/2026-09-17"),
    WorldCity("Madrid", "Spain", "Europe", 40.4168, -3.7038, "EUR", "spain/comunidad-de-madrid/madrid/2026-09-17"),
    WorldCity("Amsterdam", "Netherlands", "Europe", 52.3676, 4.9041, "EUR",
              "the-netherlands/north-holland/amsterdam/2026-09-16"),
    WorldCity("Berlin", "Germany", "Europe", 52.5200, 13.4050, "EUR", "germany/be/berlin/2026-09-19"),
    WorldCity("Vienna", "Austria", "Europe", 48.2082, 16.3738, "EUR", "austria/vienna/vienna/2026-09-17"),
    WorldCity("Prague", "Czech Republic", "Europe", 50.0755, 14.4378, "CZK", "czech-republic/prague/prague/2026-09-20"),
    WorldCity("Lisbon", "Portugal", "Europe", 38.7223, -9.1393, "EUR", "portugal/lisbon/lisbon/2026-09-19"),
    WorldCity("Athens", "Greece", "Europe", 37.9838, 23.7275, "EUR", "greece/attica/athens/2026-09-22"),
    WorldCity("Istanbul", "Turkey", "Europe", 41.0082, 28.9784, "TRY", "turkey/marmara/istanbul/2026-09-25"),
    WorldCity("Tokyo", "Japan", "Asia", 35.6812, 139.7671, "JPY", "japan/kant%C5%8D/tokyo/2026-09-25"),
    WorldCity("Bangkok", "Thailand", "Asia", 13.7563, 100.5018, "THB", "thailand/central-thailand/bangkok/2026-09-22"),
    WorldCity("Singapore", "Singapore", "Asia", 1.2903, 103.8519, "SGD", "singapore/sg/singapore/2026-09-23"),
    WorldCity("Hong Kong", "Hong Kong", "Asia", 22.2855, 114.1577, "HKD", "china/hk/hong-kong/2026-09-20"),
)

UNITED_STATES = (
    _us("Albany", 42.6526, -73.7562, "ny/albany/2026-09-14"),
    _us("Asheville", 35.5951, -82.5515, "nc/asheville/2026-09-19"),
    _us("Austin", 30.2672, -97.7431, "tx/austin/2026-09-17"),
    _us("Boston", 42.3601, -71.0589, "ma/boston/2026-09-19"),
    _us("Bozeman", 45.6770, -111.0429, "mt/bozeman/2026-09-16"),
    _us("Fort Lauderdale", 26.1224, -80.1373, "fl/broward-county/2026-09-22", max_km=30),
    _us("Cambridge", 42.3736, -71.1097, "ma/cambridge/2026-09-23"),
    _us("Chicago", 41.8781, -87.6298, "il/chicago/2026-09-19"),
    _us("Las Vegas", 36.1699, -115.1398, "nv/clark-county-nv/2026-09-20", max_km=30),
    _us("Columbus", 39.9612, -82.9988, "oh/columbus/2026-09-22"),
    _us("Dallas", 32.7767, -96.7970, "tx/dallas/2026-09-19"),
    _us("Denver", 39.7392, -104.9903, "co/denver/2026-09-25"),
    _us("Fort Worth", 32.7555, -97.3308, "tx/fort-worth/2026-09-17"),
    _us("Honolulu", 21.3069, -157.8583, "hi/hawaii/2026-09-17", max_km=30),
    _us("Jersey City", 40.7178, -74.0431, "nj/jersey-city/2026-09-21"),
    _us("Los Angeles", 34.0522, -118.2437, "ca/los-angeles/2026-09-14", max_km=40),
    _us("Nashville", 36.1627, -86.7816, "tn/nashville/2026-09-19"),
    _us("New Orleans", 29.9511, -90.0715, "la/new-orleans/2026-09-16"),
    _us("New York", 40.7128, -74.0060, "ny/new-york-city/2026-09-14"),
    _us("Newark", 40.7357, -74.1724, "nj/newark/2026-09-28"),
    _us("Oakland", 37.8044, -122.2712, "ca/oakland/2026-09-20"),
    _us("Pacific Grove", 36.6177, -121.9166, "ca/pacific-grove/2026-09-30"),
    _us("Portland", 45.5152, -122.6784, "or/portland/2026-09-14"),
    _us("Providence", 41.8240, -71.4128, "ri/rhode-island/2026-09-28", max_km=25),
    _us("Rochester", 43.1566, -77.6088, "ny/rochester/2026-09-21"),
    _us("Salem", 44.9429, -123.0351, "or/salem-or/2026-09-21"),
    _us("San Diego", 32.7157, -117.1611, "ca/san-diego/2026-09-20"),
    _us("San Francisco", 37.7749, -122.4194, "ca/san-francisco/2026-09-14"),
    _us("San Mateo", 37.5630, -122.3255, "ca/san-mateo-county/2026-09-21", max_km=20),
    _us("San Jose", 37.3382, -121.8863, "ca/santa-clara-county/2026-09-21", max_km=25),
    _us("Santa Cruz", 36.9741, -122.0308, "ca/santa-cruz-county/2026-09-28", max_km=20),
    _us("Seattle", 47.6062, -122.3321, "wa/seattle/2026-09-20"),
    _us("Minneapolis", 44.9778, -93.2650, "mn/twin-cities-msa/2026-09-20", max_km=25),
    _us("Washington", 38.9072, -77.0369, "dc/washington-dc/2026-09-19"),
)

# The smaller US cities (TravelPlanner's other cities, with centres from its attractions).
SMALLER_US_CITIES = tuple(
    WorldCity(row["name"], US, "North America", row["latitude"], row["longitude"], "USD", "")
    for row in json.loads(US_CITIES_FILE.read_text(encoding="utf-8")))

WORLD_CITIES = EUROPE_AND_ASIA + UNITED_STATES + SMALLER_US_CITIES
