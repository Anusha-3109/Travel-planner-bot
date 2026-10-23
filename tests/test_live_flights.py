"""Live flights, using a recorded Google Flights answer (London → Rome) instead of the network."""

import json
from pathlib import Path

import pytest

import config
from live import http, items
from live.airports import airports_for
from live.flights import search_live_flights
from security.validation import InputValidationError
from tools.transport import find_transport

FIXTURE = json.loads((Path(__file__).parent / "fixtures" / "serpapi_google_flights_lon_rom.json").read_text(encoding="utf-8"))
FUTURE = "2026-11-10"


class FakeResponse:
    def __init__(self, status_code=200, payload=None):
        self.status_code, self._payload, self.ok = status_code, payload or {}, status_code < 400

    def json(self):
        return self._payload


@pytest.fixture
def serpapi(monkeypatch):
    """A fake key and a fake SerpApi that records what it was asked."""
    monkeypatch.setattr(config, "SERPAPI_API_KEY", "test-key")
    monkeypatch.setattr(http.time, "sleep", lambda _: None)
    monkeypatch.setattr("live.flights.is_live_date", lambda day: True)
    monkeypatch.setattr("tools.transport.is_live_date", lambda day: True)
    sent = []
    answer = {"response": FakeResponse(200, FIXTURE)}
    monkeypatch.setattr(http, "_send", lambda *args: sent.append(args) or answer["response"])
    return sent, answer


@pytest.mark.parametrize("city, codes", [
    ("London", {"LHR", "LGW"}), ("Hong Kong", {"HKG"}), ("St. Petersburg", {"PIE"}),
    ("Sydney", {"SYD"}), ("Bangalore", {"BLR"}), ("jfk", {"JFK"}),
])
def test_airports_for_cities(city, codes):
    assert codes <= {a.code for a in airports_for(city)}


def test_unknown_city_has_no_airport():
    with pytest.raises(InputValidationError):
        airports_for("Atlantis")


def test_live_flights_are_parsed_sorted_and_remembered(serpapi):
    sent, _ = serpapi
    result = search_live_flights("London", "Rome", FUTURE, passengers=1)
    params = sent[0][2]
    assert params["departure_id"].startswith("LHR") and "FCO" in params["arrival_id"] and params["adults"] == 1
    groups = result["airlines"]
    lowest = [g["from_price_per_person"] for g in groups]
    assert lowest == sorted(lowest) and groups[0]["airline"] == "easyJet" and lowest[0] == 35
    easyjet = groups[0]
    assert easyjet["flight_count"] == len(easyjet["flights"]) == 2
    cheapest = easyjet["flights"][0]
    assert cheapest["from_airport"] == "LGW" and cheapest["departs"] == "06:45" and cheapest["stops"] == 0
    assert items.lookup(cheapest["id"])["price_per_person"] == 35
    assert sum(g["flight_count"] for g in groups) == result["flight_count"]
    assert result["source"] == "live" and "UTC" in result["checked_at"]


def test_search_flights_is_live_first(serpapi):
    result = find_transport("London", "Rome", FUTURE)
    assert result["flights_source"].startswith("live (Google Flights via SerpApi")
    assert result["airlines"][0]["flights"][0]["id"].startswith("flight-")


def test_falls_back_when_live_search_fails(serpapi):
    _, answer = serpapi
    answer["response"] = FakeResponse(503)
    result = find_transport("New York", "Tokyo", FUTURE)
    assert "Live flight search failed" in result["note"]
    assert result["estimated_flight"]["price"] is None


def test_past_dates_and_missing_key_use_snapshot(serpapi, monkeypatch):
    sent, _ = serpapi
    monkeypatch.setattr("tools.transport.is_live_date", lambda day: False)
    result = find_transport("Washington", "Myrtle Beach", "2022-03-13")
    assert result["flights_source"].startswith("snapshot") and "in the past" in result["note"]
    monkeypatch.setattr(config, "SERPAPI_API_KEY", "")
    assert "no SerpApi key" in find_transport("Washington", "Myrtle Beach", "2022-03-13")["note"]
    assert sent == []


def test_live_only_city_works_without_snapshot_data(serpapi):
    """Cities outside the catalog (here Delhi) still get live flights."""
    result = find_transport("London", "Delhi", FUTURE)
    assert result["flights_source"].startswith("live") and result["ground_options"] == []


def test_overnight_arrival_is_marked_next_day(serpapi):
    wizz = next(g for g in search_live_flights("London", "Rome", FUTURE)["airlines"] if g["airline"] == "Wizz Air")
    assert "01:20 (+1 day)" in [f["arrives"] for f in wizz["flights"]]


def test_group_fares_are_split_per_person(serpapi):
    """Google Flights prices cover all passengers; the tool reports per person and the total."""
    sent, _ = serpapi
    cheapest = search_live_flights("London", "Rome", FUTURE, passengers=2)["airlines"][0]["flights"][0]
    assert sent[0][2]["adults"] == 2
    assert cheapest["price_per_person"] == 17.5
    assert items.lookup(cheapest["id"])["total_price"] == 35


def test_price_text_for_one_and_for_groups(serpapi):
    one = search_live_flights("London", "Rome", FUTURE, passengers=1)["airlines"][0]["flights"][0]
    assert one["price_text"] == "$35 per person"
    group = search_live_flights("London", "Rome", FUTURE, passengers=2)["airlines"][0]["flights"][0]
    assert group["price_text"] == "$17.50 per person · $35 total for 2"
