"""Live restaurants from Google Places (Places API (New) text search).

Each restaurant has Google's price range per person in the local currency (for
example EUR 20-30), converted to USD at today's exchange rate, plus rating,
review count, whether it is open now, opening hours, address and a Google Maps
link. For trip costs the middle of the price range is used as the cost per
person per meal, and the answer says it is an estimate from a range.
"""

import logging

import config
from live import fx, items
from live.google_client import PLACES_SEARCH_URL, checked_at, post
from live.http import LiveDataError

logger = logging.getLogger(__name__)

MAX_RESTAURANTS = 10
FIELDS = ",".join("places." + field for field in (
    "id", "displayName", "formattedAddress", "rating", "userRatingCount", "priceLevel", "priceRange",
    "currentOpeningHours.openNow", "regularOpeningHours.weekdayDescriptions", "googleMapsUri",
    "primaryTypeDisplayName", "websiteUri"))
PRICE_LEVELS = {"PRICE_LEVEL_FREE": "Free", "PRICE_LEVEL_INEXPENSIVE": "$", "PRICE_LEVEL_MODERATE": "$$",
                "PRICE_LEVEL_EXPENSIVE": "$$$", "PRICE_LEVEL_VERY_EXPENSIVE": "$$$$"}


def _money(price: dict | None) -> tuple[float | None, str | None]:
    if not price:
        return None, None
    return float(price.get("units") or 0) + float(price.get("nanos") or 0) / 1e9, price.get("currencyCode")


def _price(place: dict, rates: fx.ExchangeRates | None) -> dict:
    start, currency = _money((place.get("priceRange") or {}).get("startPrice"))
    end, _ = _money((place.get("priceRange") or {}).get("endPrice"))
    result = {"price_level": PRICE_LEVELS.get(place.get("priceLevel")), "price_range_local": None,
              "price_range_usd": None, "estimated_cost_per_person_usd": None}
    if start is None or not currency:
        return result
    result["price_range_local"] = f"{currency} {start:g}–{end:g}" if end is not None else f"{currency} {start:g}+"
    if rates:
        try:
            low = rates.convert(start, currency, "USD")
            high = rates.convert(end, currency, "USD") if end is not None else None
        except Exception:  # an unusual currency code: keep the local price only
            return result
        result["price_range_usd"] = f"${low:.0f}–{high:.0f}" if high is not None else f"${low:.0f}+"
        result["_range_usd"] = (low, high)
        result["estimated_cost_per_person_usd"] = round((low + high) / 2 if high is not None else low, 2)
    return result


def _rating_text(rating: float | None, reviews: int | None) -> str:
    if rating is None:
        return "No rating"
    return f"{rating:g} ({reviews:,})" if reviews else f"{rating:g}"


def _restaurant(place: dict, city: str, cuisine: str | None, rates: fx.ExchangeRates | None, checked: str) -> dict:
    item = {
        "type": "restaurant",
        "name": (place.get("displayName") or {}).get("text"),
        "city": city,
        "cuisine": cuisine,
        "address": place.get("formattedAddress"),
        "rating": place.get("rating"),
        "reviews": place.get("userRatingCount"),
        **_price(place, rates),
        "open_now": (place.get("currentOpeningHours") or {}).get("openNow"),
        "opening_hours": (place.get("regularOpeningHours") or {}).get("weekdayDescriptions"),
        "maps_link": place.get("googleMapsUri"),
        "website": place.get("websiteUri"),
        "checked_at": checked,
    }
    item["rating_text"] = _rating_text(item["rating"], item["reviews"])
    if item["price_range_local"]:
        local_currency = item["price_range_local"].split(" ")[0]
        shown = ""
        if item["estimated_cost_per_person_usd"] is not None and fx.display_currency() != local_currency:
            low, high = item["_range_usd"]
            shown = f" (~{fx.money_range(low, high)})"
        item["price_text"] = f"{item['price_range_local']}{shown}"
    else:
        item["price_text"] = "Price not listed"
    item.pop("_range_usd", None)  # only needed to build price_text
    item["id"] = items.remember("restaurant", {k: v for k, v in item.items() if k != "opening_hours"})
    return item


def search_live_restaurants(city: str, cuisine: str | None = None, max_cost_per_person: float | None = None,
                            min_rating: float | None = None) -> dict:
    """Live restaurants. Raises LiveDataError so callers can fall back to snapshot data."""
    query = f"{cuisine} restaurants in {city}" if cuisine else f"restaurants in {city}"
    body = {"textQuery": query, "includedType": "restaurant", "pageSize": MAX_RESTAURANTS, "languageCode": "en"}
    if min_rating:
        body["minRating"] = min_rating
    response = post(PLACES_SEARCH_URL, body, FIELDS, config.CACHE_TTL_SECONDS["restaurants"], "Google Places")
    try:
        rates = fx.get_rates()
    except LiveDataError:
        logger.warning("No exchange rates; restaurant prices stay in local currency")
        rates = None
    restaurants = [_restaurant(p, city, cuisine, rates, checked_at(response)) for p in response.data.get("places") or []]
    restaurants = [r for r in restaurants if r["name"]]
    if max_cost_per_person is not None:
        restaurants = [r for r in restaurants if r["estimated_cost_per_person_usd"] is not None
                       and r["estimated_cost_per_person_usd"] <= max_cost_per_person]
    notes = ["Live from Google Maps. Prices are Google's typical range per person; the estimated cost is the "
             "middle of that range."]
    if rates:
        notes.append(rates.note())
    return {
        "source": "live",
        "provider": "Google Places",
        "checked_at": checked_at(response),
        "from_cache": response.from_cache,
        "query": query,
        "restaurant_count": len(restaurants),
        "restaurants": restaurants,
        "note": " ".join(notes) + " Use a restaurant's id in plans so its price is costed.",
    }
