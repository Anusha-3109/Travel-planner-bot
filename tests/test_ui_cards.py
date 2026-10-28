"""Result cards drawn from tool results, checked with Streamlit's test runner."""

import json
from datetime import date

from streamlit.testing.v1 import AppTest

from backend.agent import agent as agent_module


def _cards(tool_calls: list[dict]):
    def script(calls):
        from frontend.components.cards import render_result_cards
        render_result_cards(calls)

    at = AppTest.from_function(script, args=(tool_calls,), default_timeout=30)
    at.run()
    assert not at.exception
    return at


def _call(name: str, output: dict | str) -> dict:
    return {"name": name, "args": {}, "output": output if isinstance(output, str) else json.dumps(output)}


def _text(at) -> str:
    return "\n".join(m.value for m in at.markdown) + "\n" + "\n".join(c.value for c in at.caption)


FLIGHTS = {
    "route": "London → Rome", "date": "2026-11-06", "passengers": 2,
    "flights_source": "live (Google Flights via SerpApi, checked 2026-10-23 10:00 UTC)",
    "airlines": [
        {"airline": "easyJet", "flight_count": 4, "from_price_per_person": 35, "flights": [
            {"id": f"flight-{n}", "flight_numbers": [f"U2 {8320 + n}"], "from_airport": "LGW", "to_airport": "FCO",
             "departs": f"0{6 + n}:45", "arrives": f"1{n}:20", "duration": "2h 35m", "stops": 0, "layovers": [],
             "price_per_person": 35 + n, "price_text": f"${35 + n} per person · ${70 + 2 * n} total for 2"}
            for n in range(4)]},
        {"airline": "ITA", "flight_count": 1, "from_price_per_person": 90, "flights": [
            {"id": "flight-9", "flight_numbers": ["AZ 201"], "from_airport": "LHR", "to_airport": "FCO",
             "departs": "09:10", "arrives": "12:40", "duration": "3h 30m", "stops": 1, "layovers": ["MXP"],
             "price_per_person": 90, "price_text": "$90 per person · $180 total for 2"}]},
    ],
}
STAYS = {
    "city": "Rome", "check_in": "2026-11-06", "check_out": "2026-11-10", "nights": 4, "guests": 2,
    "stays_source": "live (Airbnb via SerpApi, checked 2026-10-23 10:00 UTC)",
    "stays": [{"id": "stay-1", "provider": "Airbnb", "name": "Flat near Trevi", "kind": "Apartment in Trevi",
               "per_night_text": "$120.00", "total_text": "$480", "rating_text": "4.9 (210)",
               "cancellation_text": "Free cancellation", "link": "https://www.airbnb.com/rooms/1"}],
}
RESTAURANTS = {
    "city": "Rome", "restaurants_source": "live (Google Places, checked 2026-10-23 10:00 UTC)",
    "filters": {"cuisine": "Italian"},
    "restaurants": [{"id": "restaurant-1", "name": "Da Enzo", "address": "Via dei Vascellari 29",
                     "rating_text": "4.6 (8,120)", "price_text": "EUR 20–30 (~$22–33)", "open_now": True,
                     "maps_link": "https://maps.google.com/?cid=1"}],
}
TRANSPORT = {
    "transport_source": "live (Google Routes, checked 2026-10-23 10:00 UTC)", "from": "FCO airport, Rome",
    "to": "Trevi Fountain, Rome",
    "public_transport": [{"id": "transit-1", "summary": "Train FL1 → Metro A", "duration": "52 min", "transfers": 1,
                          "fare_text": "EUR 8.00 (~$8.80)", "steps": ["Walk 4 min", "Train FL1 to Tuscolana"]}],
    "driving": {"id": "drive-1", "duration": "38 min", "distance_km": 31.2,
                "cost_text": "No driving cost data outside the US"},
}
COST = {
    "people": 2, "currency": "USD", "total_text": "USD 1,210.00", "budget": 1500, "budget_text": "USD 1,500.00",
    "remaining_budget": 290, "remaining_text": "USD 290.00",
    "totals_text": {"transportation": "USD 70.00", "accommodation": "USD 480.00", "meals": "USD 660.00",
                    "attractions": "USD 0.00"},
    "items": [{"day": 1, "item": "Flight U2 8320, London → Rome", "cost_text": "USD 70.00"}],
    "unpriced_items": ["day 1: Public transport Train FL1 → Metro A (fare not published)"],
}


def test_flights_are_grouped_by_airline_with_tool_prices():
    at = _cards([_call("search_flights", FLIGHTS)])
    text = _text(at)
    assert "**easyJet**" in text and "**ITA**" in text
    assert r"\$35 per person · \$70 total for 2" in text  # escaped, so "$" isn't read as LaTeX
    assert "1 stop via MXP" in text and "Nonstop" in text
    assert [p.proto.popover.label for p in at.get("popover")] == ["1 more"]  # the fourth easyJet flight


def test_stay_card_has_prices_rating_and_booking_link():
    at = _cards([_call("search_accommodations", STAYS)])
    text = _text(at)
    assert "**Flat near Trevi**" in text and r"**\$480 total**" in text and "4.9 (210)" in text
    links = at.get("link_button")
    assert len(links) == 1 and links[0].proto.label == "View on Airbnb"
    assert links[0].proto.url == "https://www.airbnb.com/rooms/1"


def test_restaurant_card_shows_open_now_and_map():
    at = _cards([_call("search_restaurants", RESTAURANTS)])
    text = _text(at)
    assert "**Da Enzo**" in text and "EUR 20–30" in text and "Open now" in text
    assert at.get("link_button")[0].proto.label == "Map"


def test_transport_cards_show_transit_and_driving():
    at = _cards([_call("get_local_transport", TRANSPORT)])
    text = _text(at)
    assert "**Train FL1 → Metro A**" in text and "52 min · 1 change(s)" in text
    assert "**By car or taxi**" in text and "No driving cost data outside the US" in text


def test_plan_shows_cost_card_first_and_options_collapsed():
    checks = {"hard_constraints": [{"check": "Budget", "passed": True, "detail": "ok"}],
              "commonsense_checks": [{"check": "Meals", "passed": False, "detail": "Day 2 has no dinner."}]}
    at = _cards([_call("search_flights", FLIGHTS), _call("search_accommodations", STAYS),
                 _call("calculate_trip_cost", COST), _call("check_constraints", checks)])
    metrics = {m.label: m.value for m in at.metric}
    assert metrics == {"Total": "USD 1,210.00", "Budget": "USD 1,500.00", "Left": "USD 290.00"}
    assert [e.label for e in at.expander] == ["Cost breakdown", "Options found (2 searches)"]
    assert "1 item(s) have no price data" in at.warning[0].value
    assert "Day 2 has no dinner." in _text(at)


def test_errors_bad_output_and_repeats_are_skipped():
    at = _cards([_call("search_flights", {"error": "Unknown city"}), _call("search_restaurants", "not json"),
                 _call("search_accommodations", STAYS), _call("search_accommodations", STAYS),
                 _call("search_destination_options", {"places": []})])
    assert len(at.get("link_button")) == 1  # one stay card, shown once
    assert "Flights" not in _text(at)


def test_snapshot_stays_and_estimates_get_cards_too():
    snapshot_stays = {"city": "Myrtle Beach", "stays_source": "snapshot", "accommodations": [
        {"name": "Beach house", "room_type": "Entire home/apt", "price_per_night": 150, "maximum_occupancy": 4,
         "minimum_nights": 1, "rating": 4.5, "total_cost": 300},
        {"name": "Waikiki Village", "room_type": "Private room",
         "price_per_night": "not in the snapshot (search live)", "maximum_occupancy": "not published",
         "minimum_nights": 1, "rating": "not available"}]}
    estimated = {"route": "Washington → Myrtle Beach", "date": "2026-11-13", "flights_source": "estimate",
                 "flight_count": 0,
                 "estimated_flight": {"distance_km": 602, "estimated_nonstop_duration": "1h 25m", "price": None},
                 "ground_options": [{"mode": "self-driving", "duration": "9h 25m", "distance_km": 751.9,
                                     "cost_per_vehicle": 338.73, "source": "estimate"},
                                    {"mode": "taxi", "duration": "9h 25m", "distance_km": 751.9,
                                     "cost_per_vehicle": None, "source": "estimate"}]}
    text = _text(_cards([_call("search_accommodations", snapshot_stays), _call("search_flights", estimated)]))
    assert "**Beach house**" in text and r"**\$300 total**" in text
    assert "No price in the snapshot" in text and "up to 4 guests" in text
    assert "**Estimated nonstop flight**" in text and "About 1h 25m" in text and "Estimate" in text
    assert r"\$338.73 per vehicle" in text and "No fare data" in text


def test_cards_rule_is_only_in_the_app_prompt():
    assert agent_module.CARDS_RULE in agent_module.system_prompt(date(2026, 10, 23), cards=True)
    assert agent_module.CARDS_RULE not in agent_module.system_prompt(date(2026, 10, 23))


def test_headings_show_found_and_shown_counts_and_the_travel_day():
    stays = {**STAYS, "stay_count": 11, "stays_shown": 10}
    transport = {**TRANSPORT, "departure_time": "Fri 06 Nov 2026, 14:30 local time",
                 "timetable_note": "Times are for Fri 06 Nov 2026, leaving from 14:30."}
    text = _text(_cards([_call("search_accommodations", stays), _call("get_local_transport", transport)]))
    assert "· 10 of 11 shown" in text
    assert "Fri 06 Nov 2026, 14:30 local time" in text and "leaving from 14:30" in text


PLAN = {"people": 2, "stay": "stay-1", "days": [{"day": 1, "city": "Rome"}, {"day": 2, "city": "Rome"}]}
OTHER_STAY = {**STAYS, "stays": [*STAYS["stays"], {**STAYS["stays"][0], "id": "stay-2", "name": "Casa Monti"}]}


def _cards_with_actions(tool_calls: list[dict], plan: dict | None):
    def script(calls, plan):
        import streamlit as st

        from frontend.components.cards import render_result_cards
        render_result_cards(calls, key="cards-1", plan=plan)
        st.write(f"pending: {st.session_state.get('pending_question')}")

    at = AppTest.from_function(script, args=(tool_calls, plan), default_timeout=30)
    at.run()
    assert not at.exception
    return at


def test_follow_ups_name_the_option_by_its_id_and_what_to_do():
    from frontend.components.cards import follow_up
    flight = FLIGHTS["airlines"][1]["flights"][0]
    assert follow_up("flight", flight, FLIGHTS, PLAN) == ("Use flight AZ 201 (flight-9) for the London → Rome flight on "
                                                          "2026-11-06 and update the plan and its cost.")
    assert follow_up("flight", flight, FLIGHTS, None).startswith("Plan a trip with flight AZ 201 (flight-9)")
    stay = OTHER_STAY["stays"][1]
    assert follow_up("stay", stay, STAYS, PLAN) == ("Use the stay Casa Monti (stay-2) for every night instead of the "
                                                    "current stay, and update the plan and its cost.")
    assert follow_up("restaurant", RESTAURANTS["restaurants"][0], RESTAURANTS, PLAN, 2, "lunch") == (
        "Use Da Enzo (restaurant-1) for lunch on day 2 and update the plan and its cost.")
    long_name = {**stay, "name": "Casa " + "x" * 200}
    assert len(follow_up("stay", long_name, STAYS, PLAN)) < 200  # names from outside services are cut


def test_cards_take_the_next_step_from_a_plan():
    at = _cards_with_actions([_call("search_accommodations", OTHER_STAY), _call("search_flights", FLIGHTS)], PLAN)
    labels = [b.label for b in at.button]
    assert labels.count("In the plan") == 1 and labels.count("Use this stay") == 1  # the plan's stay can't be picked
    assert labels.count("Use this flight") == 5  # all 4 easyJet (one in the "1 more" pop-up) and the ITA flight
    next(b for b in at.button if b.label == "Use this stay").click().run()
    assert "pending: Use the stay Casa Monti (stay-2)" in at.markdown[-1].value


def test_a_restaurant_is_added_at_the_chosen_day_and_meal():
    at = _cards_with_actions([_call("search_restaurants", RESTAURANTS)], PLAN)
    at.selectbox[0].select(2)
    at.selectbox[1].select("lunch")
    next(b for b in at.button if b.label == "Add").click().run()
    assert "pending: Use Da Enzo (restaurant-1) for lunch on day 2" in at.markdown[-1].value


def test_without_a_plan_the_cards_start_one_and_restaurants_wait():
    at = _cards_with_actions([_call("search_accommodations", STAYS), _call("search_restaurants", RESTAURANTS)], None)
    assert [b.label for b in at.button] == ["Plan with this stay"] and not at.selectbox
    plain = _cards([_call("search_accommodations", STAYS)])  # an answer still being drawn: no buttons
    assert not plain.button
