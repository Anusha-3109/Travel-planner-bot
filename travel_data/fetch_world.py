"""Fetch current data for the European and Asian cities in world_cities.py.

Run:  python -m travel_data.fetch_world            (all cities)
      python -m travel_data.fetch_world Tokyo Rome (some cities)

Sources, all free and openly licensed:
- Places to stay: Inside Airbnb (CC BY 4.0, https://insideairbnb.com), the most
  reviewed listings with a price. Prices are converted to USD.
- Exchange rates: European Central Bank daily reference rates.
- Restaurants and attractions: OpenStreetMap via the Overpass API
  (ODbL, (c) OpenStreetMap contributors).

Each city is written to data/world/<city>.json. Downloads take a few minutes.
"""

import argparse
import json
import re
import sys
import time
import xml.etree.ElementTree as ET
from datetime import datetime, timezone

import pandas as pd
import requests

import config
from travel_data.catalog import great_circle_km
from travel_data.world_cities import WORLD_CITIES, WorldCity

USER_AGENT = "travel-planner-bot/0.1 (student project; uses Overpass politely)"
ECB_URL = "https://www.ecb.europa.eu/stats/eurofxref/eurofxref-daily.xml"
OVERPASS_URL = "https://overpass-api.de/api/interpreter"
MAX_STAYS = 150
MAX_RESTAURANTS = 250
MAX_ATTRACTIONS = 120
RESTAURANT_RADIUS_M = 5000
ATTRACTION_RADIUS_M = 10000
MIN_REVIEWS = 10
ATTRACTION_KINDS = ("attraction", "museum", "gallery", "viewpoint", "zoo", "theme_park", "aquarium")
LISTING_COLUMNS = ["name", "listing_url", "room_type", "accommodates", "price", "minimum_nights",
                   "number_of_reviews", "review_scores_rating", "latitude", "longitude"]


def fetch_usd_rates() -> tuple[dict[str, float], str]:
    """USD per one unit of each currency, from the ECB's EUR-based reference rates."""
    response = requests.get(ECB_URL, timeout=30, headers={"User-Agent": USER_AGENT})
    response.raise_for_status()
    root = ET.fromstring(response.content)
    per_eur, day = {"EUR": 1.0}, ""
    for element in root.iter():
        if element.get("time"):
            day = element.get("time")
        if element.get("currency"):
            per_eur[element.get("currency")] = float(element.get("rate"))
    return {currency: per_eur["USD"] / rate for currency, rate in per_eur.items()}, day


def _price(value) -> float | None:
    text = re.sub(r"[^\d.]", "", str(value))
    return float(text) if text else None


def fetch_stays(city: WorldCity, usd_per_unit: float) -> list[dict]:
    listings = pd.read_csv(city.listings_url, compression="gzip", usecols=LISTING_COLUMNS,
                           storage_options={"User-Agent": USER_AGENT})
    listings["price_local"] = listings["price"].map(_price)
    listings = listings.dropna(subset=["price_local", "minimum_nights", "accommodates", "number_of_reviews"])
    listings = listings[(listings["price_local"] > 0) & (listings["number_of_reviews"] >= MIN_REVIEWS)
                        & listings["name"].notna() & (listings["accommodates"] > 0)]
    if city.max_km:  # areas wider than the city (a county or a state): keep listings near the centre
        distance = listings.apply(lambda row: great_circle_km(city.latitude, city.longitude, row["latitude"],
                                                              row["longitude"]), axis=1)
        listings = listings[distance <= city.max_km]
    listings = listings.sort_values("number_of_reviews", ascending=False).head(MAX_STAYS)
    return [
        {
            "name": " ".join(str(row.name).split()),
            "price": round(row.price_local * usd_per_unit, 2),
            "price_local": row.price_local,
            "room_type": row.room_type,
            "minimum_nights": int(row.minimum_nights),
            "maximum_occupancy": int(row.accommodates),
            "rating": None if pd.isna(row.review_scores_rating) else round(float(row.review_scores_rating), 2),
            "reviews": int(row.number_of_reviews),
            "url": row.listing_url,
        }
        for row in listings.itertuples()
    ]


def _overpass(query: str) -> list[dict]:
    for attempt in range(4):
        response = requests.post(OVERPASS_URL, data={"data": query}, timeout=180,
                                 headers={"User-Agent": USER_AGENT, "Accept": "application/json"})
        if response.status_code in (429, 502, 503, 504):
            time.sleep(30 * (attempt + 1))  # the public server is shared; back off and retry
            continue
        response.raise_for_status()
        return response.json()["elements"]
    raise RuntimeError("The Overpass API is busy. Try again later.")


def _name(tags: dict) -> str:
    return " ".join((tags.get("name:en") or tags.get("name") or "").split())


def _address(tags: dict) -> str:
    street = " ".join(filter(None, [tags.get("addr:housenumber"), tags.get("addr:street")]))
    return ", ".join(filter(None, [street, tags.get("addr:postcode"), tags.get("addr:city")]))


def _ranked(elements: list[dict], limit: int, *extra_keys: str) -> list[dict]:
    """Pick the best-documented places, preferring names written in Latin script
    so they are readable in English answers. De-duplicates by name."""
    seen, picked = set(), []

    def score(element: dict) -> tuple:
        tags = element.get("tags", {})
        return (bool(re.search(r"[A-Za-z]", _name(tags))), *(key in tags for key in extra_keys),
                "wikidata" in tags, "website" in tags, len(tags))

    for element in sorted(elements, key=score, reverse=True):
        name = _name(element.get("tags", {}))
        if name and name.lower() not in seen:
            seen.add(name.lower())
            picked.append(element)
        if len(picked) == limit:
            break
    return picked


def fetch_restaurants(city: WorldCity) -> list[dict]:
    query = (f'[out:json][timeout:120];nwr["amenity"="restaurant"]["name"]'
             f'(around:{RESTAURANT_RADIUS_M},{city.latitude},{city.longitude});out center tags;')
    return [
        {
            "name": _name(e["tags"]),
            "cuisines": [c.strip().replace("_", " ").title() for c in e["tags"].get("cuisine", "").split(";") if c.strip()],
            "address": _address(e["tags"]),
            "website": e["tags"].get("website", ""),
        }
        for e in _ranked(_overpass(query), MAX_RESTAURANTS, "cuisine")
    ]


def fetch_attractions(city: WorldCity) -> list[dict]:
    kinds = "|".join(ATTRACTION_KINDS)
    query = (f'[out:json][timeout:120];nwr["tourism"~"^({kinds})$"]["name"]'
             f'(around:{ATTRACTION_RADIUS_M},{city.latitude},{city.longitude});out center tags;')
    attractions = []
    for e in _ranked(_overpass(query), MAX_ATTRACTIONS):
        point = e.get("center") or e
        attractions.append({
            "name": _name(e["tags"]),
            "kind": e["tags"]["tourism"].replace("_", " "),
            "address": _address(e["tags"]),
            "website": e["tags"].get("website", ""),
            "phone": e["tags"].get("phone", ""),
            "latitude": point.get("lat"),
            "longitude": point.get("lon"),
        })
    return attractions


def fetch_city(city: WorldCity, rates: dict[str, float], rates_date: str) -> dict:
    data = {
        "city": city.name, "country": city.country, "region": city.region,
        "latitude": city.latitude, "longitude": city.longitude,
        "currency": city.currency, "usd_per_unit": rates[city.currency], "rates_date": rates_date,
        "airbnb_scrape_date": city.scrape_date,
        "fetched_at": datetime.now(timezone.utc).strftime("%Y-%m-%d"),
        "accommodations": fetch_stays(city, rates[city.currency]),
    }
    data["restaurants"] = fetch_restaurants(city)
    time.sleep(5)  # be polite to the shared Overpass server
    data["attractions"] = fetch_attractions(city)
    return data


def main(names: list[str]) -> None:
    wanted = {n.lower() for n in names}
    cities = [c for c in WORLD_CITIES if not wanted or c.name.lower() in wanted]
    if not cities:
        sys.exit(f"Unknown city. Choose from: {', '.join(c.name for c in WORLD_CITIES)}")
    rates, rates_date = fetch_usd_rates()
    config.WORLD_DIR.mkdir(parents=True, exist_ok=True)
    for city in cities:
        print(f"{city.name}: fetching...", flush=True)
        try:
            data = fetch_city(city, rates, rates_date)
        except Exception as error:  # keep going so one failing city doesn't block the rest
            print(f"{city.name}: failed ({error})", flush=True)
            continue
        (config.WORLD_DIR / f"{city.slug}.json").write_text(json.dumps(data, ensure_ascii=False, indent=1),
                                                             encoding="utf-8")
        prices = sorted(s["price"] for s in data["accommodations"])
        median = prices[len(prices) // 2] if prices else 0
        print(f"{city.name}: {len(data['accommodations'])} stays (median ${median:.0f}/night), "
              f"{len(data['restaurants'])} restaurants, {len(data['attractions'])} attractions", flush=True)
        time.sleep(5)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("cities", nargs="*", help="City names (default: all)")
    main(parser.parse_args().cities)
