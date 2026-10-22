"""Google Maps Platform: Places API (New) for restaurants, Routes API for local transport.

The key travels in a request header, so it is never part of the cache key,
the cache, logs or error messages. Field masks keep each request to the
fields the app uses, which also keeps Google's per-request cost down.
"""

from datetime import datetime, timezone

import config
from live.http import LiveAuthError, LiveResponse, fetch_json

PLACES_SEARCH_URL = "https://places.googleapis.com/v1/places:searchText"
ROUTES_URL = "https://routes.googleapis.com/directions/v2:computeRoutes"


def post(url: str, body: dict, field_mask: str, ttl_seconds: int, label: str) -> LiveResponse:
    if not config.GOOGLE_MAPS_API_KEY:
        raise LiveAuthError("Live Google Maps data is off because GOOGLE_MAPS_API_KEY isn't set.")
    return fetch_json("google", url, method="POST", body=body, ttl_seconds=ttl_seconds, label=label,
                      headers={"X-Goog-Api-Key": config.GOOGLE_MAPS_API_KEY, "X-Goog-FieldMask": field_mask})


def checked_at(response: LiveResponse) -> str:
    return datetime.fromtimestamp(response.fetched_at, timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
