"""Live local transport between two places, from the Google Routes API.

- Public transport: up to three different routes (fastest first) with each
  line (train, metro, bus, tram, ferry), where to get on and off, the number of
  stops, departure and arrival times, walking time, and the fare when Google
  publishes one (converted to USD at today's rate).
- Driving: distance and time without traffic. In the US, an estimated cost at
  the IRS 2026 standard mileage rate (fuel and running costs; no tolls or
  parking). Google gives no taxi prices, so a taxi is described by driving
  time and distance only.

With a travel date (and time), public transport is searched for that local
time, up to 100 days ahead (Google's limit). The local time is turned into UTC
with the time zone Google reports for the route. Without a date, or further
ahead, times come from the current timetable; on another day departure times
shift but the lines and the trip length are a good guide.
"""

import logging
import re
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from backend import config
from backend.live import fx, items
from backend.live.google_client import ROUTES_URL, checked_at, post
from backend.live.http import LiveDataError
from backend.travel_data.catalog import load_catalog

logger = logging.getLogger(__name__)

MAX_TRANSIT_OPTIONS = 3
MAX_TRANSIT_DAYS_AHEAD = 100  # Google Routes accepts transit departure times up to 100 days ahead
TRANSIT_FIELDS = ",".join([
    "routes.duration", "routes.distanceMeters", "routes.travelAdvisory.transitFare",
    "routes.legs.steps.travelMode", "routes.legs.steps.staticDuration", "routes.legs.steps.transitDetails"])
DRIVE_FIELDS = "routes.duration,routes.distanceMeters"
VEHICLES = {"HEAVY_RAIL": "Train", "RAIL": "Train", "COMMUTER_TRAIN": "Train", "HIGH_SPEED_TRAIN": "Train",
            "LONG_DISTANCE_TRAIN": "Train", "SUBWAY": "Metro", "METRO_RAIL": "Metro", "MONORAIL": "Monorail",
            "BUS": "Bus", "INTERCITY_BUS": "Bus", "TROLLEYBUS": "Bus", "SHARE_TAXI": "Shared taxi",
            "TRAM": "Tram", "LIGHT_RAIL": "Tram", "FERRY": "Ferry", "CABLE_CAR": "Cable car",
            "GONDOLA_LIFT": "Cable car", "FUNICULAR": "Funicular"}


def _seconds(value: str | None) -> int:
    match = re.match(r"^(\d+)s$", value or "")
    return int(match.group(1)) if match else 0


def _minutes_text(seconds: int) -> str:
    minutes = max(round(seconds / 60), 1)
    return f"{minutes // 60}h {minutes % 60:02d}m" if minutes >= 60 else f"{minutes} min"


def _fare(route: dict, rates: fx.ExchangeRates | None) -> tuple[str | None, float | None]:
    fare = (route.get("travelAdvisory") or {}).get("transitFare") or {}
    if not fare.get("currencyCode"):
        return None, None
    amount = float(fare.get("units") or 0) + float(fare.get("nanos") or 0) / 1e9
    usd = None
    if rates:
        try:
            usd = rates.convert(amount, fare["currencyCode"], "USD")
        except Exception:  # an unusual currency code: keep the local fare only
            pass
    shown = f" ({fx.money(usd, approx=True)})" if usd is not None and fx.display_currency() != fare["currencyCode"] else ""
    text = f"{fare['currencyCode']} {amount:.2f}{shown}"
    return text, usd


def _steps(route: dict) -> list[dict]:
    """Transit rides with the walking in between merged into single walk steps."""
    steps, walk = [], 0
    for step in (route.get("legs") or [{}])[0].get("steps") or []:
        details = step.get("transitDetails")
        if not details:
            walk += _seconds(step.get("staticDuration"))
            continue
        if walk:
            steps.append({"mode": "Walk", "text": f"Walk {_minutes_text(walk)}"})
            walk = 0
        line = details.get("transitLine") or {}
        vehicle = VEHICLES.get((line.get("vehicle") or {}).get("type"), "Transit")
        name = line.get("nameShort") or line.get("name") or ""
        stops = details.get("stopDetails") or {}
        times = details.get("localizedValues") or {}
        depart = ((times.get("departureTime") or {}).get("time") or {}).get("text")
        arrive = ((times.get("arrivalTime") or {}).get("time") or {}).get("text")
        board = (stops.get("departureStop") or {}).get("name")
        alight = (stops.get("arrivalStop") or {}).get("name")
        count = details.get("stopCount")
        text = f"{vehicle} {name}".strip() + f" from {board} to {alight}"
        if count:
            text += f" ({count} stop{'s' if count != 1 else ''})"
        if depart and arrive:
            text += f", {depart} → {arrive}"
        if details.get("headsign"):
            text += f", towards {details['headsign']}"
        steps.append({"mode": vehicle, "line": name, "from": board, "to": alight, "stops": count,
                      "departs": depart, "arrives": arrive, "text": text})
    if walk:
        steps.append({"mode": "Walk", "text": f"Walk {_minutes_text(walk)}"})
    return steps


def _transit_options(data: dict, origin: str, destination: str, rates: fx.ExchangeRates | None,
                     checked: str) -> list[dict]:
    options, seen = [], set()
    for route in sorted(data.get("routes") or [], key=lambda r: _seconds(r.get("duration"))):
        steps = _steps(route)
        rides = [s for s in steps if s["mode"] != "Walk"]
        signature = tuple((s["mode"], s.get("line"), s.get("from"), s.get("to")) for s in rides)
        if not rides or signature in seen:
            continue  # same lines at a later time: keep only the first
        seen.add(signature)
        fare_text, fare_usd = _fare(route, rates)
        option = {
            "type": "transit", "origin": origin, "destination": destination,
            "summary": " → ".join(f"{s['mode']} {s['line']}".strip() for s in rides),
            "duration": _minutes_text(_seconds(route.get("duration"))),
            "distance_km": round((route.get("distanceMeters") or 0) / 1000, 1),
            "transfers": len(rides) - 1,
            "fare_text": fare_text or "Fare not published by Google",
            "fare_per_person_usd": fare_usd,
            "steps": [s["text"] for s in steps],
            "checked_at": checked,
        }
        option["id"] = items.remember("transit", option)
        options.append(option)
        if len(options) == MAX_TRANSIT_OPTIONS:
            break
    return options


def _time_zone(data: dict) -> ZoneInfo | None:
    """The time zone Google reports for the first ride, e.g. Europe/Rome."""
    for route in data.get("routes") or []:
        for step in (route.get("legs") or [{}])[0].get("steps") or []:
            times = (step.get("transitDetails") or {}).get("localizedValues") or {}
            name = (times.get("departureTime") or {}).get("timeZone")
            if name:
                try:
                    return ZoneInfo(name)
                except ZoneInfoNotFoundError:
                    return None
    return None


def _departure_utc(depart_at: datetime, zone: ZoneInfo, now: datetime) -> tuple[datetime | None, str]:
    """The local departure time in UTC, or None and the reason it can't be searched."""
    utc = depart_at.replace(tzinfo=zone).astimezone(timezone.utc)
    if utc < now - timedelta(days=7):
        return None, "The travel time is in the past, so the current timetable is shown."
    if utc > now + timedelta(days=MAX_TRANSIT_DAYS_AHEAD):
        return None, (f"Google has timetables up to {MAX_TRANSIT_DAYS_AHEAD} days ahead, so the current timetable "
                      "is shown; on the travel day departure times will differ.")
    return utc, ""


def _address(place: str, city: str | None) -> str:
    return f"{place}, {city}" if city and city.lower() not in place.lower() else place


def _in_us(*places: str | None) -> bool:
    """Whether the trip is in the US: the city, or one of the ends, is a known US city."""
    catalog = load_catalog()
    for place in places:
        for part in (place or "").split(","):
            info = catalog.city_info.get(" ".join(part.split()).lower())
            if info:
                return info.country == "United States"
    return False


def _driving(car: dict, origin: str, destination: str, us: bool, checked: str) -> dict:
    distance_km = round((car.get("distanceMeters") or 0) / 1000, 1)
    driving = {"duration": _minutes_text(_seconds(car.get("duration"))), "distance_km": distance_km,
               "taxi_note": "Google gives no taxi fares. A taxi takes about this long; check local taxi rates."}
    if us:
        cost = round(distance_km / config.KM_PER_MILE * config.IRS_MILEAGE_RATE_USD, 2)
        driving.update({
            "estimated_cost_per_car_usd": cost,
            "cost_text": f"{fx.money(cost, approx=True)} per car",
            "cost_note": f"Estimate at the IRS 2026 standard mileage rate (${config.IRS_MILEAGE_RATE_USD}/mile), "
                         "which covers fuel and running costs; tolls and parking are not included.",
        })
    else:
        driving["cost_text"] = "No driving cost data outside the US"
    driving["id"] = items.remember("drive", {"type": "drive", "origin": origin, "destination": destination,
                                            "distance_km": distance_km,
                                            "cost_per_car_usd": driving.get("estimated_cost_per_car_usd"),
                                            "checked_at": checked})
    return driving


def search_live_drive(origin: str, destination: str) -> dict:
    """Driving between two cities (no public transport), with an IRS-rate cost per car in
    the US. Raises LiveDataError so callers can fall back to an estimate."""
    response = post(ROUTES_URL, {"origin": {"address": origin}, "destination": {"address": destination},
                                 "travelMode": "DRIVE", "routingPreference": "TRAFFIC_UNAWARE", "languageCode": "en",
                                 "units": "METRIC"}, DRIVE_FIELDS, config.CACHE_TTL_SECONDS["transport"],
                    "Google Routes")
    car = (response.data.get("routes") or [None])[0]
    if not car:
        raise LiveDataError("Google Routes found no driving route between those places.")
    return {**_driving(car, origin, destination, _in_us(origin, destination), checked_at(response)),
            "checked_at": checked_at(response)}


def search_local_transport(origin: str, destination: str, city: str | None = None,
                           depart_at: datetime | None = None) -> dict:
    """Public transport and driving between two places. depart_at is a local
    travel time (no time zone); public transport is then searched for that time.
    Raises LiveDataError so callers can fall back to snapshot data."""
    ends = {"origin": {"address": _address(origin, city)}, "destination": {"address": _address(destination, city)}}
    ttl = config.CACHE_TTL_SECONDS["transport"]
    transit_body = {**ends, "travelMode": "TRANSIT", "computeAlternativeRoutes": True, "languageCode": "en",
                    "units": "METRIC"}
    transit = post(ROUTES_URL, transit_body, TRANSIT_FIELDS, ttl, "Google Routes")
    timing = {"departure_time": None,
              "timetable_note": "Departure times come from the current timetable and will differ on the travel day."}
    if depart_at is not None:
        zone = _time_zone(transit.data)
        utc, reason = _departure_utc(depart_at, zone, datetime.now(timezone.utc)) if zone else (
            None, "The route's time zone is unknown, so the current timetable is shown.")
        if utc:
            transit = post(ROUTES_URL, {**transit_body, "departureTime": utc.strftime("%Y-%m-%dT%H:%M:%SZ")},
                           TRANSIT_FIELDS, ttl, "Google Routes")
            timing = {"departure_time": f"{depart_at:%a %d %b %Y, %H:%M} local time",
                      "timetable_note": f"Times are for {depart_at:%a %d %b %Y}, leaving from {depart_at:%H:%M}."}
        else:
            timing["timetable_note"] = reason
    drive = post(ROUTES_URL, {**ends, "travelMode": "DRIVE", "routingPreference": "TRAFFIC_UNAWARE",
                              "languageCode": "en", "units": "METRIC"}, DRIVE_FIELDS, ttl, "Google Routes")
    try:
        rates = fx.get_rates()
    except LiveDataError:
        rates = None
    options = _transit_options(transit.data, origin, destination, rates, checked_at(transit))
    car = (drive.data.get("routes") or [None])[0]
    driving = _driving(car, origin, destination, _in_us(city, origin, destination), checked_at(drive)) if car else None
    if not options and not driving:
        raise LiveDataError("Google Routes found no route between those places. Try fuller place names.")
    notes = ["Live from Google Maps.", timing["timetable_note"]]
    if rates and any(o["fare_per_person_usd"] is not None for o in options):
        notes.append(rates.note())
    return {
        "source": "live",
        "provider": "Google Routes",
        "checked_at": checked_at(transit),
        "from": ends["origin"]["address"],
        "to": ends["destination"]["address"],
        **timing,
        "public_transport": options,
        "driving": driving,
        "note": " ".join(notes),
    }
