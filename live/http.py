"""One way to call every live API: cache first, then the session limit, then
the network with timeouts and retries.

Errors are raised as LiveDataError subclasses whose messages are safe to show:
they never contain the request URL or parameters, which hold the API keys.
Callers (the live tools) catch LiveDataError and fall back to snapshot data.
"""

import logging
import time
from dataclasses import dataclass

import requests

import config
from live import cache
from live.budget import LiveLimitError, current_budget

logger = logging.getLogger(__name__)

RETRY_STATUS = (429, 500, 502, 503, 504)
BACKOFF_SECONDS = (1, 3)


class LiveDataError(RuntimeError):
    """A live service couldn't answer. The message is safe to show to users."""


class LiveAuthError(LiveDataError):
    """The API key is missing or was rejected."""


class LiveQuotaError(LiveDataError):
    """The account's quota or the session's limit is used up."""


@dataclass(frozen=True)
class LiveResponse:
    data: dict
    fetched_at: float  # Unix time when the service answered
    from_cache: bool


def _send(method: str, url: str, params: dict | None, headers: dict | None, body: dict | None) -> requests.Response:
    return requests.request(method, url, params=params, headers=headers, json=body,
                            timeout=config.LIVE_TIMEOUT_SECONDS)


def fetch_json(service: str, url: str, *, ttl_seconds: int, params: dict | None = None,
               secret_params: dict | None = None, headers: dict | None = None, body: dict | None = None,
               method: str = "GET", label: str = "the live service") -> LiveResponse:
    """Call a JSON API. params and body form the cache key; secret_params (API keys)
    and headers are sent but never cached, logged or shown in errors."""
    key = cache.cache_key(service, url, params, body)
    cached = cache.get(key)
    if cached:
        return LiveResponse(cached.data, cached.fetched_at, from_cache=True)

    try:
        current_budget().charge(service)
    except LiveLimitError as error:
        raise LiveQuotaError(str(error)) from None

    all_params = {**(params or {}), **(secret_params or {})} or None
    for attempt in range(config.LIVE_RETRIES + 1):
        try:
            response = _send(method, url, all_params, headers, body)
        except requests.RequestException as error:
            logger.warning("%s request failed: %s", label, type(error).__name__)
            if attempt == config.LIVE_RETRIES:
                raise LiveDataError(f"Couldn't reach {label}. Check the internet connection.") from None
        else:
            if response.status_code not in RETRY_STATUS or attempt == config.LIVE_RETRIES:
                break
            logger.warning("%s returned HTTP %s, retrying", label, response.status_code)
        time.sleep(BACKOFF_SECONDS[min(attempt, len(BACKOFF_SECONDS) - 1)])

    if response.status_code in (401, 403):
        raise LiveAuthError(f"{label} rejected the API key. Check it in the .env file.")
    if response.status_code == 429:
        raise LiveQuotaError(f"{label} says the quota or rate limit is used up. Try again later.")
    if not response.ok:
        raise LiveDataError(f"{label} returned an error (HTTP {response.status_code}).")
    try:
        data = response.json()
    except ValueError:
        raise LiveDataError(f"{label} returned an unreadable answer.") from None
    stored = cache.put(key, data, ttl_seconds)
    return LiveResponse(stored.data, stored.fetched_at, from_cache=False)
