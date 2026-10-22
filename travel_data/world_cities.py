"""European and Asian cities added on top of the US TravelPlanner data.

Each city has a centre point (used for OpenStreetMap searches and flight
distance estimates), the currency its Inside Airbnb prices are listed in, and
the Inside Airbnb scrape to use. Taipei has Inside Airbnb data but is left out
because the ECB publishes no rate for the Taiwan dollar.
"""

from dataclasses import dataclass

AIRBNB_BASE = "https://data.insideairbnb.com"


@dataclass(frozen=True)
class WorldCity:
    name: str
    country: str
    region: str  # "Europe" or "Asia"
    latitude: float
    longitude: float
    currency: str
    airbnb_path: str  # <country>/<region>/<city>/<scrape date>

    @property
    def slug(self) -> str:
        return self.name.lower().replace(" ", "-")

    @property
    def listings_url(self) -> str:
        return f"{AIRBNB_BASE}/{self.airbnb_path}/data/listings.csv.gz"

    @property
    def scrape_date(self) -> str:
        return self.airbnb_path.rsplit("/", 1)[-1]


WORLD_CITIES = (
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
