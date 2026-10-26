"""Exchange rates, with both sources mocked."""

import pytest

from backend import config
from backend.live import fx, http
from backend.live.budget import SessionBudget, use_budget
from backend.security.validation import InputValidationError

PRIMARY_ANSWER = {"result": "success", "base_code": "USD", "time_last_update_unix": 1792627351,
                  "rates": {"USD": 1, "EUR": 0.9, "INR": 84.0, "JPY": 150.0}}
ECB_XML = b"""<gesmes:Envelope xmlns:gesmes="http://www.gesmes.org/xml/2002-08-01"
 xmlns="http://www.ecb.int/vocabulary/2002-08-01/eurofxref"><Cube><Cube time="2026-10-21">
 <Cube currency="USD" rate="1.25"/><Cube currency="JPY" rate="175"/></Cube></Cube></gesmes:Envelope>"""


class FakeResponse:
    def __init__(self, status_code=200, payload=None, content=b""):
        self.status_code, self._payload, self.content = status_code, payload, content
        self.ok = status_code < 400

    def json(self):
        return self._payload

    def raise_for_status(self):
        if not self.ok:
            raise fx.requests.HTTPError(f"HTTP {self.status_code}")


@pytest.fixture(autouse=True)
def isolated(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "CACHE_DB", tmp_path / "backend.live.sqlite3")
    monkeypatch.setattr(http.time, "sleep", lambda _: None)


def test_primary_rates_convert_between_any_currencies(monkeypatch):
    monkeypatch.setattr(http, "_send", lambda *a: FakeResponse(200, PRIMARY_ANSWER))
    rates = fx.get_rates()
    assert rates.updated == "2026-10-22" and "exchangerate-api.com" in rates.note()
    assert rates.convert(100, "usd", "INR") == 8400.0
    assert rates.convert(90, "EUR", "USD") == 100.0
    assert rates.convert(150, "JPY", "EUR") == 0.9


def test_falls_back_to_ecb_when_primary_fails(monkeypatch):
    monkeypatch.setattr(http, "_send", lambda *a: FakeResponse(503))
    monkeypatch.setattr(fx.requests, "get", lambda *a, **k: FakeResponse(200, content=ECB_XML))
    with use_budget(SessionBudget()):
        rates = fx.get_rates()
    assert rates.source == fx.ECB_SOURCE and rates.updated == "2026-10-21"
    assert rates.convert(125, "USD", "EUR") == 100.0
    assert rates.convert(1.25, "USD", "JPY") == 175.0


def test_rates_are_cached_and_not_limited(monkeypatch):
    calls = []
    monkeypatch.setattr(http, "_send", lambda *a: calls.append(a) or FakeResponse(200, PRIMARY_ANSWER))
    with use_budget(SessionBudget(limits={"serpapi": 0})):
        fx.get_rates(), fx.get_rates()
    assert len(calls) == 1


def test_both_sources_down_is_reported(monkeypatch):
    monkeypatch.setattr(http, "_send", lambda *a: FakeResponse(503))
    monkeypatch.setattr(fx.requests, "get", lambda *a, **k: FakeResponse(503))
    with pytest.raises(http.LiveDataError):
        fx.get_rates()


@pytest.mark.parametrize("bad", ["", "EURO", "XYZ", None, "€"])
def test_unknown_currency_is_rejected(monkeypatch, bad):
    monkeypatch.setattr(http, "_send", lambda *a: FakeResponse(200, PRIMARY_ANSWER))
    with pytest.raises(InputValidationError):
        fx.get_rates().convert(10, "USD", bad)
