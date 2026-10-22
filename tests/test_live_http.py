"""Cache, session limit and request helper, with the network mocked."""

import pytest
import requests

import config
from live import cache, http
from live.budget import LiveLimitError, SessionBudget, use_budget


class FakeResponse:
    def __init__(self, status_code: int, payload=None):
        self.status_code, self._payload = status_code, payload if payload is not None else {}
        self.ok = status_code < 400

    def json(self):
        if isinstance(self._payload, Exception):
            raise self._payload
        return self._payload


@pytest.fixture(autouse=True)
def isolated(tmp_path, monkeypatch):
    """A private cache file, no retry delays, and a record of every network call."""
    monkeypatch.setattr(config, "CACHE_DB", tmp_path / "live.sqlite3")
    monkeypatch.setattr(http.time, "sleep", lambda _: None)
    calls = []
    monkeypatch.setattr(http, "_send", lambda *args: calls.append(args) or responses.pop(0))
    responses: list = []
    return calls, responses


def _fetch(**kwargs):
    defaults = {"ttl_seconds": 60, "params": {"q": "Rome"}, "secret_params": {"api_key": "secret-123"}}
    return http.fetch_json("serpapi", "https://example.test/search", **{**defaults, **kwargs})


def test_second_identical_call_comes_from_cache_and_is_free(isolated):
    calls, responses = isolated
    responses.append(FakeResponse(200, {"price": 99}))
    budget = SessionBudget(limits={"serpapi": 5})
    with use_budget(budget):
        first, second = _fetch(), _fetch()
    assert (first.from_cache, second.from_cache) == (False, True)
    assert second.data == {"price": 99} and len(calls) == 1
    assert budget.used == {"serpapi": 1}


def test_cache_expires_and_never_stores_the_key(tmp_path):
    path = tmp_path / "c.sqlite3"
    key = cache.cache_key("serpapi", "https://example.test", {"q": "Rome"})
    cache.put(key, {"price": 1}, ttl_seconds=60, path=path, now=1000)
    assert cache.get(key, path=path, now=1059).data == {"price": 1}
    assert cache.get(key, path=path, now=1061) is None
    assert b"secret" not in path.read_bytes()


def test_session_limit_stops_live_calls(isolated):
    _, responses = isolated
    responses.extend([FakeResponse(200, {"n": 1})])
    with use_budget(SessionBudget(limits={"serpapi": 1})):
        _fetch(params={"q": "Rome"})
        with pytest.raises(http.LiveQuotaError, match="all 1 live serpapi searches"):
            _fetch(params={"q": "Paris"})
    with pytest.raises(LiveLimitError):
        SessionBudget(limits={"google": 0}).charge("google")


def test_retries_server_errors_then_succeeds(isolated):
    calls, responses = isolated
    responses.extend([FakeResponse(503), FakeResponse(200, {"ok": True})])
    with use_budget(SessionBudget()):
        assert _fetch().data == {"ok": True}
    assert len(calls) == 2


@pytest.mark.parametrize("response, error", [
    (FakeResponse(401), http.LiveAuthError),
    (FakeResponse(429), http.LiveQuotaError),
    (FakeResponse(400), http.LiveDataError),
    (FakeResponse(200, ValueError("not json")), http.LiveDataError),
])
def test_errors_are_safe_to_show(isolated, monkeypatch, response, error):
    _, responses = isolated
    responses.extend([response] * (config.LIVE_RETRIES + 1))
    with use_budget(SessionBudget()), pytest.raises(error) as raised:
        _fetch()
    assert "secret-123" not in str(raised.value) and "example.test" not in str(raised.value)


def test_network_failure_is_reported_without_the_url(monkeypatch):
    def fail(*args):
        raise requests.ConnectionError("https://example.test/search?api_key=secret-123")
    monkeypatch.setattr(http, "_send", fail)
    with use_budget(SessionBudget()), pytest.raises(http.LiveDataError) as raised:
        _fetch(label="SerpApi")
    assert "secret-123" not in str(raised.value) and "SerpApi" in str(raised.value)
