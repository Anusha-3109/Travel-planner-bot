"""Text the app builds for the agent: the trip form's question and the example questions.

Kept apart from app.py so it can be tested without drawing the Streamlit page.
"""

from datetime import date, timedelta

CURRENCIES = ["USD", "EUR", "GBP", "INR", "JPY", "AUD", "CAD", "CHF", "SGD", "AED", "THB"]
LIVE_DAYS_AHEAD = 330  # Google Flights shows fares about 11 months ahead


def example_questions(today: date | None = None) -> list[str]:
    """Examples with dates worked out from today, so the live examples always work."""
    today = today or date.today()
    soon, later = today + timedelta(days=14), today + timedelta(days=30)
    return [
        f"Plan a 4-night trip from London to Rome starting {soon:%d %B %Y} for 2 people with a budget of 1,500.",
        f"Flights from New York to Tokyo on {later:%d %B %Y}.",
        f"Find an Airbnb in Paris from {soon:%d %B} to {soon + timedelta(days=3):%d %B %Y} for 2 people.",
        "Sushi restaurants in Tokyo rated 4.5 or more.",
        "How do I get from Fiumicino Airport to the Colosseum?",
        "Plan a 3-day trip from Washington to Myrtle Beach, 13-15 March 2022, for 1 person with a $1,400 budget "
        "(snapshot data).",
    ]


def trip_question(origin: str, destination: str, start: date, nights: int, people: int, budget: float,
                  currency: str, stay_type: str, house_rule: str | None = None, room_type: str | None = None,
                  cuisines: list[str] | None = None, transportation: str | None = None) -> str:
    """The chat question the trip form sends when you press Plan my trip."""
    end = start + timedelta(days=nights)
    question = (
        f"Plan a {nights}-night trip from {origin} to {destination}, {start:%Y-%m-%d} to {end:%Y-%m-%d}, "
        f"for {people} {'person' if people == 1 else 'people'} with a budget of {currency} {budget:,.0f}. "
        f"Include flights both ways, {'an Airbnb' if stay_type == 'Airbnb' else 'a hotel'}, restaurants for each "
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
