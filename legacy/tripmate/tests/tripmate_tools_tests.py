import json

import pytest

from tools.flights import estimate_duration, estimate_flight_duration, find_airports, find_routes, search_flight_routes
from tools.insurance import calculate_premium, calculate_travel_insurance_estimate
from security.validation import InputValidationError


def test_ambiguous_city_prefers_busiest_country():
    airports = find_airports("London")
    assert {a.country for a in airports} == {"United Kingdom"}
    assert {"LHR", "LGW"} <= {a.iata for a in airports[:3]}


def test_metro_airports_filed_under_other_city_are_included():
    assert {"JFK", "LGA", "EWR"} <= {a.iata for a in find_airports("New York")}


def test_shared_airline_code_uses_main_carrier():
    airlines = {r["airline"] for r in find_routes("Paris", "Tokyo")["routes"]}
    assert "Japan Airlines" in airlines
    assert "Japan Airlines Domestic" not in airlines


def test_country_override():
    assert {a.country for a in find_airports("London", "Canada")} == {"Canada"}


def test_routes_london_new_york():
    result = find_routes("London", "New York")
    assert result["route_count"] > 0
    airlines = {r["airline"] for r in result["routes"]}
    assert "British Airways" in airlines


def test_duration_london_paris_is_short():
    result = estimate_duration("London", "Paris")
    assert 250 < result["great_circle_distance_km"] < 400
    assert 0.75 < result["estimated_hours"] < 1.5


def test_duration_long_haul():
    result = estimate_duration("Tokyo", "New York")
    assert 11 < result["estimated_hours"] < 16


def test_unknown_city_returns_error_json():
    output = json.loads(search_flight_routes.invoke({"origin_city": "Notarealcity", "destination_city": "Paris"}))
    assert "error" in output
    output = json.loads(estimate_flight_duration.invoke({"origin_city": "London", "destination_city": "123"}))
    assert "error" in output


def test_premium_increases_with_age():
    young = calculate_premium(2000, 7, 30, "international")["estimated_premium_usd"]
    older = calculate_premium(2000, 7, 72, "international")["estimated_premium_usd"]
    assert older > young


def test_premium_minimum_applies():
    assert calculate_premium(100, 1, 20, "domestic")["estimated_premium_usd"] == 25.0


def test_premium_invalid_input():
    with pytest.raises(InputValidationError):
        calculate_premium(-5, 7, 30, "international")
    output = json.loads(calculate_travel_insurance_estimate.invoke(
        {"trip_cost_usd": 1000, "trip_days": 7, "traveler_age": 30, "trip_type": "moon"}))
    assert "error" in output
