"""Catalog tests. They read the downloaded TravelPlanner files in data/travelplanner/."""

from collections import Counter, defaultdict
from statistics import median

import pytest

from security.validation import InputValidationError
from tools.planning import HouseRule, RoomType, TransportRule
from travel_data.catalog import HOUSE_RULES, ROOM_TYPES, TRANSPORT_RULES, great_circle_km, load_catalog


@pytest.fixture(scope="module")
def catalog():
    return load_catalog()


def test_catalog_merges_all_bundles(catalog):
    assert sum(map(len, catalog.attractions.values())) > 4000
    assert sum(map(len, catalog.restaurants.values())) > 6000
    assert sum(map(len, catalog.accommodations.values())) > 2500
    assert len(catalog.flights_by_number) > 10000
    assert len(catalog.place_cities()) > 200


def test_places_are_deduplicated(catalog):
    for places in (catalog.attractions, catalog.restaurants, catalog.accommodations):
        counts = Counter((p.name.lower(), p.city.lower()) for city in places.values() for p in city)
        assert max(counts.values()) == 1


def test_ground_routes_are_parsed(catalog):
    route = catalog.ground[("self-driving", "washington", "myrtle beach")]
    assert route.distance_km == 693 and route.cost == 34
    assert route.vehicles_needed(6) == 2
    assert catalog.ground[("taxi", "washington", "myrtle beach")].vehicles_needed(4) == 1


def test_flights_are_indexed_by_route_and_number(catalog):
    numbers = {f.number for f in catalog.flights[("washington", "myrtle beach", "2022-03-13")]}
    assert "F3792603" in numbers
    assert catalog.flights_by_number["F3792603"].price == 164
    assert catalog.flight_dates("Washington", "Myrtle Beach") == ["2022-03-13"]


def test_require_city_suggests_close_matches(catalog):
    assert catalog.require_city("  myrtle   beach ") == "Myrtle Beach"
    with pytest.raises(InputValidationError, match="Did you mean Myrtle Beach"):
        catalog.require_city("Myrtle Bech")


def test_find_place_accepts_name_with_city(catalog):
    assert catalog.find_place("restaurant", "Coco Bambu, Rockford", ["Washington"]).average_cost == 72
    assert catalog.find_place("restaurant", "coco bambu", ["Rockford"]) is not None
    assert catalog.find_place("restaurant", "Coco Bambu", ["Washington"]) is None


def test_constraint_values_match_tool_schemas():
    assert set(HOUSE_RULES) == set(HouseRule.__args__)
    assert set(ROOM_TYPES) == set(RoomType.__args__)
    assert set(TRANSPORT_RULES) == set(TransportRule.__args__)


def test_city_centres_agree_with_flight_distances(catalog):
    """City centres drive the flight estimates, so each one must match the real
    flight distances in the data (TravelPlanner distances are in miles)."""
    ratios = defaultdict(list)
    for flight in catalog.flights_by_number.values():
        a, b = catalog.city_info[flight.origin.lower()], catalog.city_info[flight.destination.lower()]
        if None in (a.latitude, b.latitude) or not flight.distance_miles:
            continue
        ratio = great_circle_km(a.latitude, a.longitude, b.latitude, b.longitude) / 1.609 / flight.distance_miles
        ratios[flight.origin].append(ratio)
        ratios[flight.destination].append(ratio)
    off = {city: round(median(r), 2) for city, r in ratios.items() if len(r) >= 5 and not 0.75 < median(r) < 1.33}
    assert off == {}
