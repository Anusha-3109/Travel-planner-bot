"""Live places to stay: Airbnb listings or Google Hotels (via SerpApi).

Both searches use the trip's dates and number of guests, so prices are real
totals for that stay (Airbnb's include its fees). Results are cheapest per
night first and each gets an id for plans. Airbnb searches already only return
listings that fit the guests; the "pets" house rule maps to Airbnb's pets
filter, other house rules can't be filtered live.
"""

import config
from live import items
from live.serpapi_client import checked_at, search
from security.validation import InputValidationError

MAX_STAYS_SHOWN = 10
MAX_AIRBNB_GUESTS = 16  # the most guests an Airbnb search accepts
AIRBNB_ROOM_TYPES = {"entire room": "entire_home", "private room": "private_room"}


def _per_night(total: float | None, nights: int) -> float | None:
    return round(total / nights, 2) if total is not None else None


def _airbnb(listing: dict, city: str, nights: int) -> dict:
    total = listing.get("extracted_price")
    return {
        "type": "stay", "provider": "Airbnb", "city": city,
        "name": listing.get("name") or listing.get("title"),
        "kind": listing.get("title"),  # e.g. "Apartment in Trevi", "Room in Monti"
        "price_per_night": _per_night(total, nights), "total_price": total,
        "rating": listing.get("rating"), "reviews": listing.get("reviews"),
        "bedrooms": listing.get("bedrooms"), "beds": listing.get("beds"),
        "free_cancellation": bool(listing.get("free_cancellation")),
        "link": listing.get("link"),
    }


def _hotel(prop: dict, city: str, nights: int) -> dict:
    total = (prop.get("total_rate") or {}).get("extracted_lowest")
    nightly = (prop.get("rate_per_night") or {}).get("extracted_lowest")
    return {
        "type": "stay", "provider": "Google Hotels", "city": city,
        "name": prop.get("name"),
        "kind": prop.get("type") or "hotel",  # "hotel" or "vacation rental"
        "hotel_class": prop.get("hotel_class"),
        "price_per_night": nightly if nightly is not None else _per_night(total, nights), "total_price": total,
        "rating": prop.get("overall_rating"), "reviews": prop.get("reviews"),
        "link": prop.get("link"),
    }


def search_live_stays(city: str, check_in: str, check_out: str, nights: int, guests: int, stay_type: str = "airbnb",
                      max_price_per_night: float | None = None, room_type: str | None = None,
                      allow_pets: bool = False, min_rating: float | None = None) -> dict:
    """Live stays for the dates. Raises LiveDataError (or InputValidationError for groups too big
    for one search) so callers can fall back to snapshot data."""
    if stay_type != "hotel" and guests > MAX_AIRBNB_GUESTS:
        raise InputValidationError(f"Airbnb searches up to {MAX_AIRBNB_GUESTS} guests. Split the group or try hotels.")
    if stay_type == "hotel":
        params = {"q": city, "check_in_date": check_in, "check_out_date": check_out, "adults": guests,
                  "currency": "USD", "gl": "us", "hl": "en", "sort_by": "3"}  # 3 = lowest price
        if max_price_per_night:
            params["max_price"] = int(max_price_per_night)
        response = search("google_hotels", params, ttl_seconds=config.CACHE_TTL_SECONDS["stays"])
        stays = [_hotel(p, city, nights) for p in response.data.get("properties") or [] if p.get("name")]
        provider = "Google Hotels via SerpApi"
    else:
        params = {"q": city, "check_in_date": check_in, "check_out_date": check_out, "adults": guests,
                  "currency": "USD"}
        if room_type in AIRBNB_ROOM_TYPES:
            params["room_type"] = AIRBNB_ROOM_TYPES[room_type]
        if allow_pets:
            params["pets"] = 1
        if max_price_per_night:
            params["max_price"] = int(max_price_per_night * nights)  # Airbnb filters on the stay's total
        response = search("airbnb", params, ttl_seconds=config.CACHE_TTL_SECONDS["stays"])
        stays = [_airbnb(listing, city, nights) for listing in response.data.get("organic_results") or []]
        provider = "Airbnb via SerpApi"

    stays = [s for s in stays if s["name"]
             and (max_price_per_night is None or (s["price_per_night"] or 0) <= max_price_per_night)
             and (min_rating is None or (s["rating"] or 0) >= min_rating)]
    stays.sort(key=lambda s: (s["price_per_night"] is None, s["price_per_night"] or 0))
    for stay in stays:
        stay.update({"check_in": check_in, "check_out": check_out, "nights": nights, "guests": guests,
                     "checked_at": checked_at(response)})
        stay["per_night_text"] = f"${stay['price_per_night']:,.2f}" if stay["price_per_night"] is not None else "n/a"
        stay["total_text"] = f"${stay['total_price']:,.0f}" if stay["total_price"] is not None else "n/a"
        stay["cancellation_text"] = "Free cancellation" if stay.get("free_cancellation") else ""
        rating, reviews = stay.get("rating"), stay.get("reviews")
        stay["rating_text"] = ("No rating" if rating is None
                               else f"{rating:g} ({reviews:,})" if reviews else f"{rating:g}")
        stay["id"] = items.remember("stay", stay)
    notes = [f"Live prices in USD for {nights} night(s) and {guests} guest(s); they can change before booking."]
    if stay_type != "hotel":
        notes.append("Airbnb totals include Airbnb's fees; every listing fits the number of guests.")
    return {
        "source": "live",
        "provider": provider,
        "checked_at": checked_at(response),
        "from_cache": response.from_cache,
        "stay_count": len(stays),
        "stays": stays[:MAX_STAYS_SHOWN],
        "note": " ".join(notes) + " Use a stay's id in plans so its price is costed exactly.",
    }
