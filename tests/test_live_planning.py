"""Trip costs and checks with live items, which are stored by id like the live tools do."""

import pytest

from live import fx, items
from tools.planning import check_plan, compute_cost

RATES = fx.ExchangeRates({"USD": 1.0, "EUR": 0.9}, "2026-10-22", "test rates")
CHECKED = "2026-10-22 14:00 UTC"


@pytest.fixture
def live_ids(monkeypatch):
    """A London → Rome trip for 2 people: two flights, a 3-night stay, two meals and a transit route."""
    monkeypatch.setattr("tools.planning.fx.get_rates", lambda: RATES)
    out = items.remember("flight", {"type": "flight", "origin_city": "London", "destination_city": "Rome",
                                    "flight_numbers": ["U2 8323"], "price_per_person": 35, "checked_at": CHECKED})
    back = items.remember("flight", {"type": "flight", "origin_city": "Rome", "destination_city": "London",
                                     "flight_numbers": ["U2 8324"], "price_per_person": 60, "checked_at": CHECKED})
    stay = items.remember("stay", {"type": "stay", "name": "Rifugio San Pietro", "city": "Rome",
                                   "kind": "Apartment in Aurelio", "price_per_night": 99.75, "guests": 2,
                                   "checked_at": CHECKED})
    dinner = items.remember("restaurant", {"type": "restaurant", "name": "Cantina e Cucina", "city": "Rome",
                                           "cuisine": "Italian", "estimated_cost_per_person_usd": 27.77,
                                           "checked_at": CHECKED})
    lunch = items.remember("restaurant", {"type": "restaurant", "name": "Ambrosia", "city": "Rome",
                                          "estimated_cost_per_person_usd": None, "checked_at": CHECKED})
    train = items.remember("transit", {"type": "transit", "summary": "Train RV → Metro B", "origin": "Fiumicino Airport",
                                       "destination": "Colosseum", "fare_per_person_usd": None, "checked_at": CHECKED})
    return {"out": out, "back": back, "stay": stay, "dinner": dinner, "lunch": lunch, "train": train}


def _plan(ids, **extra):
    return {"people": 2, "budget": 1000, "days": [
        {"day": 1, "city": "Rome", "transportation": {"mode": "flight", "item_id": ids["out"]},
         "dinner": ids["dinner"], "accommodation": ids["stay"]},
        {"day": 2, "city": "Rome", "transportation": {"mode": "transit", "item_id": ids["train"]},
         "lunch": ids["lunch"], "accommodation": ids["stay"]},
        {"day": 3, "city": "Rome", "accommodation": ids["stay"]},
        {"day": 4, "city": "Rome", "transportation": {"mode": "flight", "item_id": ids["back"]}},
    ], **extra}


def test_live_items_are_costed_from_their_stored_prices(live_ids):
    cost = compute_cost(_plan(live_ids))
    assert cost["totals"] == {"transportation": 190.0, "accommodation": 299.25, "meals": 55.54, "attractions": 0.0}
    assert cost["total_cost"] == 544.79 and cost["within_budget"] and cost["remaining_budget"] == 455.21
    assert all(line["source"] == f"live (checked {CHECKED})" for line in cost["items"])
    meal = next(line for line in cost["items"] if line["type"] == "meals")
    assert meal["estimate"] and meal["quantity"] == 2


def test_missing_prices_are_listed_not_guessed(live_ids):
    cost = compute_cost(_plan(live_ids))
    assert len(cost["unpriced_items"]) == 2 and not cost["budget_check_complete"]
    assert any("fare not published" in item for item in cost["unpriced_items"])
    assert any("price not listed" in item for item in cost["unpriced_items"])


def test_totals_in_another_currency(live_ids):
    cost = compute_cost(_plan(live_ids, currency="eur", budget=900))
    assert cost["currency"] == "EUR" and cost["total_cost_usd"] == 544.79
    assert cost["total_cost"] == round(544.79 * 0.9, 2) and cost["remaining_budget"] == round(900 - 544.79 * 0.9, 2)
    assert "test rates" in cost["note"]


def test_unknown_or_expired_ids_are_reported(live_ids):
    plan = _plan(live_ids)
    plan["days"][0]["accommodation"] = "stay-00000000"
    cost = compute_cost(plan)
    assert any("unknown or expired id" in item for item in cost["unknown_items"])


def test_checks_for_live_stays(live_ids):
    result = check_plan(_plan(live_ids, constraints={"room_type": "entire room", "house_rule": "pets"}))
    hard = {c["check"]: c for c in result["hard_constraints"]}
    assert hard["room type"]["passed"]  # an apartment is an entire place
    assert not hard["house rule"]["passed"] and "not published" in hard["house rule"]["detail"]
    assert "no price data" in hard["budget"]["detail"]

    big_group = check_plan(_plan(live_ids, people=4))
    fits = next(c for c in big_group["commonsense_checks"] if c["check"] == "stays fit the group")
    assert not fits["passed"] and "searched for 2" in fits["detail"]


def test_live_items_found_by_name(live_ids):
    """Models often write the name instead of the id; the live price must still be used."""
    plan = _plan(live_ids)
    plan["days"][0]["dinner"] = "Cantina e Cucina, Rome"
    plan["days"][0]["accommodation"] = "Rifugio San Pietro"
    plan["days"][1]["accommodation"] = plan["days"][2]["accommodation"] = "Rifugio San Pietro"
    plan["days"][3]["transportation"] = {"mode": "flight", "flight_number": "U2 8324"}
    cost = compute_cost(plan)
    assert cost["unknown_items"] == []
    assert cost["totals"]["accommodation"] == 299.25 and cost["totals"]["transportation"] == 190.0


def test_ready_made_money_text(live_ids):
    cost = compute_cost(_plan(live_ids, currency="EUR", budget=900))
    assert cost["total_text"] == f"EUR {cost['total_cost']:,.2f}" and cost["budget_text"] == "EUR 900.00"
    assert all(line["cost_text"].startswith("EUR ") for line in cost["items"])


def test_plan_level_stay_covers_every_night_but_the_last(live_ids):
    plan = _plan(live_ids, stay=live_ids["stay"])
    for day in plan["days"]:
        day.pop("accommodation", None)
    cost = compute_cost(plan)
    assert cost["totals"]["accommodation"] == 299.25  # 3 nights: days 1-3, not the departure day


def test_citation_prefixes_are_ignored(live_ids):
    plan = _plan(live_ids)
    plan["days"][0]["dinner"] = "restaurant: Cantina e Cucina, Rome"
    assert compute_cost(plan)["unknown_items"] == []


def test_live_drive_is_costed_per_car(live_ids):
    """A live US drive costs per car (5 seats); a taxi on the same route has no fare data."""
    drive = items.remember("drive", {"type": "drive", "origin": "Washington", "destination": "Myrtle Beach",
                                     "distance_km": 690.0, "cost_per_car_usd": 310.82, "checked_at": CHECKED})
    plan = {"people": 6, "days": [{"day": 1, "city": "Myrtle Beach",
                                   "transportation": {"mode": "self-driving", "item_id": drive}}]}
    line = compute_cost(plan)["items"][0]
    assert line["quantity"] == 2 and line["cost_usd"] == 621.64  # two cars for six people
    assert "IRS" in line["estimate"] and line["source"] == f"live (checked {CHECKED})"

    plan["days"][0]["transportation"]["mode"] = "taxi"
    assert any("no fare data" in item for item in compute_cost(plan)["unpriced_items"])


def test_airport_transfer_is_costed_next_to_the_flight(live_ids):
    """Day 1 has a flight and an airport transfer; both count in the total."""
    paid_train = items.remember("transit", {"type": "transit", "summary": "Bus A2 → Train S2", "origin": "BCN Airport",
                                            "destination": "Stay", "fare_per_person_usd": 11.95, "checked_at": CHECKED})
    taxi = items.remember("drive", {"type": "drive", "origin": "Stay", "destination": "BCN Airport",
                                    "distance_km": 15.0, "cost_per_car_usd": 6.76, "checked_at": CHECKED})
    plan = _plan(live_ids)
    plan["days"][0]["local_transport"] = [{"mode": "transit", "item_id": paid_train}]
    plan["days"][3]["local_transport"] = [{"mode": "taxi", "item_id": taxi}]
    cost = compute_cost(plan)
    transfer = next(line for line in cost["items"] if "Bus A2" in line["item"])
    assert transfer["day"] == 1 and transfer["cost_usd"] == 23.9  # 2 people x $11.95
    assert cost["totals"]["transportation"] == 190.0 + 23.9
    assert any("Taxi, Stay → BCN Airport (no fare data)" in item for item in cost["unpriced_items"])


def test_unknown_local_trip_is_reported(live_ids):
    plan = _plan(live_ids)
    plan["days"][0]["local_transport"] = [{"mode": "transit", "item_id": "transit-00000000"}]
    assert any("transit id 'transit-00000000'" in item for item in compute_cost(plan)["unknown_items"])
