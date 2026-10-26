"""Which live data services are set up, for the status panel in the app.

Checking SerpApi uses its account endpoint, which doesn't count as a search.
Google has no free equivalent, so its key is only checked for presence here;
a rejected key shows up as a clear error the first time a tool uses it.
Error messages never include the keys.
"""

from dataclasses import dataclass

import requests

from backend import config

SERPAPI_ACCOUNT_URL = "https://serpapi.com/account.json"


@dataclass(frozen=True)
class ServiceStatus:
    name: str
    provides: str
    configured: bool
    working: bool | None  # None: not checked
    detail: str


def serpapi_status() -> ServiceStatus:
    provides = "flights, hotels and Airbnb stays"
    if not config.SERPAPI_API_KEY:
        return ServiceStatus("SerpApi", provides, False, None, "Key not set: using snapshot data.")
    try:
        response = requests.get(SERPAPI_ACCOUNT_URL, params={"api_key": config.SERPAPI_API_KEY},
                                timeout=config.LIVE_TIMEOUT_SECONDS)
    except requests.RequestException:
        return ServiceStatus("SerpApi", provides, True, None, "Couldn't reach SerpApi to check the key.")
    if response.status_code in (401, 403):
        return ServiceStatus("SerpApi", provides, True, False, "Key rejected. Check SERPAPI_API_KEY in .env.")
    if not response.ok:
        return ServiceStatus("SerpApi", provides, True, None, f"SerpApi returned HTTP {response.status_code}.")
    account = response.json()
    left = account.get("total_searches_left", account.get("plan_searches_left"))
    plan = account.get("plan_name") or "plan"
    return ServiceStatus("SerpApi", provides, True, True, f"Connected ({plan}): {left} searches left this month.")


def google_status() -> ServiceStatus:
    provides = "restaurants and local transport"
    if not config.GOOGLE_MAPS_API_KEY:
        return ServiceStatus("Google Maps", provides, False, None, "Key not set: using snapshot data.")
    return ServiceStatus("Google Maps", provides, True, None, "Key set.")


def live_status() -> list[ServiceStatus]:
    return [serpapi_status(), google_status()]
