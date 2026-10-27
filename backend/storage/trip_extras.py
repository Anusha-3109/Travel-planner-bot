"""The logic behind what a traveller adds to a saved trip: the budget tracker's sums and the
packing list's starting items. The data itself is stored by history.py.

The packing list is built with plain rules from the trip (no model call): documents, clothes for
the number of nights, a plug adapter when the destination uses other sockets than home, and
items for what the plan contains (flights, drives, public transport, beaches, the season).
"""

import re
from datetime import date

from backend.travel_data.catalog import load_catalog

# Budget categories, with the plan's cost groups (calculate_trip_cost's totals_text) they compare with.
BUDGET_CATEGORIES = {"Transport": "transportation", "Stay": "accommodation", "Food": "meals",
                     "Sights": "attractions", "Other": None}

# Socket types per country, for the plug adapter (IEC world plugs). Only countries in the catalog.
PLUG_TYPES = {
    "United States": "A/B", "Japan": "A/B", "Thailand": "A/B/C/O", "United Kingdom": "G", "Hong Kong": "G",
    "Singapore": "G", "Italy": "C/F/L", "Austria": "C/F", "Czech Republic": "C/E", "France": "C/E",
    "Germany": "C/F", "Greece": "C/F", "Netherlands": "C/F", "Portugal": "C/F", "Spain": "C/F", "Turkey": "C/F",
}
NORTHERN_WINTER, NORTHERN_SUMMER = {11, 12, 1, 2, 3}, {6, 7, 8}
MAX_CLOTHES_SETS = 7  # past a week, plan to wash rather than pack more


def _amount(text: str | None) -> float | None:
    """'USD 1,272.30' -> 1272.3."""
    match = re.search(r"-?[\d,]+(?:\.\d+)?", text or "")
    return float(match.group().replace(",", "")) if match else None


def planned_by_category(trip: dict) -> dict[str, float | None]:
    """What the saved plan costs per budget category (None for Other, which the plan has no line for)."""
    totals = (trip.get("cost") or {}).get("totals_text") or {}
    return {category: _amount(totals.get(group)) if group else None for category, group in BUDGET_CATEGORIES.items()}


def budget_summary(trip: dict, expenses: list[dict]) -> dict:
    """Planned against spent per category, the totals, what's left of the budget and spent per person."""
    planned = planned_by_category(trip)
    spent = {category: 0.0 for category in BUDGET_CATEGORIES}
    for expense in expenses:
        spent[expense["category"] if expense["category"] in spent else "Other"] += expense["amount"]
    total_spent = round(sum(spent.values()), 2)
    budget = trip.get("budget")
    people = trip.get("people") or 1
    return {
        "currency": trip.get("currency") or "",
        "rows": [{"Category": c, "Planned": planned[c], "Spent": round(spent[c], 2)} for c in BUDGET_CATEGORIES],
        "planned": round(sum(v for v in planned.values() if v is not None), 2),
        "spent": total_spent,
        "budget": budget,
        "left": round(budget - total_spent, 2) if budget is not None else None,
        "per_person": round(total_spent / people, 2),
        "people": people,
    }


def _season(trip: dict, latitude: float | None) -> str | None:
    """'winter', 'summer' or None, from the start month (flipped south of the equator; none in the tropics)."""
    if not trip.get("start") or latitude is None or abs(latitude) < 23.5:
        return None
    month = date.fromisoformat(trip["start"]).month
    winter, summer = (NORTHERN_WINTER, NORTHERN_SUMMER) if latitude >= 0 else (NORTHERN_SUMMER, NORTHERN_WINTER)
    return "winter" if month in winter else "summer" if month in summer else None


def packing_suggestions(trip: dict) -> list[tuple[str, str]]:
    """The starting packing list for a saved trip, as (item, section)."""
    catalog = load_catalog()
    destination = catalog.city_info.get((trip.get("destination") or "").lower())
    origin = catalog.city_info.get((trip.get("origin") or "").lower())
    people = trip.get("people") or 1
    nights = max(len(trip.get("days") or []) - 1, 1)
    kinds = {item["kind"] for day in trip.get("days") or [] for item in day["items"]}
    titles = " ".join(item["title"].lower() for day in trip.get("days") or [] for item in day["items"])
    international = bool(destination and origin and destination.country != origin.country)

    items = [("Passport" + (f"s ({people})" if people > 1 else "") if international or not origin
              else "ID card or driving licence" + (f" ({people})" if people > 1 else ""), "Documents"),
             ("Travel insurance details", "Documents"), ("Bank cards and some cash", "Documents")]
    if "flight" in kinds:
        items += [("Boarding passes", "Documents"), ("Liquids in a clear bag (100 ml each)", "Bags")]
    if "drive" in kinds:
        items.append(("Driving licence", "Documents"))
    if "transit" in kinds:
        items.append(("Public transport app or card", "Getting around"))
    sets = min(nights + 1, MAX_CLOTHES_SETS)
    items += [(f"Underwear and socks ({sets} sets)", "Clothes"), (f"Tops ({sets})", "Clothes"),
              ("Comfortable walking shoes", "Clothes"), ("Sleepwear", "Clothes"),
              ("Toothbrush and toiletries", "Toiletries"), ("Medicines you take", "Toiletries"),
              ("Phone charger", "Electronics")]
    if destination and destination.country in PLUG_TYPES and (
            not origin or PLUG_TYPES.get(origin.country) != PLUG_TYPES[destination.country]):
        items.append((f"Plug adapter for {destination.country} (type {PLUG_TYPES[destination.country]})",
                      "Electronics"))
    season = _season(trip, destination.latitude if destination else None)
    if season == "winter":
        items += [("Warm jacket", "Clothes"), ("Umbrella or rain jacket", "Clothes")]
    elif season == "summer":
        items += [("Sun cream", "Toiletries"), ("Sunglasses and a hat", "Clothes")]
    if "beach" in titles:
        items += [("Swimwear", "Clothes"), ("Beach towel", "Bags")]
    if nights >= MAX_CLOTHES_SETS:
        items.append(("Travel laundry soap", "Toiletries"))
    return items
