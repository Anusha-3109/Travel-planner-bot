"""User input validation and basic prompt-injection screening.

Every function raises InputValidationError with a message that is safe to show
to the user. Tools call these too, because the LLM chooses tool arguments and
they must be checked like any other untrusted input.
"""

import re
from datetime import date

MAX_QUESTION_CHARS = 1000
MAX_PEOPLE = 20
MAX_TRIP_DAYS = 30
PLACE_CATEGORIES = ("attraction", "restaurant", "accommodation")

_CITY_PATTERN = re.compile(r"^[A-Za-zÀ-ÖØ-öø-ÿ' .\-]{2,60}$")
_CONTROL_CHARS = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]")
_INJECTION_PATTERNS = [
    re.compile(r"\b(ignore|disregard|forget)\b.{0,30}\b(previous|prior|above|earlier|system)\b.{0,20}\b(instructions?|prompts?|rules|messages)\b", re.I),
    re.compile(r"\b(reveal|show|print|repeat)\b.{0,20}\b(your|the)\b.{0,10}\b(system prompt|instructions|hidden prompt)\b", re.I),
    re.compile(r"\byou are now\b.{0,30}\b(developer mode|dan|jailbroken|unrestricted)\b", re.I),
    re.compile(r"\b(act|pretend)\b.{0,20}\bwithout (any )?(restrictions|rules|guidelines)\b", re.I),
]


class InputValidationError(ValueError):
    """Raised when input fails validation. The message is safe to show to users."""


def looks_like_prompt_injection(text: str) -> bool:
    return any(pattern.search(text) for pattern in _INJECTION_PATTERNS)


def validate_question(text: object) -> str:
    if not isinstance(text, str):
        raise InputValidationError("Please enter your question as text.")
    cleaned = text.strip()
    if not cleaned:
        raise InputValidationError("Please enter a question.")
    if len(cleaned) > MAX_QUESTION_CHARS:
        raise InputValidationError(
            f"Your message is too long ({len(cleaned)} characters). Please keep it under {MAX_QUESTION_CHARS}."
        )
    if _CONTROL_CHARS.search(cleaned):
        raise InputValidationError("Your message contains unsupported characters.")
    if looks_like_prompt_injection(cleaned):
        raise InputValidationError(
            "That message looks like an attempt to change the assistant's instructions, so it was blocked. "
            "Please ask about your trip: flights, places to stay, restaurants or attractions."
        )
    return cleaned


def validate_city(name: object) -> str:
    cleaned = " ".join(str(name).split())
    if not _CITY_PATTERN.match(cleaned):
        raise InputValidationError(f"'{name}' doesn't look like a city name.")
    return cleaned


def validate_keyword(value: object, label: str) -> str | None:
    """A short free-text search word such as a cuisine ("sushi", "vegan", "dim sum")."""
    if value in (None, "", "any"):
        return None
    cleaned = " ".join(str(value).split())
    if not _CITY_PATTERN.match(cleaned) or len(cleaned) > 40:
        raise InputValidationError(f"{label} must be a few words of letters, e.g. 'Italian' or 'sushi'.")
    return cleaned


def validate_place(value: object, label: str = "Place") -> str:
    """A place name or address, such as 'Fiumicino Airport' or 'Via del Corso 12, Rome'."""
    cleaned = " ".join(str(value or "").split())
    if not 2 <= len(cleaned) <= 150 or _CONTROL_CHARS.search(cleaned) or looks_like_prompt_injection(cleaned):
        raise InputValidationError(f"{label} must be a place name or address of 2-150 characters.")
    if not re.search(r"[^\W\d_]", cleaned):
        raise InputValidationError(f"{label} must contain letters, e.g. 'Colosseum' or 'Fiumicino Airport'.")
    return cleaned


def validate_date(value: object) -> str:
    try:
        return date.fromisoformat(str(value).strip()).isoformat()
    except ValueError:
        raise InputValidationError(f"'{value}' isn't a valid date. Use the YYYY-MM-DD format, e.g. 2026-11-10.") from None


def _number(value: object, label: str) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        raise InputValidationError(f"{label} must be a number.") from None


def validate_budget(value: object) -> float:
    budget = _number(value, "Budget")
    if not 0 < budget <= 1_000_000:
        raise InputValidationError("Budget must be between 0 and 1,000,000 USD.")
    return budget


def validate_max_price(value: object, label: str = "Maximum price") -> float | None:
    if value in (None, ""):
        return None
    price = _number(value, label)
    if price <= 0:
        raise InputValidationError(f"{label} must be more than 0.")
    return price


def validate_rating(value: object) -> float | None:
    if value in (None, ""):
        return None
    rating = _number(value, "Rating")
    if not 0 <= rating <= 5:
        raise InputValidationError("Rating must be between 0 and 5.")
    return rating


def validate_people(value: object) -> int:
    try:
        people = int(value)
    except (TypeError, ValueError):
        raise InputValidationError("Number of travellers must be a whole number.") from None
    if not 1 <= people <= MAX_PEOPLE:
        raise InputValidationError(f"Number of travellers must be between 1 and {MAX_PEOPLE}.")
    return people


def validate_trip_days(value: object) -> int:
    try:
        days = int(value)
    except (TypeError, ValueError):
        raise InputValidationError("Trip length must be a whole number of days.") from None
    if not 1 <= days <= MAX_TRIP_DAYS:
        raise InputValidationError(f"Trip length must be between 1 and {MAX_TRIP_DAYS} days.")
    return days


def validate_choice(value: object, options, label: str) -> str | None:
    """A case-insensitive pick from a fixed list. Empty values mean "no preference"."""
    if value in (None, "", "any"):
        return None
    choice = " ".join(str(value).split()).lower()
    by_lower = {option.lower(): option for option in options}
    if choice not in by_lower:
        raise InputValidationError(f"{label} must be one of: {', '.join(options)}.")
    return by_lower[choice]


def validate_category(value: object) -> str | None:
    return validate_choice(value, PLACE_CATEGORIES, "Category")
