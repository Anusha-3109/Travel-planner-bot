import json

import pytest
from pydantic import ValidationError

from security.validation import InputValidationError
from tools.places import find_accommodations, find_restaurants, search_restaurants
from tools.planning import check_plan, check_constraints, compute_cost
from tools.transport import find_transport, search_flights

PLAN = {
    "people": 1,
    "budget": 1400,
    "constraints": {"cuisines": ["Indian"]},
    "days": [
        {"day": 1, "city": "Myrtle Beach", "transportation": {"mode": "flight", "flight_number": "F3792603"},
         "dinner": "Exotic India", "accommodation": "Cozy Brooklyn Room - Next to Pratt Institute"},
        {"day": 2, "city": "Myrtle Beach", "breakfast": "Catfish Charlie's", "attractions": ["SkyWheel Myrtle Beach"],
         "accommodation": "Cozy Brooklyn Room - Next to Pratt Institute"},
        {"day": 3, "city": "Myrtle Beach", "transportation": {"mode": "flight", "flight_number": "F3791200"},
         "lunch": "Exotic India", "attractions": ["Nowhere Land"]},
    ],
}


def test_flights_cheapest_first_with_ground_options():
    result = find_transport("Washington", "Myrtle Beach", "2022-03-13")
    prices = [f["price_per_person"] for f in result["flights"]]
    assert prices == sorted(prices) and "F3792603" in {f["flight_number"] for f in result["flights"]}
    assert {g["mode"] for g in result["ground_options"]} == {"self-driving", "taxi"}


def test_no_flights_lists_other_dates():
    result = find_transport("Washington", "Myrtle Beach", "2022-03-20")
    assert result["flight_count"] == 0
    assert result["other_dates_with_flights"] == ["2022-03-13"]


@pytest.mark.parametrize("args", [
    {"origin_city": "Atlantis", "destination_city": "Myrtle Beach", "date": "2022-03-13"},
    {"origin_city": "Washington", "destination_city": "Myrtle Beach", "date": "13/03/2022"},
])
def test_bad_flight_input_returns_error_json(args):
    assert "error" in json.loads(search_flights.invoke(args))


def test_restaurant_filters():
    result = find_restaurants("Myrtle Beach", cuisine="indian", max_average_cost=50)
    assert result["match_count"] >= 1
    assert all("Indian" in r["cuisines"] and r["average_cost_per_person"] <= 50 for r in result["restaurants"])
    assert "error" in json.loads(search_restaurants.invoke({"city": "Myrtle Beach", "cuisine": "Klingon"}))


def test_accommodation_house_rule_and_group_size():
    result = find_accommodations("Myrtle Beach", must_allow="pets", people=3, nights=2)
    assert result["match_count"] >= 1
    for stay in result["accommodations"]:
        assert "No pets" not in stay["house_rules"] and stay["minimum_nights"] <= 2
        assert stay["total_cost"] == stay["price_per_night"] * stay["rooms_needed"] * 2


def test_accommodation_not_shared_room():
    result = find_accommodations("Myrtle Beach", room_type="not shared room")
    assert all(stay["room_type"] != "Shared room" for stay in result["accommodations"])
    with pytest.raises(InputValidationError):
        find_accommodations("Myrtle Beach", room_type="castle")


def test_cost_uses_data_prices_and_group_rules():
    cost = compute_cost(PLAN)
    assert cost["totals"] == {"transportation": 251.0, "accommodation": 836.0, "meals": 176.0, "attractions": 0.0}
    assert cost["within_budget"] and cost["remaining_budget"] == 137.0

    group = {"people": 6, "days": [{"day": 1, "city": "Myrtle Beach", "transportation":
             {"mode": "self-driving", "origin": "Washington", "destination": "Myrtle Beach"}}]}
    assert compute_cost(group)["items"][0]["quantity"] == 2  # two cars for six people


def test_check_plan_reports_failures():
    result = check_plan(PLAN)
    checks = {c["check"]: c["passed"] for c in result["hard_constraints"] + result["commonsense_checks"]}
    assert checks["budget"] and checks["cuisine"]
    assert not checks["all items found in the data"]  # "Nowhere Land"
    assert not checks["no repeated restaurants"]  # Exotic India twice
    assert not checks["minimum nights"]  # the room needs 5 nights
    assert not result["passed"]


def test_invalid_plan_is_rejected_by_schema():
    with pytest.raises(ValidationError):
        check_constraints.invoke({"plan": {"people": 0, "days": []}})
