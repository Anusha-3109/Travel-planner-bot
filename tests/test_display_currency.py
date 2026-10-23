"""Listing prices in the user's chosen currency (the app's currency picker)."""

import json
from pathlib import Path

import pytest

import config
from live import fx, http
from live.fx import money, money_range, use_display_currency
from tools.places import find_restaurants

RATES = fx.ExchangeRates({"USD": 1.0, "EUR": 0.9, "GBP": 0.8, "JPY": 150.0}, "2026-10-23", "test rates")
PLACES = json.loads((Path(__file__).parent / "fixtures" / "google_places_rome_italian.json").read_text(encoding="utf-8"))


@pytest.fixture(autouse=True)
def rates(monkeypatch):
    monkeypatch.setattr(fx, "get_rates", lambda: RATES)


def test_usd_text_is_unchanged_by_default():
    assert (money(35), money(17.5), money(13.47, approx=True), money_range(22.2, 33.3)) == \
        ("$35", "$17.50", "~$13.47", "$22–33")


def test_amounts_follow_the_chosen_currency():
    with use_display_currency("eur"):
        assert money(100) == "EUR 90.00" and money(100, whole=True) == "EUR 90"
        assert money(13.47, approx=True) == "~EUR 12.12" and money_range(20, 40) == "EUR 18–36"
        assert money_range(50, None) == "EUR 45+"
    assert money(100) == "$100"  # back to USD after the answer


def test_unknown_currency_falls_back_to_usd():
    with use_display_currency("XYZ"):
        assert money(10) == "$10"


def test_restaurant_prices_show_local_and_chosen_currency(monkeypatch):
    monkeypatch.setattr(config, "GOOGLE_MAPS_API_KEY", "test-key")

    class Answer:
        status_code, ok = 200, True

        def json(self):
            return PLACES
    monkeypatch.setattr(http, "_send", lambda *a: Answer())
    with use_display_currency("GBP"):
        first = find_restaurants("Rome", cuisine="Italian")["restaurants"][0]
    assert first["price_text"] == "EUR 20–30 (~GBP 18–27)" and "_range_usd" not in first
    with use_display_currency("EUR"):  # already in the local currency: no conversion shown
        assert find_restaurants("Rome", cuisine="Italian")["restaurants"][0]["price_text"] == "EUR 20–30"


def test_agent_sets_the_currency_while_it_answers(monkeypatch):
    import agent.agent as agent_module
    seen = []
    monkeypatch.setattr(agent_module, "_run_agent", lambda *a: seen.append(fx.display_currency()))
    agent_module.run_agent("Hello", currency="JPY")
    assert seen == ["JPY"] and fx.display_currency() == "USD"
