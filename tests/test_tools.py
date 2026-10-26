import json

import pytest
from pydantic import ValidationError

import config
from security.validation import InputValidationError
from tools.places import find_accommodations, find_restaurants, search_restaurants
from tools.planning import check_plan, check_constraints, compute_cost
from tools.transport import find_transport, search_flights

# A snapshot plan in Boston (2026 data): Inside Airbnb stays have prices, OpenStreetMap
# restaurants don't, and the flights are estimates without a price.
PLAN = {
    "people": 1,
    "budget": 1400,
    "constraints": {"cuisines": ["Indian"]},
    "days": [
        {"day": 1, "city": "Boston", "transportation": {"mode": "flight", "origin": "Washington",
                                                         "destination": "Boston"},
         "dinner": "India Pavilion", "accommodation": "Shelly's Swan Room"},
        {"day": 2, "city": "Boston", "breakfast": "Picco", "attractions": ["Swan Boats"],
         "accommodation": "#3 Maverick MBTA clean comfy Private room"},
        {"day": 3, "city": "Boston", "transportation": {"mode": "flight", "origin": "Boston",
                                                         "destination": "Washington"},
         "lunch": "India Pavilion", "attractions": ["Nowhere Land"]},
    ],
}


def test_without_live_data_flights_are_estimates_and_drives_are_estimated():
    result = find_transport("Washington", "Myrtle Beach", "2026-11-20")
    assert result["flights_source"] == "estimate" and result["flight_count"] == 0
    assert result["estimated_flight"]["price"] is None and 500 < result["estimated_flight"]["distance_km"] < 700
    car, taxi = result["ground_options"]
    assert (car["mode"], taxi["mode"]) == ("self-driving", "taxi")
    assert car["cost_per_vehicle"] > 0 and taxi["cost_per_vehicle"] is None
    assert "estimated from the distance" in result["note"] and "2022" not in json.dumps(result)


def test_live_drive_between_cities_has_an_id(monkeypatch):
    monkeypatch.setattr(config, "GOOGLE_MAPS_API_KEY", "test-key")
    monkeypatch.setattr("tools.transport.search_live_drive", lambda origin, destination: {
        "id": "drive-1234abcd", "duration": "8h 10m", "distance_km": 760.2, "estimated_cost_per_car_usd": 342.45,
        "cost_text": "~$342.45 per car", "checked_at": "2026-10-26 09:00 UTC"})
    car, taxi = find_transport("Washington", "Myrtle Beach", "2026-11-20")["ground_options"]
    assert car["id"] == taxi["id"] == "drive-1234abcd" and car["source"].startswith("live (Google Routes")
    assert car["cost_per_vehicle"] == 342.45 and taxi["cost_text"] == "No taxi fare data"


@pytest.mark.parametrize("args", [
    {"origin_city": "Atlantis", "destination_city": "Myrtle Beach", "date": "2026-11-20"},
    {"origin_city": "Washington", "destination_city": "Myrtle Beach", "date": "20/11/2026"},
])
def test_bad_flight_input_returns_error_json(args):
    assert "error" in json.loads(search_flights.invoke(args))


def test_restaurant_filters():
    result = find_restaurants("Boston", cuisine="indian")
    assert result["match_count"] >= 3 and result["restaurants_source"] == "snapshot"
    assert all("Indian" in r["cuisines"] for r in result["restaurants"])
    # snapshot restaurants have no prices, so a price limit can't be met
    assert find_restaurants("Boston", cuisine="indian", max_average_cost=50)["match_count"] == 0
    assert "error" in json.loads(search_restaurants.invoke({"city": "Boston", "cuisine": "Klingon"}))


def test_accommodation_prices_and_group_size():
    result = find_accommodations("Boston", people=3, nights=2, max_price_per_night=100)
    assert result["match_count"] >= 1
    for stay in result["accommodations"]:
        assert stay["price_per_night"] <= 100 and stay["minimum_nights"] <= 2
        assert stay["total_cost"] == stay["price_per_night"] * stay["rooms_needed"] * 2


def test_openstreetmap_stays_are_listed_without_prices():
    result = find_accommodations("Myrtle Beach", people=2, nights=2)
    stay = result["accommodations"][0]
    assert stay["price_per_night"].startswith("not in the snapshot") and "total_cost" not in stay
    assert "OpenStreetMap stays have no prices" in result["note"]
    assert find_accommodations("Myrtle Beach", max_price_per_night=200)["match_count"] == 0


def test_house_rules_are_not_published_in_2026_data():
    assert find_accommodations("Boston", must_allow="pets")["match_count"] == 0


def test_accommodation_not_shared_room():
    result = find_accommodations("Boston", room_type="not shared room")
    assert all(stay["room_type"] != "Shared room" for stay in result["accommodations"])
    with pytest.raises(InputValidationError):
        find_accommodations("Boston", room_type="castle")


def test_cost_uses_data_prices_and_leaves_out_unknown_prices():
    cost = compute_cost(PLAN)
    assert cost["totals"] == {"transportation": 0.0, "accommodation": 122.25, "meals": 0.0, "attractions": 0.0}
    assert cost["within_budget"] and not cost["budget_check_complete"]
    unpriced = " ".join(cost["unpriced_items"])
    assert "Flight Washington → Boston" in unpriced and "India Pavilion" in unpriced

    group = {"people": 6, "days": [{"day": 1, "city": "Myrtle Beach", "transportation":
             {"mode": "self-driving", "origin": "Washington", "destination": "Myrtle Beach"}}]}
    line = compute_cost(group)["items"][0]
    assert line["quantity"] == 2 and line["source"] == "estimate"  # two cars for six people
    assert "estimated from the distance" in line["item"]


def test_check_plan_reports_failures():
    result = check_plan(PLAN)
    checks = {c["check"]: c["passed"] for c in result["hard_constraints"] + result["commonsense_checks"]}
    assert checks["budget"] and checks["cuisine"]
    assert not checks["all items found in the data"]  # "Nowhere Land"
    assert not checks["no repeated restaurants"]  # India Pavilion twice
    assert not checks["minimum nights"]  # the Maverick room needs 28 nights
    assert not result["passed"]


def test_invalid_plan_is_rejected_by_schema():
    with pytest.raises(ValidationError):
        check_constraints.invoke({"plan": {"people": 0, "days": []}})
