"""Live stays, using recorded Airbnb and Google Hotels answers for Rome instead of the network."""

import json
from pathlib import Path

import pytest

from backend import config
from backend.live import http, items
from backend.security.validation import InputValidationError
from backend.tools.places import find_accommodations

FIXTURES = Path(__file__).parent / "fixtures"
AIRBNB = json.loads((FIXTURES / "serpapi_airbnb_rome.json").read_text(encoding="utf-8"))
HOTELS = json.loads((FIXTURES / "serpapi_google_hotels_rome.json").read_text(encoding="utf-8"))
DATES = {"check_in_date": "2026-11-10", "check_out_date": "2026-11-14"}


class FakeResponse:
    def __init__(self, status_code=200, payload=None):
        self.status_code, self._payload, self.ok = status_code, payload or {}, status_code < 400

    def json(self):
        return self._payload


@pytest.fixture
def serpapi(monkeypatch):
    monkeypatch.setattr(config, "SERPAPI_API_KEY", "test-key")
    monkeypatch.setattr(http.time, "sleep", lambda _: None)
    monkeypatch.setattr("backend.tools.places.is_live_date", lambda day: True)
    sent = []

    def send(method, url, params, headers, body):
        sent.append(params)
        if params.get("fail"):
            return FakeResponse(503)
        return FakeResponse(200, HOTELS if params["engine"] == "google_hotels" else AIRBNB)
    monkeypatch.setattr(http, "_send", send)
    return sent


def test_live_airbnb_stays_with_totals_and_ids(serpapi):
    result = find_accommodations("Rome", people=2, **DATES)
    assert result["stays_source"].startswith("live (Airbnb via SerpApi") and result["nights"] == 4
    assert serpapi[0]["engine"] == "airbnb" and serpapi[0]["adults"] == 2
    nightly = [s["price_per_night"] for s in result["stays"]]
    assert nightly == sorted(nightly)
    stay = result["stays"][0]
    assert stay["provider"] == "Airbnb" and stay["link"].startswith("https://www.airbnb.com/rooms/")
    assert stay["price_per_night"] == round(stay["total_price"] / 4, 2)
    assert items.lookup(stay["id"])["total_price"] == stay["total_price"]


def test_live_hotels(serpapi):
    result = find_accommodations("Rome", people=2, stay_type="hotel", **DATES)
    assert serpapi[0]["engine"] == "google_hotels" and result["stays"]
    assert all(s["provider"] == "Google Hotels" for s in result["stays"])


@pytest.mark.parametrize("asked, code", [(None, "7"), (3.0, "7"), (4.0, "8"), (4.6, "9")])
def test_hotels_use_relevance_and_a_rating_floor(serpapi, asked, code):
    """No lowest-price sort (it surfaced dorms and capsules), and at least 3.5 stars by default."""
    result = find_accommodations("Rome", people=2, stay_type="hotel", min_rating=asked, **DATES)
    assert "sort_by" not in serpapi[0] and serpapi[0]["rating"] == code
    assert all((s["rating"] or 0) >= max(asked or 0, 3.5) for s in result["stays"])


def test_live_filters_are_passed_on(serpapi):
    find_accommodations("Rome", people=2, room_type="private room", must_allow="pets", max_price_per_night=100, **DATES)
    params = serpapi[0]
    assert params["room_type"] == "private_room" and params["pets"] == 1 and params["max_price"] == 400


def test_house_rules_other_than_pets_are_flagged(serpapi):
    assert "can't be filtered by the 'smoking'" in find_accommodations("Rome", must_allow="smoking", **DATES)["note"]


def test_falls_back_to_snapshot_when_live_fails(serpapi, monkeypatch):
    monkeypatch.setattr("backend.live.stays.search", lambda *a, **k: (_ for _ in ()).throw(http.LiveDataError("down")))
    result = find_accommodations("Rome", people=2, **DATES)
    assert result["stays_source"] == "snapshot" and "Live stay search failed" in result["note"]
    assert result["accommodations"]  # Inside Airbnb snapshot for Rome


def test_past_dates_use_snapshot(serpapi, monkeypatch):
    monkeypatch.setattr("backend.tools.places.is_live_date", lambda day: False)
    result = find_accommodations("Myrtle Beach", people=1, check_in_date="2022-03-13", check_out_date="2022-03-15")
    assert result["stays_source"] == "snapshot" and "in the past" in result["note"] and serpapi == []


@pytest.mark.parametrize("check_in, check_out", [("2026-11-14", "2026-11-10"), ("2026-11-10", "2026-11-10"),
                                                 ("2026-11-10", "2027-01-30")])
def test_bad_stay_dates_are_rejected(serpapi, check_in, check_out):
    with pytest.raises(InputValidationError):
        find_accommodations("Rome", check_in_date=check_in, check_out_date=check_out)


def test_ready_to_show_text(serpapi):
    stay = find_accommodations("Rome", people=2, **DATES)["stays"][0]
    assert stay["per_night_text"].startswith("$") and "." in stay["per_night_text"]
    assert stay["total_text"] == f"${stay['total_price']:,.0f}" and "(" in stay["rating_text"]


def test_free_cancellation_text(serpapi):
    stays = find_accommodations("Rome", people=2, **DATES)["stays"]
    assert {s["cancellation_text"] for s in stays} <= {"Free cancellation", ""}
    assert all((s["cancellation_text"] == "Free cancellation") == s["free_cancellation"] for s in stays)


def test_found_and_shown_counts(serpapi, monkeypatch):
    monkeypatch.setattr("backend.live.stays.MAX_STAYS_SHOWN", 2)
    result = find_accommodations("Rome", people=2, **DATES)
    assert result["stays_shown"] == len(result["stays"]) == 2 < result["stay_count"]
    assert f"Showing the 2 cheapest of {result['stay_count']} stays found." in result["note"]
