"""Catalog tests. They read the 2026 city files committed in data/world/."""

from collections import Counter

import pytest

from backend import config
from backend.security.validation import InputValidationError
from backend.tools.planning import HouseRule, RoomType, TransportRule
from backend.travel_data.catalog import HOUSE_RULES, ROOM_TYPES, TRANSPORT_RULES, build_catalog, load_catalog


@pytest.fixture(scope="module")
def catalog():
    return load_catalog()


def test_catalog_has_every_city_file(catalog):
    files = list(config.WORLD_DIR.glob("*.json"))
    assert len(catalog.cities) == len(files) >= 50
    assert catalog.city_info["boston"].country == "United States" and catalog.city_info["rome"].region == "Europe"
    assert not hasattr(catalog, "flights") and not hasattr(catalog, "ground")  # no 2022 snapshot routes


def test_places_are_deduplicated(catalog):
    for places in (catalog.attractions, catalog.restaurants, catalog.accommodations):
        counts = Counter((p.name.lower(), p.city.lower()) for city in places.values() for p in city)
        assert max(counts.values()) == 1


def test_openstreetmap_stays_have_no_prices(catalog):
    stays = catalog.accommodations["myrtle beach"]
    assert stays and all(s.price is None and s.maximum_occupancy is None for s in stays)
    assert stays[0].rooms_needed(3) == 2  # without a guest limit a room sleeps 2
    assert "OpenStreetMap (no prices" in catalog.data_note("Myrtle Beach")
    airbnb = catalog.accommodations["boston"]
    assert all(s.price is not None for s in airbnb) and "Inside Airbnb" in catalog.data_note("Boston")


def test_hotel_rooms_count_as_private_rooms(catalog):
    assert {s.room_type for city in catalog.accommodations.values() for s in city} <= {
        "Entire home/apt", "Private room", "Shared room"}


def test_drives_are_estimated_from_the_distance(catalog):
    car = catalog.estimate_drive("self-driving", "Washington", "Myrtle Beach")
    assert 650 < car.distance_km < 850 and car.duration.startswith("9h")
    assert car.cost == round(car.distance_km / config.KM_PER_MILE * config.IRS_MILEAGE_RATE_USD, 2)
    assert car.vehicles_needed(6) == 2
    taxi = catalog.estimate_drive("taxi", "Washington", "Myrtle Beach")
    assert taxi.cost is None and taxi.vehicles_needed(4) == 1
    assert catalog.estimate_drive("self-driving", "Rome", "Paris").cost is None  # IRS rate is US only


def test_require_city_suggests_close_matches(catalog):
    assert catalog.require_city("  myrtle   beach ") == "Myrtle Beach"
    with pytest.raises(InputValidationError, match="Did you mean Myrtle Beach"):
        catalog.require_city("Myrtle Bech")


def test_find_place_accepts_name_with_city(catalog):
    name = catalog.restaurants["myrtle beach"][0].name
    assert catalog.find_place("restaurant", f"{name}, Myrtle Beach", ["Boston"]).city == "Myrtle Beach"
    assert catalog.find_place("restaurant", name.lower(), ["Myrtle Beach"]) is not None
    assert catalog.find_place("restaurant", name, ["Boston"]) is None


def test_constraint_values_match_tool_schemas():
    assert set(HOUSE_RULES) == set(HouseRule.__args__)
    assert set(ROOM_TYPES) == set(RoomType.__args__)
    assert set(TRANSPORT_RULES) == set(TransportRule.__args__)


def test_missing_city_files_are_reported(tmp_path):
    with pytest.raises(FileNotFoundError, match="fetch_world"):
        build_catalog(tmp_path)
