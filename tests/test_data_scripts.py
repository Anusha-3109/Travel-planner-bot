"""The data scripts (dataset download and world-city fetch), with every download replaced by fake data."""

import json

import pandas as pd
import pytest

import config
from travel_data import download, fetch_world
from travel_data.world_cities import WORLD_CITIES

ECB_XML = b"""<gesmes:Envelope xmlns:gesmes="http://www.gesmes.org/xml/2002-08-01"
 xmlns="http://www.ecb.int/vocabulary/2002-08-01/eurofxref"><Cube><Cube time="2026-10-21">
 <Cube currency="USD" rate="1.25"/><Cube currency="JPY" rate="125"/></Cube></Cube></gesmes:Envelope>"""
TOKYO = next(c for c in WORLD_CITIES if c.name == "Tokyo")


class FakeResponse:
    def __init__(self, status_code=200, content=b"", payload=None):
        self.status_code, self.content, self._payload = status_code, content, payload

    def raise_for_status(self):
        if self.status_code >= 400:
            raise RuntimeError(f"HTTP {self.status_code}")

    def json(self):
        return self._payload


def test_world_cities_have_urls_and_slugs():
    assert TOKYO.slug == "tokyo" and TOKYO.scrape_date == "2026-09-25"
    assert TOKYO.listings_url.startswith("https://data.insideairbnb.com/japan/") and TOKYO.listings_url.endswith(".csv.gz")
    assert len({c.slug for c in WORLD_CITIES}) == len(WORLD_CITIES) == 245


def test_usd_rates_from_the_ecb(monkeypatch):
    monkeypatch.setattr(fetch_world.requests, "get", lambda *a, **k: FakeResponse(content=ECB_XML))
    rates, day = fetch_world.fetch_usd_rates()
    assert day == "2026-10-21" and rates["EUR"] == 1.25 and rates["JPY"] == 0.01


@pytest.mark.parametrize("raw, price", [("$14,280.00", 14280.0), ("¥9,442", 9442.0), ("", None), (None, None)])
def test_airbnb_price_text_is_parsed(raw, price):
    assert fetch_world._price(raw) == price


def test_stays_are_filtered_converted_and_sorted(monkeypatch):
    listings = pd.DataFrame([
        {"name": "Busy  flat", "listing_url": "u1", "room_type": "Entire home/apt", "accommodates": 3,
         "price": "$14,280.00", "minimum_nights": 1, "number_of_reviews": 400, "review_scores_rating": 4.76},
        {"name": "Quiet room", "listing_url": "u2", "room_type": "Private room", "accommodates": 2,
         "price": "$9,442.00", "minimum_nights": 3, "number_of_reviews": 50, "review_scores_rating": None},
        {"name": "Too few reviews", "listing_url": "u3", "room_type": "Private room", "accommodates": 2,
         "price": "$5,000.00", "minimum_nights": 1, "number_of_reviews": 2, "review_scores_rating": 5.0},
        {"name": "No price", "listing_url": "u4", "room_type": "Private room", "accommodates": 2,
         "price": None, "minimum_nights": 1, "number_of_reviews": 90, "review_scores_rating": 4.0},
    ])
    monkeypatch.setattr(fetch_world.pd, "read_csv", lambda *a, **k: listings)
    stays = fetch_world.fetch_stays(TOKYO, usd_per_unit=0.0063)
    assert [s["name"] for s in stays] == ["Busy flat", "Quiet room"]  # most reviewed first; bad rows dropped
    assert stays[0]["price"] == round(14280 * 0.0063, 2) and stays[0]["maximum_occupancy"] == 3
    assert stays[1]["rating"] is None


def test_openstreetmap_places_prefer_latin_names_and_skip_duplicates(monkeypatch):
    elements = [
        {"tags": {"amenity": "restaurant", "name": "寿司", "cuisine": "sushi"}},
        {"tags": {"amenity": "restaurant", "name": "Sushi Zanmai", "name:en": "Sushi Zanmai", "cuisine": "sushi;japanese",
                  "addr:housenumber": "4", "addr:street": "Tsukiji", "website": "https://x.test"}},
        {"tags": {"amenity": "restaurant", "name": "Sushi Zanmai", "cuisine": "sushi"}},
        {"tags": {"amenity": "restaurant", "name": "Ramen Bar", "cuisine": "ramen"}},
    ]
    monkeypatch.setattr(fetch_world, "_overpass", lambda query: elements)
    restaurants = fetch_world.fetch_restaurants(TOKYO)
    assert [r["name"] for r in restaurants][:2] == ["Sushi Zanmai", "Ramen Bar"]
    assert restaurants[0]["cuisines"] == ["Sushi", "Japanese"] and restaurants[0]["address"] == "4 Tsukiji"
    assert len([r for r in restaurants if r["name"] == "Sushi Zanmai"]) == 1


def test_attractions_use_way_centres(monkeypatch):
    elements = [{"type": "way", "center": {"lat": 35.7, "lon": 139.8},
                 "tags": {"name": "Edo Tokyo Museum", "tourism": "museum", "wikidata": "Q1"}}]
    monkeypatch.setattr(fetch_world, "_overpass", lambda query: elements)
    attraction = fetch_world.fetch_attractions(TOKYO)[0]
    assert attraction["kind"] == "museum" and (attraction["latitude"], attraction["longitude"]) == (35.7, 139.8)


def test_overpass_backs_off_when_busy(monkeypatch):
    answers = [FakeResponse(429), FakeResponse(200, payload={"elements": [{"tags": {"name": "A"}}]})]
    monkeypatch.setattr(fetch_world.requests, "post", lambda *a, **k: answers.pop(0))
    monkeypatch.setattr(fetch_world.time, "sleep", lambda _: None)
    assert fetch_world._overpass("query") == [{"tags": {"name": "A"}}]


def test_one_failing_city_does_not_stop_the_rest(monkeypatch, tmp_path):
    monkeypatch.setattr(config, "WORLD_DIR", tmp_path)
    monkeypatch.setattr(fetch_world, "fetch_usd_rates", lambda: ({"JPY": 0.0063, "EUR": 1.12}, "2026-10-21"))
    monkeypatch.setattr(fetch_world.time, "sleep", lambda _: None)

    def fetch_city(city, rates, rates_date):
        if city.name == "Paris":
            raise RuntimeError("Overpass is busy")
        return {"city": city.name, "accommodations": [{"price": 100.0}], "restaurants": [], "attractions": []}
    monkeypatch.setattr(fetch_world, "fetch_city", fetch_city)
    fetch_world.main(["Tokyo", "Paris"])
    assert [p.name for p in tmp_path.iterdir()] == ["tokyo.json"]
    assert json.loads((tmp_path / "tokyo.json").read_text(encoding="utf-8"))["city"] == "Tokyo"


def test_unknown_city_name_stops_with_a_message():
    with pytest.raises(SystemExit, match="Unknown city"):
        fetch_world.main(["Atlantis"])


def test_dataset_download_copies_every_file(monkeypatch, tmp_path):
    source = tmp_path / "cached.txt"
    source.write_text("data", encoding="utf-8")
    asked = []
    monkeypatch.setattr(download, "hf_hub_download", lambda repo, name, repo_type: asked.append(name) or str(source))
    paths = download.download(target_dir=tmp_path / "travelplanner")
    assert asked == list(download.FILES)
    assert [p.name for p in paths] == list(download.FILES) and all(p.read_text() == "data" for p in paths)


def test_wide_areas_keep_only_listings_near_the_city(monkeypatch):
    honolulu = next(c for c in WORLD_CITIES if c.name == "Honolulu")
    assert honolulu.max_km == 30 and honolulu.currency == "USD" and honolulu.region == "North America"
    listings = pd.DataFrame([
        {"name": "Waikiki studio", "listing_url": "u1", "room_type": "Entire home/apt", "accommodates": 2,
         "price": "$180.00", "minimum_nights": 2, "number_of_reviews": 300, "review_scores_rating": 4.8,
         "latitude": 21.28, "longitude": -157.83},
        {"name": "Maui cottage", "listing_url": "u2", "room_type": "Entire home/apt", "accommodates": 2,
         "price": "$220.00", "minimum_nights": 2, "number_of_reviews": 500, "review_scores_rating": 4.9,
         "latitude": 20.80, "longitude": -156.33},
    ])
    monkeypatch.setattr(fetch_world.pd, "read_csv", lambda *a, **k: listings)
    stays = fetch_world.fetch_stays(honolulu, usd_per_unit=1.0)
    assert [s["name"] for s in stays] == ["Waikiki studio"] and stays[0]["price"] == 180.0


def test_us_areas_are_listed():
    us = [c for c in WORLD_CITIES if c.country == "United States"]
    airbnb = [c for c in us if c.airbnb_path]
    assert len(airbnb) == 34 and all(c.listings_url.startswith("https://data.insideairbnb.com/united-states/")
                                     for c in airbnb)
    assert len(us) - len(airbnb) == 195  # smaller US cities: OpenStreetMap stays only


def test_smaller_city_uses_one_combined_request(monkeypatch):
    from travel_data.world_cities import SMALLER_US_CITIES
    queries = []
    elements = [
        {"tags": {"amenity": "restaurant", "name": "Waffle House", "cuisine": "american"}},
        {"tags": {"tourism": "motel", "name": "Waikiki Village"}},
        {"tags": {"tourism": "museum", "name": "Hollywood Wax Museum"}, "center": {"lat": 33.7, "lon": -78.9}},
    ]
    monkeypatch.setattr(fetch_world, "_overpass", lambda query: queries.append(query) or elements)
    data = fetch_world.fetch_city(SMALLER_US_CITIES[0], {"USD": 1.0}, "2026-10-26")
    assert len(queries) == 1 and data["stays_source"] == "OpenStreetMap" and data["airbnb_scrape_date"] is None
    assert [s["name"] for s in data["accommodations"]] == ["Waikiki Village"]
    assert data["accommodations"][0]["price"] is None and data["accommodations"][0]["room_type"] == "Hotel room"
    assert [r["name"] for r in data["restaurants"]] == ["Waffle House"]
    assert [a["name"] for a in data["attractions"]] == ["Hollywood Wax Museum"]
