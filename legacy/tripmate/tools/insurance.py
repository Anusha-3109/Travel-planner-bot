"""Illustrative travel insurance premium calculator.

The pricing model is a simplified teaching example based on the factors
described in the knowledge base (trip cost, age, length and trip type). It is
not an insurer's quote.
"""

import json

from langchain_core.tools import tool

from security.validation import (
    InputValidationError,
    validate_age,
    validate_trip_cost,
    validate_trip_days,
    validate_trip_type,
)

BASE_RATE = 0.05  # 5% of the insured trip cost
MINIMUM_PREMIUM_USD = 25.0
TRIP_TYPE_FACTORS = {"domestic": 0.8, "international": 1.0}
AGE_BANDS = [(34, 1.0), (54, 1.25), (69, 1.7), (110, 2.4)]  # (max age, factor)
RECOMMENDED_MEDICAL_COVER_USD = {"domestic": 50_000, "international": 100_000}


def age_factor(age: int) -> float:
    return next(factor for max_age, factor in AGE_BANDS if age <= max_age)


def duration_factor(days: int) -> float:
    return min(1.0 + 0.01 * days, 1.5)


def calculate_premium(trip_cost_usd: float, trip_days: int, traveler_age: int, trip_type: str) -> dict:
    cost = validate_trip_cost(trip_cost_usd)
    days = validate_trip_days(trip_days)
    age = validate_age(traveler_age)
    kind = validate_trip_type(trip_type)

    factors = {
        "base_rate": BASE_RATE,
        "trip_type": TRIP_TYPE_FACTORS[kind],
        "age": age_factor(age),
        "duration": round(duration_factor(days), 2),
    }
    premium = cost * factors["base_rate"] * factors["trip_type"] * factors["age"] * factors["duration"]
    premium = max(premium, MINIMUM_PREMIUM_USD)
    return {
        "inputs": {"trip_cost_usd": cost, "trip_days": days, "traveler_age": age, "trip_type": kind},
        "factors": factors,
        "estimated_premium_usd": round(premium, 2),
        "premium_as_percent_of_trip_cost": round(premium / cost * 100, 1),
        "suggested_minimum_medical_cover_usd": RECOMMENDED_MEDICAL_COVER_USD[kind],
        "note": "Illustrative estimate from a simplified model, not a quote. Compare real policies and read the wording.",
    }


@tool
def calculate_travel_insurance_estimate(trip_cost_usd: float, trip_days: int, traveler_age: int,
                                        trip_type: str) -> str:
    """Estimate a travel insurance premium in USD for one traveller. trip_type must be
    'domestic' or 'international'. Ask the user for any value you don't know."""
    try:
        return json.dumps(calculate_premium(trip_cost_usd, trip_days, traveler_age, trip_type))
    except InputValidationError as error:
        return json.dumps({"error": str(error)})
