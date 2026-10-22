"""Live data status checks, with the network mocked so no key or search is used."""

import requests

import config
from live import status


class FakeResponse:
    def __init__(self, status_code: int, payload: dict | None = None):
        self.status_code, self._payload = status_code, payload or {}
        self.ok = status_code < 400

    def json(self) -> dict:
        return self._payload


def test_missing_keys_mean_snapshot_mode(monkeypatch):
    monkeypatch.setattr(config, "SERPAPI_API_KEY", "")
    monkeypatch.setattr(config, "GOOGLE_MAPS_API_KEY", "")
    assert all(not s.configured and "snapshot" in s.detail for s in status.live_status())


def test_serpapi_reports_searches_left(monkeypatch):
    monkeypatch.setattr(config, "SERPAPI_API_KEY", "test-key")
    monkeypatch.setattr(status.requests, "get",
                        lambda *a, **k: FakeResponse(200, {"plan_name": "Free Plan", "total_searches_left": 249}))
    result = status.serpapi_status()
    assert result.working and "249 searches left" in result.detail


def test_rejected_key_and_network_errors_never_show_the_key(monkeypatch):
    monkeypatch.setattr(config, "SERPAPI_API_KEY", "secret-key-123")
    monkeypatch.setattr(status.requests, "get", lambda *a, **k: FakeResponse(401))
    rejected = status.serpapi_status()
    assert rejected.working is False and "secret-key-123" not in rejected.detail

    def fail(*args, **kwargs):
        raise requests.ConnectionError("https://serpapi.com/account.json?api_key=secret-key-123")
    monkeypatch.setattr(status.requests, "get", fail)
    assert "secret-key-123" not in status.serpapi_status().detail
