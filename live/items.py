"""Remember live results by ID and by name, so a plan can refer to them later.

Each live flight, stay, restaurant or transit route gets a short ID (for
example "flight-3f9a1c2b"). It is also findable by its name (a stay's or
restaurant's name, a flight's numbers such as "U2 8323", a transit summary),
because models often write the name instead of the ID. The planning tools look
prices up this way, so a trip cost always uses the price the live service
returned, never one the model typed. Items are kept for a day in the live cache.
"""

import hashlib
import json

from live import cache

ITEM_TTL_SECONDS = 24 * 3600


def _name(item: dict) -> str:
    return str(item.get("name") or " ".join(item.get("flight_numbers") or []) or item.get("summary") or "")


def _name_key(kind: str, name: str) -> str:
    return cache.cache_key("item-name", kind, {"name": " ".join(name.lower().split())})


def remember(kind: str, item: dict) -> str:
    digest = hashlib.sha1(json.dumps(item, sort_keys=True, default=str).encode("utf-8")).hexdigest()[:8]
    item_id = f"{kind}-{digest}"
    cache.put(cache.cache_key("item", item_id), {**item, "id": item_id}, ITEM_TTL_SECONDS)
    if _name(item):
        cache.put(_name_key(kind, _name(item)), {"id": item_id}, ITEM_TTL_SECONDS)
    return item_id


def lookup(item_id: str) -> dict | None:
    found = cache.get(cache.cache_key("item", str(item_id).strip()))
    return found.data if found else None


def lookup_by_name(kind: str, name: str) -> str | None:
    """The ID of the most recent live item of this kind with this name, if any."""
    found = cache.get(_name_key(kind, str(name)))
    return found.data["id"] if found else None
