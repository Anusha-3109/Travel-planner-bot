"""Search restaurants and places to stay.

Places to stay are live first: with check-in and check-out dates for today or
later and a SerpApi key set, search_accommodations asks Airbnb (default) or
Google Hotels for current prices. Otherwise, or if the live search fails, it
uses the snapshot data (TravelPlanner for US cities, Inside Airbnb for
European and Asian cities) with exact filters.
"""

import json
from datetime import date

from langchain_core.tools import tool

import config
from live.flights import is_live_date, too_far_ahead
from live.http import LiveDataError
from live.restaurants import search_live_restaurants
from live.stays import search_live_stays
from security.validation import (
    InputValidationError,
    validate_choice,
    validate_city,
    validate_date,
    validate_keyword,
    validate_max_price,
    validate_people,
    validate_rating,
    validate_trip_days,
)
from travel_data.catalog import HOUSE_RULES, ROOM_TYPES, load_catalog


def _snapshot_restaurants(city: str, cuisine: str | None = None, max_average_cost: float | None = None,
                          min_rating: float | None = None) -> dict:
    catalog = load_catalog()
    city = catalog.require_city(city)
    cuisine = validate_choice(cuisine, catalog.cuisines, "Cuisine")
    max_cost = validate_max_price(max_average_cost, "Maximum average cost")
    min_rating = validate_rating(min_rating)

    # A restaurant without a price or rating can't be shown to meet a cost or rating filter.
    matches = [
        r for r in catalog.restaurants.get(city.lower(), [])
        if (cuisine is None or cuisine in r.cuisines)
        and (max_cost is None or (r.average_cost is not None and r.average_cost <= max_cost))
        and (min_rating is None or (r.rating is not None and r.rating >= min_rating))
    ]
    matches.sort(key=lambda r: (-(r.rating or 0), r.average_cost if r.average_cost is not None else float("inf")))
    return {
        "city": city,
        "filters": {"cuisine": cuisine, "max_average_cost": max_cost, "min_rating": min_rating},
        "match_count": len(matches),
        "restaurants": [
            {"name": r.name, "cuisines": list(r.cuisines),
             "average_cost_per_person": r.average_cost if r.average_cost is not None else "not available",
             "rating": r.rating if r.rating is not None else "not available"}
            for r in matches[: config.MAX_RESULTS_SHOWN]
        ],
        "note": catalog.data_note(city),
    }


def find_restaurants(city: str, cuisine: str | None = None, max_average_cost: float | None = None,
                     min_rating: float | None = None) -> dict:
    """Live restaurants from Google Places when a key is set, otherwise (or if that
    fails) the snapshot restaurants."""
    max_cost = validate_max_price(max_average_cost, "Maximum average cost")
    min_rating = validate_rating(min_rating)
    if not config.GOOGLE_MAPS_API_KEY:
        reason = "Live restaurants are off (no Google Maps key), so snapshot data is shown."
    else:
        try:
            live = search_live_restaurants(validate_city(city), validate_keyword(cuisine, "Cuisine"), max_cost,
                                           min_rating)
        except LiveDataError as error:
            reason = f"Live restaurant search failed ({error}), so snapshot data is shown."
        else:
            return {"city": city, "restaurants_source": f"live ({live['provider']}, checked {live['checked_at']})",
                    "filters": {"cuisine": cuisine, "max_cost_per_person_usd": max_cost, "min_rating": min_rating},
                    "match_count": live["restaurant_count"], "restaurants": live["restaurants"],
                    "note": live["note"]}
    result = _snapshot_restaurants(city, cuisine, max_cost, min_rating)
    result["restaurants_source"] = "snapshot"
    if config.GOOGLE_MAPS_API_KEY:
        result["note"] = f"{reason} {result['note']}"
    return result


def _snapshot_accommodations(city: str, max_price_per_night: float | None = None, room_type: str | None = None,
                             must_allow: str | None = None, people: int | None = None,
                             nights: int | None = None) -> dict:
    catalog = load_catalog()
    city = catalog.require_city(city)
    max_price = validate_max_price(max_price_per_night, "Maximum price per night")
    room_type = validate_choice(room_type, list(ROOM_TYPES), "Room type")
    must_allow = validate_choice(must_allow, list(HOUSE_RULES), "House rule")
    people = validate_people(people) if people is not None else None
    nights = validate_trip_days(nights) if nights is not None else None

    matches = [
        a for a in catalog.accommodations.get(city.lower(), [])
        if (max_price is None or a.price <= max_price)
        and (room_type is None or a.matches_room_type(room_type))
        and (must_allow is None or a.allows(must_allow))
        and (nights is None or a.minimum_nights <= nights)
    ]
    matches.sort(key=lambda a: (a.price, -(a.rating or 0)))

    def summary(a) -> dict:
        item = {"name": a.name, "room_type": a.room_type, "price_per_night": a.price,
                "maximum_occupancy": a.maximum_occupancy, "minimum_nights": a.minimum_nights,
                "house_rules": list(a.house_rules) if a.house_rules is not None else "not published",
                "rating": a.rating if a.rating is not None else "not available"}
        if people:
            item["rooms_needed"] = a.rooms_needed(people)
            if nights:
                item["total_cost"] = a.price * a.rooms_needed(people) * nights
        return item

    return {
        "city": city,
        "filters": {"max_price_per_night": max_price, "room_type": room_type, "must_allow": must_allow,
                    "people": people, "nights": nights},
        "match_count": len(matches),
        "accommodations": [summary(a) for a in matches[: config.MAX_RESULTS_SHOWN]],
        "note": f"{catalog.data_note(city)} When a group is larger than maximum_occupancy, several rooms are booked. "
                "Prices are in USD. A stay whose house rules are not published never matches must_allow.",
    }


@tool
def search_restaurants(city: str, cuisine: str | None = None, max_average_cost: float | None = None,
                       min_rating: float | None = None) -> str:
    """Find restaurants in a city worldwide. Live from Google Maps: rating, review
    count, price range per person (local currency and USD, plus an estimated cost
    per person), open now, opening hours, address and a Maps link; each has an
    id to use in plans. cuisine is any word ('Italian', 'sushi', 'vegan').
    max_average_cost is the most per person in USD; min_rating is 0-5. If live
    data is unavailable, snapshot restaurants are used (US 2022 with prices;
    Europe and Asia without prices or ratings)."""
    try:
        return json.dumps(find_restaurants(city, cuisine, max_average_cost, min_rating))
    except InputValidationError as error:
        return json.dumps({"error": str(error)})


STAY_TYPES = ("airbnb", "hotel")


def _stay_dates(check_in_date: str, check_out_date: str) -> tuple[str, str, int]:
    check_in, check_out = validate_date(check_in_date), validate_date(check_out_date)
    nights = (date.fromisoformat(check_out) - date.fromisoformat(check_in)).days
    if nights < 1:
        raise InputValidationError("The check-out date must be after the check-in date.")
    return check_in, check_out, validate_trip_days(nights)


def find_accommodations(city: str, max_price_per_night: float | None = None, room_type: str | None = None,
                        must_allow: str | None = None, people: int | None = None, nights: int | None = None,
                        check_in_date: str | None = None, check_out_date: str | None = None,
                        stay_type: str = "airbnb", min_rating: float | None = None) -> dict:
    if not check_in_date or not check_out_date:
        result = _snapshot_accommodations(city, max_price_per_night, room_type, must_allow, people, nights)
        result["stays_source"] = "snapshot"
        return result

    check_in, check_out, nights = _stay_dates(check_in_date, check_out_date)
    guests = validate_people(people or 1)
    stay_type = validate_choice(stay_type or "airbnb", STAY_TYPES, "Stay type")
    room_type = validate_choice(room_type, list(ROOM_TYPES), "Room type")
    must_allow = validate_choice(must_allow, list(HOUSE_RULES), "House rule")
    max_price = validate_max_price(max_price_per_night, "Maximum price per night")
    min_rating = validate_rating(min_rating)

    if not config.SERPAPI_API_KEY:
        reason = "Live stays are off (no SerpApi key), so snapshot data is shown."
    elif not is_live_date(check_in):
        reason = "The check-in date is in the past, so live stays aren't available and snapshot data is shown."
    elif too_far_ahead(check_in):
        reason = ("The check-in date is more than about 11 months ahead, too far for live prices, so snapshot data "
                  "is shown.")
    else:
        try:
            live = search_live_stays(validate_city(city), check_in, check_out, nights, guests, stay_type, max_price,
                                     room_type, allow_pets=must_allow == "pets", min_rating=min_rating)
        except (LiveDataError, InputValidationError) as error:
            reason = f"Live stay search failed ({error}), so snapshot data is shown."
        else:
            note = live["note"]
            if must_allow and must_allow != "pets":
                note += f" Live listings can't be filtered by the '{must_allow}' house rule: check each listing."
            return {"city": city, "check_in": check_in, "check_out": check_out, "nights": nights, "guests": guests,
                    "stays_source": f"live ({live['provider']}, checked {live['checked_at']})",
                    "stay_count": live["stay_count"], "stays": live["stays"], "note": note}

    result = _snapshot_accommodations(city, max_price, room_type, must_allow, guests, nights)
    result["stays_source"] = "snapshot"
    result["note"] = f"{reason} {result['note']}"
    return result


@tool
def search_accommodations(city: str, check_in_date: str | None = None, check_out_date: str | None = None,
                          people: int | None = None, stay_type: str = "airbnb",
                          max_price_per_night: float | None = None, room_type: str | None = None,
                          must_allow: str | None = None, min_rating: float | None = None,
                          nights: int | None = None) -> str:
    """Find places to stay in a city, cheapest per night first.
    With check_in_date and check_out_date (YYYY-MM-DD, today or later): live
    results with current prices for those dates and people, worldwide.
    stay_type: 'airbnb' (default) or 'hotel'. Each live stay has an id, a total
    price, a rating and a link. Without dates, or if live search is unavailable:
    snapshot data (TravelPlanner US cities, Inside Airbnb for European and
    Asian cities), where nights adds the total cost.
    room_type: 'entire room', 'private room', 'shared room' or 'not shared room'.
    must_allow: a house rule the guest needs allowed: 'smoking', 'parties',
    'children under 10', 'visitors' or 'pets'. min_rating: 0-5."""
    try:
        return json.dumps(find_accommodations(city, max_price_per_night, room_type, must_allow, people, nights,
                                              check_in_date, check_out_date, stay_type, min_rating))
    except InputValidationError as error:
        return json.dumps({"error": str(error)})
