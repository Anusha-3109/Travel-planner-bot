"""SerpApi: live Google Flights, Google Hotels and Airbnb results.

All SerpApi calls go through search(), which adds the API key, uses the shared
cache and session limit, and turns SerpApi's own error messages into
LiveDataError. To switch to another provider later, only this file and the
small parsers in live/flights.py (and later live/stays.py) need to change.
"""

from datetime import datetime, timezone

import config
from live.http import LiveAuthError, LiveDataError, LiveResponse, fetch_json

SERPAPI_URL = "https://serpapi.com/search.json"
PROVIDER = "SerpApi"
NO_RESULTS_PHRASES = ("hasn't returned any results", "no results")


def search(engine: str, params: dict, ttl_seconds: int) -> LiveResponse:
    if not config.SERPAPI_API_KEY:
        raise LiveAuthError("Live search is off because SERPAPI_API_KEY isn't set.")
    response = fetch_json("serpapi", SERPAPI_URL, ttl_seconds=ttl_seconds, params={"engine": engine, **params},
                          secret_params={"api_key": config.SERPAPI_API_KEY}, label=PROVIDER)
    error = str(response.data.get("error") or "")
    if error and not any(phrase in error.lower() for phrase in NO_RESULTS_PHRASES):
        raise LiveDataError(f"{PROVIDER}: {error[:200]}")
    return response


def checked_at(response: LiveResponse) -> str:
    return datetime.fromtimestamp(response.fetched_at, timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
