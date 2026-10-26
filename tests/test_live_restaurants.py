"""Live restaurants, using a recorded Google Places answer (Italian restaurants in Rome)."""

import json
from pathlib import Path

import pytest

from backend import config
from backend.live import fx, http, items
from backend.security.validation import InputValidationError
from backend.tools.places import find_restaurants

PLACES = json.loads((Path(__file__).parent / "fixtures" / "google_places_rome_italian.json").read_text(encoding="utf-8"))
RATES = fx.ExchangeRates({"USD": 1.0, "EUR": 0.9}, "2026-10-22", "test rates")


class FakeResponse:
    def __init__(self, status_code=200, payload=None):
        self.status_code, self._payload, self.ok = status_code, payload or {}, status_code < 400

    def json(self):
        return self._payload


@pytest.fixture
def google(monkeypatch):
    monkeypatch.setattr(config, "GOOGLE_MAPS_API_KEY", "test-key")
    monkeypatch.setattr(http.time, "sleep", lambda _: None)
    monkeypatch.setattr("backend.live.restaurants.fx.get_rates", lambda: RATES)
    sent = []
    answer = {"response": FakeResponse(200, PLACES)}

    def send(method, url, params, headers, body):
        sent.append({"headers": headers, "body": body})
        return answer["response"]
    monkeypatch.setattr(http, "_send", send)
    return sent, answer


def test_live_restaurants_with_prices_in_usd(google):
    sent, _ = google
    result = find_restaurants("Rome", cuisine="Italian")
    assert sent[0]["body"]["textQuery"] == "Italian restaurants in Rome"
    assert result["restaurants_source"].startswith("live (Google Places")
    first = result["restaurants"][0]
    assert first["name"] == "Cantina e Cucina" and first["rating"] == 4.7 and first["reviews"] == 18050
    assert first["price_range_local"] == "EUR 20–30" and first["price_range_usd"] == "$22–33"
    assert first["estimated_cost_per_person_usd"] == 27.77
    assert first["maps_link"].startswith("https://maps.google.com/") and first["open_now"] is True
    assert items.lookup(first["id"])["estimated_cost_per_person_usd"] == 27.77


def test_restaurant_without_a_price_range_is_kept_without_cost(google):
    rooftop = next(r for r in find_restaurants("Rome")["restaurants"] if r["name"].startswith("Ambrosia"))
    assert rooftop["price_range_local"] is None and rooftop["estimated_cost_per_person_usd"] is None


def test_cost_and_rating_filters(google):
    sent, _ = google
    result = find_restaurants("Rome", max_average_cost=20, min_rating=4.5)
    assert sent[0]["body"]["minRating"] == 4.5
    assert result["restaurants"] and all(r["estimated_cost_per_person_usd"] <= 20 for r in result["restaurants"])


def test_key_is_sent_in_a_header_and_never_cached(google):
    sent, _ = google
    find_restaurants("Rome")
    assert sent[0]["headers"]["X-Goog-Api-Key"] == "test-key"
    assert b"test-key" not in config.CACHE_DB.read_bytes()


def test_falls_back_to_snapshot_when_google_fails(google):
    _, answer = google
    answer["response"] = FakeResponse(403)
    result = find_restaurants("Rome")
    assert result["restaurants_source"] == "snapshot" and "Live restaurant search failed" in result["note"]
    assert result["restaurants"]  # OpenStreetMap snapshot for Rome


def test_bad_cuisine_text_is_rejected(google):
    with pytest.raises(InputValidationError):
        find_restaurants("Rome", cuisine="pizza; DROP TABLE")


def test_ready_to_show_text(google):
    first = find_restaurants("Rome", cuisine="Italian")["restaurants"][0]
    assert first["rating_text"] == "4.7 (18,050)" and first["price_text"] == "EUR 20–30 (~$22–33)"
