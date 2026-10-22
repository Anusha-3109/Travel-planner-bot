"""European and Asian city data.

Catalog tests use a small made-up city file, so they don't depend on a fetch.
Tool tests use the real Tokyo file from `python -m travel_data.fetch_world`
and are skipped when it hasn't been fetched.
"""

import json

import pytest

import config
from rag.ingest import place_documents
from tools.places import find_accommodations, find_restaurants
from tools.planning import check_plan, compute_cost
from tools.transport import find_transport
from travel_data.catalog import build_catalog

SAMPLE_CITY = {
    "city": "Kyoto", "country": "Japan", "region": "Asia", "latitude": 35.0116, "longitude": 135.7681,
    "currency": "JPY", "usd_per_unit": 0.0063, "rates_date": "2026-10-21", "airbnb_scrape_date": "2026-09-25",
    "fetched_at": "2026-10-22",
    "accommodations": [{"name": "Machiya by the river", "price": 120.5, "price_local": 19000, "room_type": "Entire home/apt",
                        "minimum_nights": 2, "maximum_occupancy": 4, "rating": 4.9, "reviews": 300, "url": ""}],
    "restaurants": [{"name": "Soba Corner", "cuisines": ["Japanese", "Soba"], "address": "", "website": ""}],
    "attractions": [{"name": "Golden Pavilion", "kind": "attraction", "address": "", "website": "", "phone": "",
                     "latitude": 35.0394, "longitude": 135.7292}],
}

needs_tokyo = pytest.mark.skipif(not (config.WORLD_DIR / "tokyo.json").exists(), reason="run travel_data.fetch_world")


@pytest.fixture(scope="module")
def sample_catalog(tmp_path_factory):
    world_dir = tmp_path_factory.mktemp("world")
    (world_dir / "kyoto.json").write_text(json.dumps(SAMPLE_CITY), encoding="utf-8")
    return build_catalog(world_dir=world_dir)


def test_world_city_is_loaded_with_its_source(sample_catalog):
    info = sample_catalog.city_info["kyoto"]
    assert (info.country, info.region) == ("Japan", "Asia")
    assert "Inside Airbnb" in info.data_note and "OpenStreetMap" in info.data_note
    assert "Kyoto" in sample_catalog.cities_by_region()["Asia"]


def test_missing_values_stay_missing(sample_catalog):
    restaurant = sample_catalog.restaurants["kyoto"][0]
    assert restaurant.average_cost is None and restaurant.rating is None
    stay = sample_catalog.accommodations["kyoto"][0]
    assert stay.house_rules is None
    assert not stay.allows("pets")  # unpublished rules never count as allowing something


def test_flight_estimate_between_continents(sample_catalog):
    estimate = sample_catalog.estimate_flight("New York", "Kyoto")
    assert 10_500 < estimate["distance_km"] < 11_500 and estimate["price"] is None
    assert sample_catalog.estimate_flight("Kyoto", "Kyoto") is None


def test_world_documents_carry_country(sample_catalog):
    documents = place_documents(sample_catalog, cities=["Kyoto"])
    assert {d.metadata["country"] for d in documents} == {"Japan"}
    restaurant = next(d for d in documents if d.metadata["category"] == "restaurant")
    assert "Price not available" in restaurant.page_content and "average_cost" not in restaurant.metadata


@needs_tokyo
def test_tokyo_restaurants_have_no_prices():
    result = find_restaurants("Tokyo", cuisine="Sushi")
    assert result["match_count"] > 0
    assert all(r["average_cost_per_person"] == "not available" for r in result["restaurants"])
    # A price filter can't be met by restaurants without prices.
    assert find_restaurants("Tokyo", max_average_cost=50)["match_count"] == 0


@needs_tokyo
def test_tokyo_stays_priced_in_usd_without_house_rules():
    result = find_accommodations("Tokyo", room_type="private room", people=2, nights=2)
    assert result["match_count"] > 0
    assert all(10 < s["price_per_night"] < 2000 for s in result["accommodations"])
    assert find_accommodations("Tokyo", must_allow="pets")["match_count"] == 0


@needs_tokyo
def test_international_flight_is_estimated_and_unpriced():
    result = find_transport("New York", "Tokyo", "2026-11-10")
    assert result["flight_count"] == 0 and result["estimated_flight"]["price"] is None

    stay = find_accommodations("Tokyo", nights=3)["accommodations"][0]["name"]
    restaurant = find_restaurants("Tokyo")["restaurants"][0]["name"]
    plan = {"people": 1, "budget": 3000, "days": [
        {"day": 1, "city": "Tokyo", "transportation": {"mode": "flight", "origin": "New York", "destination": "Tokyo"},
         "dinner": restaurant, "accommodation": stay},
        {"day": 2, "city": "Tokyo", "accommodation": stay},
        {"day": 3, "city": "Tokyo", "accommodation": stay},
        {"day": 4, "city": "Tokyo", "transportation": {"mode": "flight", "origin": "Tokyo", "destination": "New York"}},
    ]}
    cost = compute_cost(plan)
    assert cost["totals"]["accommodation"] > 0 and cost["totals"]["transportation"] == 0
    assert len(cost["unpriced_items"]) == 3 and not cost["budget_check_complete"]
    budget = next(c for c in check_plan(plan)["hard_constraints"] if c["check"] == "budget")
    assert "no price data" in budget["detail"]
