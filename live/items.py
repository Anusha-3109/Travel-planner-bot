"""Remember live results by ID, so a plan can refer to them later.

Each live flight, stay or restaurant gets a short ID (for example
"flight-3f9a1c2b"). The planning tools look prices up by that ID, so a trip
cost always uses the price the live service returned, never one the model
typed. Items are kept for a day in the live cache.
"""

import hashlib
import json

from live import cache

ITEM_TTL_SECONDS = 24 * 3600


def remember(kind: str, item: dict) -> str:
    digest = hashlib.sha1(json.dumps(item, sort_keys=True, default=str).encode("utf-8")).hexdigest()[:8]
    item_id = f"{kind}-{digest}"
    cache.put(cache.cache_key("item", item_id), {**item, "id": item_id}, ITEM_TTL_SECONDS)
    return item_id


def lookup(item_id: str) -> dict | None:
    found = cache.get(cache.cache_key("item", str(item_id).strip()))
    return found.data if found else None
