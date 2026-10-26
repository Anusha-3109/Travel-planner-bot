"""Saved trips: building one from a chat's costed plan, saving it, and the trip pages."""

import json

from streamlit.testing.v1 import AppTest

import history
import trips


def _call(name, output, args=None):
    return {"name": name, "args": args or {}, "output": json.dumps(output)}


FLIGHTS_OUT = _call("search_flights", {"route": "Washington → Boston", "date": "2026-11-16", "airlines": [
    {"airline": "JetBlue", "flights": [{"id": "flight-out", "flight_numbers": ["B6 1234"], "from_airport": "DCA",
                                        "to_airport": "BOS", "departs": "07:10", "arrives": "08:40",
                                        "duration": "1h 30m", "price_text": "$89 per person"}]}]})
FLIGHTS_BACK = _call("search_flights", {"route": "Boston → Washington", "date": "2026-11-18", "airlines": [
    {"airline": "JetBlue", "flights": [{"id": "flight-back", "flight_numbers": ["B6 1235"], "from_airport": "BOS",
                                        "to_airport": "DCA", "departs": "18:00", "arrives": "19:35",
                                        "duration": "1h 35m", "price_text": "$95 per person"}]}]})
STAYS = _call("search_accommodations", {"check_in": "2026-11-16", "check_out": "2026-11-18", "stays": [
    {"id": "stay-1", "name": "Shelly's Swan Room", "kind": "Room in Back Bay", "per_night_text": "$75.00",
     "total_text": "$150", "rating_text": "4.85 (120)", "link": "https://www.airbnb.com/rooms/1"},
    {"id": "stay-2", "name": "The Jazzy Airbnb", "kind": "Room in Roxbury", "per_night_text": "$81.00",
     "total_text": "$162", "link": "https://www.airbnb.com/rooms/2"}]})
RESTAURANTS = _call("search_restaurants", {"restaurants": [
    {"id": "restaurant-1", "name": "India Pavilion", "rating_text": "4.4 (900)", "price_text": "$20–30",
     "maps_link": "https://maps.google.com/?cid=1", "address": "17 Central Sq"}]})
TRANSFER = _call("get_local_transport", {"from": "BOS airport", "to": "Back Bay", "public_transport": [
    {"id": "transit-1", "summary": "Bus SL1 → Subway Red", "origin": "BOS airport", "destination": "Back Bay",
     "duration": "35 min", "fare_text": "USD 2.40", "steps": ["Bus SL1 to South Station", "Walk 5 min"]}]})
PLAN = {"people": 1, "budget": 900, "currency": "USD", "stay": "stay-1", "days": [
    {"day": 1, "city": "Boston", "transportation": {"mode": "flight", "item_id": "flight-out"},
     "local_transport": [{"mode": "transit", "item_id": "transit-1"}], "dinner": "restaurant-1",
     "attractions": ["Museum of Science"]},
    {"day": 2, "city": "Boston", "attractions": ["Swan Boats"]},
    {"day": 3, "city": "Boston", "transportation": {"mode": "flight", "item_id": "flight-back"}}]}
COST = _call("calculate_trip_cost", {"currency": "USD", "total_text": "USD 336.40", "budget_text": "USD 900.00",
                                     "remaining_text": "USD 563.60", "within_budget": True, "totals_text": {},
                                     "unpriced_items": ["day 1: Dinner: India Pavilion (price not listed)"]},
             {"plan": PLAN})
CHECKS = _call("check_constraints", {"passed": False, "hard_constraints": [],
                                     "commonsense_checks": [{"check": "minimum nights", "passed": False,
                                                             "detail": "Needs 3 nights."}]}, {"plan": PLAN})
MESSAGES = [
    {"role": "user", "content": "Find flights and a stay"},
    {"role": "assistant", "content": "Here are options", "tool_calls": [FLIGHTS_OUT, FLIGHTS_BACK, STAYS]},
    {"role": "user", "content": "Plan it"},
    {"role": "assistant", "content": "The plan", "tool_calls": [RESTAURANTS, TRANSFER, COST, CHECKS]},
]


def test_a_trip_is_built_from_tool_results_only():
    trip = trips.build_trip(MESSAGES, 3)
    assert trip["title"] == "Boston, 2 nights" and (trip["origin"], trip["destination"]) == ("Washington", "Boston")
    assert (trip["start"], trip["end"], trip["people"]) == ("2026-11-16", "2026-11-18", 1)
    assert trip["cost"]["total_text"] == "USD 336.40" and trip["cost"]["remaining_text"] == "USD 563.60"
    assert trip["checks"] == {"passed": False, "failed": [{"check": "minimum nights", "passed": False,
                                                          "detail": "Needs 3 nights."}]}
    day1 = trip["days"][0]
    assert day1["date"] == "2026-11-16" and [i["kind"] for i in day1["items"]] == [
        "flight", "transit", "meal", "attraction", "stay"]
    flight, transit, meal, sight, stay = day1["items"]
    assert flight["title"] == "JetBlue B6 1234" and "DCA → BOS · 07:10 → 08:40" in flight["detail"]
    assert transit["steps"] == ["Bus SL1 to South Station", "Walk 5 min"] and transit["price"] == "USD 2.40"
    assert meal["title"] == "Dinner: India Pavilion" and meal["link"] == "https://maps.google.com/?cid=1"
    assert stay["title"] == "Shelly's Swan Room" and stay["price"] == "$75.00 / night"
    assert stay["detail"] == "Room in Back Bay"  # the listing's own type, not the record type
    assert day1["unpriced"] == ["Dinner: India Pavilion (price not listed)"]
    assert [i["kind"] for i in trip["days"][2]["items"]] == ["flight"]  # no stay on the last day


def test_stays_and_map_points():
    trip = trips.build_trip(MESSAGES, 3)
    assert [(s["name"], s["chosen"]) for s in trip["stays"]] == [("Shelly's Swan Room", True),
                                                                 ("The Jazzy Airbnb", False)]
    kinds = {p["kind"] for p in trip["points"]}
    assert {"origin", "destination"} <= kinds
    assert all(-90 <= p["lat"] <= 90 for p in trip["points"])


def test_messages_without_a_costed_plan_make_no_trip():
    assert trips.build_trip(MESSAGES, 1) is None
    assert trips.find_plan([]) is None


def test_trips_are_saved_listed_and_deleted():
    trip_id = history.save_trip(trips.build_trip(MESSAGES, 3), "chat-1")
    (saved,) = history.list_trips()
    assert saved["id"] == trip_id and saved["chat_id"] == "chat-1" and history.load_trip(trip_id)["title"]
    history.delete_trip(trip_id)
    assert history.list_trips() == [] and history.load_trip(trip_id) is None


def _page(name):
    from ui import trips_pages
    getattr(trips_pages, name)()


def _app(name):
    return AppTest.from_function(_page, args=(name,), default_timeout=30)


def test_my_trips_lists_saved_trips():
    at = _app("my_trips")
    at.run()
    assert "No trips yet" in at.info[0].value
    history.save_trip(trips.build_trip(MESSAGES, 3))
    at.run()
    assert "**Boston, 2 nights**" in [m.value for m in at.markdown] and not at.exception


def test_trip_page_shows_the_plan_stays_and_discover(monkeypatch):
    trip_id = history.save_trip(trips.build_trip(MESSAGES, 3))
    at = _app("trip_page")
    at.query_params["trip"] = trip_id
    at.run()
    assert not at.exception and [t.label for t in at.tabs] == ["Plan", "Route", "Stays", "Discover"]
    metrics = {m.label: m.value for m in at.metric}
    assert metrics["Total"] == "USD 336.40" and metrics["Left"] == "USD 563.60"
    text = " ".join(m.value for m in at.markdown)
    assert "JetBlue B6 1234" in text and "Shelly's Swan Room" in text
    assert "minimum nights: Needs 3 nights." in at.warning[0].value


def test_unknown_trip_says_so():
    at = _app("trip_page")
    at.query_params["trip"] = "missing"
    at.run()
    assert at.title[0].value == "Trip not found"
