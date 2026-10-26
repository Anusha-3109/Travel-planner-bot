"""The trip request the app sends to the agent when the trip form is filled in.

The evaluation builds its questions the same way, so it lives with the agent.
"""

from datetime import date, timedelta


def trip_question(origin: str, destination: str, start: date, nights: int, people: int, budget: float,
                  currency: str, stay_type: str, house_rule: str | None = None, room_type: str | None = None,
                  cuisines: list[str] | None = None, transportation: str | None = None) -> str:
    """The chat question the trip form sends when you press Plan my trip."""
    end = start + timedelta(days=nights)
    question = (
        f"Plan a {nights}-night trip from {origin} to {destination}, {start:%Y-%m-%d} to {end:%Y-%m-%d}, "
        f"for {people} {'person' if people == 1 else 'people'} with a budget of {currency} {budget:,.0f}. "
        f"Include {'transport other than flights' if transportation == 'no flight' else 'flights'} both ways, "
        f"{'an Airbnb' if stay_type == 'Airbnb' else 'a hotel'}, restaurants for each "
        f"day and how to get from the airport to the stay."
    )
    rules = []
    if house_rule:
        rules.append(f"the place to stay must allow {house_rule}")
    if room_type:
        rules.append(f"the room type must be {room_type}")
    if cuisines:
        rules.append(f"meals must include {', '.join(cuisines)} cuisine")
    if transportation:
        rules.append(f"transportation: {transportation}")
    return question + (f" Constraints: {'; '.join(rules)}." if rules else "")
