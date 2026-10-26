"""The dashboard's numbers from the request log, and the page itself."""

from datetime import date, datetime

from streamlit.testing.v1 import AppTest

from backend.storage import history
from frontend.pages import dashboard

TODAY = date(2026, 10, 26)


def _row(status="answered", day=TODAY, seconds=4.0, cost=0.002, tools=("search_flights",), reason=None,
         serpapi=1, google=0):
    return {"status": status, "reason": reason, "asked_at": datetime(day.year, day.month, day.day, 12).timestamp(),
            "seconds": seconds, "input_tokens": 1000, "output_tokens": 100, "cost_usd": cost, "tools": list(tools),
            "serpapi": serpapi, "google": google}


ROWS = [_row(seconds=2.0), _row(seconds=6.0, tools=("search_flights", "calculate_trip_cost")),
        _row(day=date(2026, 10, 24), seconds=10.0),
        _row("refused", reason="prompt injection", seconds=0.1, cost=None, tools=(), serpapi=0),
        _row("error", reason="The model is rate limited right now.", cost=None, tools=(), serpapi=0),
        _row("limit", reason="sending too quickly", seconds=None, cost=None, tools=(), serpapi=0)]


def test_summary_counts_answers_waits_tokens_and_cost():
    numbers = dashboard.summary(ROWS)
    assert (numbers["requests"], numbers["answered"]) == (6, 3) and numbers["answered_share"] == 0.5
    assert numbers["median_seconds"] == 6.0  # answered requests only
    assert numbers["input_tokens"] == 6000 and round(numbers["cost_usd"], 4) == 0.006 and numbers["cost_complete"]
    assert numbers["serpapi"] == 3 and dashboard.summary([])["answered_share"] is None


def test_per_day_fills_every_day_of_the_range():
    frame = dashboard.per_day(ROWS, 7, TODAY)
    assert len(frame) == 7 and frame["day"].iloc[-1] == TODAY
    today = frame.iloc[-1]
    assert today["Answered"] == 2 and today["Turned away by the guard"] == 1 and today["Error"] == 1
    assert today["Turned away by a limit"] == 1 and today["p50_seconds"] == 4.0 and today["p95_seconds"] == 6.0
    assert frame.iloc[-3]["Answered"] == 1 and frame.iloc[0]["Answered"] == 0


def test_tool_and_guard_counts():
    assert dashboard.tool_counts(ROWS) == {"search_flights": 3, "calculate_trip_cost": 1}
    reached, refused = dashboard.guard_counts(ROWS)
    assert reached == 4 and refused == {"prompt injection": 1}  # answered and errors reached the agent


def test_page_draws_the_numbers_from_the_log(monkeypatch):
    history.log_request(None, "anthropic/claude-haiku-5.5", "answered", seconds=8.2,
                        usage={"input_tokens": 19985, "output_tokens": 745, "cost_usd": 0.0024},
                        tools=["search_destination_options"])
    history.log_request(None, "anthropic/claude-haiku-5.5", "refused", "prompt injection", 0.1)

    monkeypatch.setattr(dashboard, "knowledge_base", lambda: {
        "cities": 245, "attractions": 9000, "restaurants": 30000, "stays": 18000, "priced_stays": 7416,
        "indexed": 57000})
    monkeypatch.setattr(dashboard, "cached_live_status", lambda: [])

    def page():
        from frontend.pages import dashboard
        dashboard.render()

    at = AppTest.from_function(page, default_timeout=30)
    at.run()
    assert not at.exception
    metrics = {m.label: m.value for m in at.metric}
    assert metrics == {"Requests": "2", "Answered": "50%", "Typical wait": "8.2 s", "Tokens": "21K",
                       "Cost": r"\$0.0024"}
    text = " ".join(m.value for m in at.markdown)
    assert "**245** cities" in text and "1 of 2" in text


def test_page_without_requests_says_so(monkeypatch):
    monkeypatch.setattr(dashboard, "knowledge_base", lambda: {
        "cities": 1, "attractions": 0, "restaurants": 0, "stays": 0, "priced_stays": 0, "indexed": None})

    def page():
        from frontend.pages import dashboard
        dashboard.render()

    at = AppTest.from_function(page, default_timeout=30)
    at.run()
    assert not at.exception and "No questions in the last 30 days" in at.info[0].value
