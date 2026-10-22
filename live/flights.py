"""Live one-way flights from Google Flights (via SerpApi).

Each leg of a trip is searched as a one-way flight, so a round trip uses two
searches. Round-trip fares can be a little cheaper than two one-way fares,
which the result note mentions. Prices are per person in USD.
"""

from datetime import date

import config
from live import items
from live.airports import airports_for
from live.serpapi_client import checked_at, search

PROVIDER = "Google Flights via SerpApi"


MAX_FLIGHTS_SHOWN = 15


def _duration(minutes: int | None) -> str | None:
    return f"{minutes // 60}h {minutes % 60:02d}m" if minutes else None


def _clock(timestamp: str | None, day: str) -> str | None:
    """'2026-11-11 01:20' on a trip dated 2026-11-10 becomes '01:20 (+1 day)'."""
    if not timestamp:
        return None
    when, _, clock = timestamp.partition(" ")
    if not clock:
        return timestamp
    extra = (date.fromisoformat(when) - date.fromisoformat(day)).days
    return clock if extra == 0 else f"{clock} ({extra:+d} day{'s' if abs(extra) > 1 else ''})"


def _by_airline(flights: list[dict]) -> list[dict]:
    """Group flights under their airline (or airline combination for connections),
    cheapest airline first, so answers can show one table per airline."""
    groups: dict[str, list[dict]] = {}
    for flight in flights:
        groups.setdefault(" + ".join(flight["airlines"]) or "Unknown airline", []).append(flight)
    summaries = []
    for airline, options in groups.items():
        prices = [f["price_per_person"] for f in options if f["price_per_person"] is not None]
        summaries.append({
            "airline": airline,
            "flight_count": len(options),
            "from_price_per_person": min(prices) if prices else None,
            "flights": [{key: f[key] for key in ("id", "flight_numbers", "from_airport", "to_airport", "departs",
                                                  "arrives", "duration", "stops", "layovers", "price_per_person")}
                        for f in options],
        })
    summaries.sort(key=lambda g: (g["from_price_per_person"] is None, g["from_price_per_person"] or 0))
    return summaries


def _flight(option: dict, origin: str, destination: str, day: str, passengers: int) -> dict:
    segments = option.get("flights") or []
    first, last = segments[0], segments[-1]
    item = {
        "type": "flight",
        "origin_city": origin,
        "destination_city": destination,
        "date": day,
        "airlines": list(dict.fromkeys(s.get("airline", "") for s in segments if s.get("airline"))),
        "flight_numbers": [s.get("flight_number") for s in segments if s.get("flight_number")],
        "from_airport": first.get("departure_airport", {}).get("id"),
        "to_airport": last.get("arrival_airport", {}).get("id"),
        "departure": first.get("departure_airport", {}).get("time"),
        "arrival": last.get("arrival_airport", {}).get("time"),
        "departs": _clock(first.get("departure_airport", {}).get("time"), day),
        "arrives": _clock(last.get("arrival_airport", {}).get("time"), day),
        "duration": _duration(option.get("total_duration")),
        "stops": len(option.get("layovers") or []),
        "layovers": [stop.get("id") for stop in option.get("layovers") or [] if stop.get("id")],
        "price_per_person": option.get("price"),  # None when Google shows no price
        "passengers": passengers,
        "currency": "USD",
    }
    item["id"] = items.remember("flight", item)
    return item


def search_live_flights(origin: str, destination: str, day: str, passengers: int = 1) -> dict:
    """Live flights for one date. Raises LiveDataError (or InputValidationError for
    unknown cities) so callers can fall back to snapshot data."""
    origins, destinations = airports_for(origin), airports_for(destination)
    response = search("google_flights", {
        "departure_id": ",".join(a.code for a in origins),
        "arrival_id": ",".join(a.code for a in destinations),
        "outbound_date": day,
        "type": "2",  # one way
        "adults": passengers,
        "currency": "USD",
        "hl": "en",
        "gl": "us",
    }, ttl_seconds=config.CACHE_TTL_SECONDS["flights"])
    options = (response.data.get("best_flights") or []) + (response.data.get("other_flights") or [])
    flights = [_flight(o, origin, destination, day, passengers) for o in options if o.get("flights")]
    flights.sort(key=lambda f: (f["price_per_person"] is None, f["price_per_person"] or 0, f["departure"] or ""))
    insights = response.data.get("price_insights") or {}
    return {
        "source": "live",
        "provider": PROVIDER,
        "checked_at": checked_at(response),
        "from_cache": response.from_cache,
        "airports_searched": {"from": [a.code for a in origins], "to": [a.code for a in destinations]},
        "flight_count": len(flights),
        "airlines": _by_airline(flights[:MAX_FLIGHTS_SHOWN]),
        "price_insights": {key: insights[key] for key in ("lowest_price", "price_level", "typical_price_range")
                           if key in insights},
        "note": "Live prices per person in USD for a one-way ticket; they can change before booking. "
                "Use a flight's id in plans so its price is costed exactly.",
    }


def is_live_date(day: str) -> bool:
    """Live searches only make sense for today or later."""
    return date.fromisoformat(day) >= date.today()
