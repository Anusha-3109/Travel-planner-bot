"""More packing-list items for a saved trip, from the model ("Suggest more" on the Packing tab).

The rules in storage/trip_extras.py make the starting list for free; this asks the model once
for items those rules can't know about (the sights in the plan, the city's weather, the kind of
trip). The reply is read as plain lines only: at most MAX_ITEMS short items, and nothing that
looks like instructions is kept.
"""

import re

from langchain_core.messages import HumanMessage, SystemMessage

from backend import config
from backend.agent.llm import get_llm, message_usage
from backend.security.validation import looks_like_prompt_injection

MAX_ITEMS = 10
MAX_ITEM_CHARS = 80
SYSTEM = ("You suggest packing-list items for a trip. Reply with up to 10 items that aren't on the list yet, "
          "one per line, each a few words, with no numbering, headings or explanations.")


def _trip_text(trip: dict, have: list[str]) -> str:
    sights = sorted({item["title"] for day in trip.get("days") or [] for item in day["items"]
                     if item["kind"] == "attraction"})[:15]
    return (f"Trip: {trip.get('title')}, from {trip.get('origin') or 'unknown'} to {trip.get('destination')}, "
            f"{trip.get('start') or 'dates unknown'} to {trip.get('end') or ''}, {trip.get('people') or 1} traveller(s).\n"
            f"Sights in the plan: {', '.join(sights) or 'none'}.\n"
            f"Already on the list: {', '.join(have) or 'nothing'}.")


def parse_items(text: str, have: list[str]) -> list[str]:
    """The model's reply as clean, new items: bullets and numbers removed, and duplicates, headings
    ("Here you go:"), long lines and instruction-like lines dropped."""
    seen, items = {name.lower() for name in have}, []
    for line in text.splitlines():
        item = re.sub(r"^\s*(?:[-*•]|\d+[.)])\s*", "", line).strip().rstrip(".")
        if (item and not item.endswith(":") and len(item) <= MAX_ITEM_CHARS and item.lower() not in seen
                and not looks_like_prompt_injection(item)):
            seen.add(item.lower())
            items.append(item)
    return items[:MAX_ITEMS]


def suggest_items(trip: dict, have: list[str], model: str = config.OPENROUTER_MODEL) -> tuple[list[str], dict]:
    """New items for the trip and the call's usage (tokens and cost)."""
    reply = get_llm(model).invoke([SystemMessage(SYSTEM), HumanMessage(_trip_text(trip, have))])
    return parse_items(str(reply.content), have), message_usage(model, reply)
