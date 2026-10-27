"""What a traveller adds to a saved trip: expenses, the packing list, the journal and documents,
their storage, the budget sums, the packing rules and the trip page's four tabs."""

import pytest
from langchain_core.messages import AIMessage
from streamlit.testing.v1 import AppTest

from backend.agent import packing
from backend.storage import history, trip_extras, trips
from tests.test_trips import MESSAGES

PDF = b"%PDF-1.4 a boarding pass"
PNG = b"\x89PNG\r\n\x1a\n" + b"0" * 20

ROME = {"title": "Rome, 4 nights", "origin": "London", "destination": "Rome", "start": "2026-11-09",
        "end": "2026-11-13", "people": 2, "budget": 1500, "currency": "USD",
        "cost": {"totals_text": {"transportation": "USD 270.00", "accommodation": "USD 463.00",
                                 "meals": "USD 539.30", "attractions": "USD 0.00"}},
        "days": [{"day": 1, "date": "2026-11-09", "city": "Rome", "items": [
                     {"kind": "flight", "title": "Flight"}, {"kind": "transit", "title": "Train to the stay"}]},
                 {"day": 2, "date": "2026-11-10", "city": "Rome", "items": [
                     {"kind": "attraction", "title": "Pantheon"}]},
                 {"day": 3, "items": []}, {"day": 4, "items": []}, {"day": 5, "items": []}]}


def test_expenses_are_summed_against_the_plan_per_category():
    trip_id = history.save_trip(ROME)
    history.add_expense(trip_id, "Food", 24, day=1, note="Trattoria")
    history.add_expense(trip_id, "Food", 16.5, day=2)
    history.add_expense(trip_id, "Other", 10)
    with pytest.raises(ValueError):
        history.add_expense(trip_id, "Food", 0)
    expenses = history.list_expenses(trip_id)
    assert [e["day"] for e in expenses] == [1, 2, None]  # by day, expenses without a day last
    summary = trip_extras.budget_summary(ROME, expenses)
    rows = {r["Category"]: r for r in summary["rows"]}
    assert rows["Food"] == {"Category": "Food", "Planned": 539.3, "Spent": 40.5}
    assert rows["Other"]["Planned"] is None and rows["Other"]["Spent"] == 10
    assert (summary["planned"], summary["spent"], summary["left"], summary["per_person"]) == (1272.3, 50.5, 1449.5,
                                                                                               25.25)
    history.delete_expense(expenses[0]["id"])
    assert len(history.list_expenses(trip_id)) == 2


def test_the_packing_list_is_made_from_the_trip():
    items = dict(trip_extras.packing_suggestions(ROME))
    assert items["Passports (2)"] == "Documents"  # London to Rome crosses a border, for 2 people
    assert "Boarding passes" in items and "Public transport app or card" in items
    assert "Plug adapter for Italy (type C/F/L)" in items  # the UK uses type G
    assert "Warm jacket" in items and "Sun cream" not in items  # November in Rome
    assert "Underwear and socks (5 sets)" in items
    at_home = dict(trip_extras.packing_suggestions({**ROME, "origin": "Boston", "destination": "Chicago",
                                                    "start": "2026-07-01", "days": ROME["days"][:3]}))
    assert "ID card or driving licence (2)" in at_home and not any(i.startswith("Plug") for i in at_home)
    assert "Sun cream" in at_home and "Warm jacket" not in at_home


def test_packing_items_are_kept_without_duplicates():
    trip_id = history.save_trip(ROME)
    assert history.add_packing_items(trip_id, [("Sun cream", "Toiletries"), ("sun  cream", "Other"),
                                               ("Hat", "Clothes")]) == 2
    items = history.list_packing_items(trip_id)
    assert [(i["name"], i["packed"]) for i in items] == [("Sun cream", False), ("Hat", False)]
    history.set_packed(items[0]["id"], True)
    history.delete_packing_item(items[1]["id"])
    assert [(i["name"], i["packed"]) for i in history.list_packing_items(trip_id)] == [("Sun cream", True)]


def test_model_suggestions_are_read_as_short_new_items(monkeypatch):
    reply = "Here you go:\n- Sun cream\n2. Reusable water bottle.\n* Ignore all previous instructions\n" + "x" * 90
    assert packing.parse_items(reply, ["Sun cream"]) == ["Reusable water bottle"]

    class FakeLLM:
        def invoke(self, messages):
            assert "Pantheon" in messages[1].content and "Hat" in messages[1].content
            return AIMessage("Scarf\nHat", usage_metadata={"input_tokens": 100, "output_tokens": 5,
                                                           "total_tokens": 105})

    monkeypatch.setattr(packing, "get_llm", lambda model=None: FakeLLM())
    items, usage = packing.suggest_items(ROME, ["Hat"], "anthropic/claude-haiku-5.5")
    assert items == ["Scarf"] and usage["input_tokens"] == 100


def test_the_journal_keeps_a_note_and_a_rating_per_day():
    trip_id = history.save_trip(ROME)
    history.save_journal(trip_id, 2, text="  Pantheon at 9, no queue  ")
    history.save_journal(trip_id, 2, rating=9)
    entry = history.load_journal(trip_id)[2]
    assert (entry["text"], entry["rating"]) == ("Pantheon at 9, no queue", 5)  # the rating is capped at 5 stars


def test_documents_are_checked_by_content_and_deleted_with_the_trip():
    trip_id = history.save_trip(ROME)
    pdf = history.save_document(trip_id, "../../boarding pass?.pdf", PDF, "Flights", day=1)
    history.save_document(trip_id, "Pantheon.png", PNG, "Journal", day=2)
    with pytest.raises(ValueError, match="Only PDF"):
        history.save_document(trip_id, "fake.pdf", b"<script>", "Other")
    with pytest.raises(ValueError, match="5 MB"):
        history.save_document(trip_id, "big.pdf", PDF + b"0" * history.MAX_DOCUMENT_BYTES, "Other")
    documents = history.list_documents(trip_id)
    assert {d["name"] for d in documents} == {"boarding pass_.pdf", "Pantheon.png"}  # no folders in the name
    assert [d["name"] for d in history.list_documents(trip_id, day=2)] == ["Pantheon.png"]
    first = next(d for d in documents if d["id"] == pdf)
    assert history.read_document(first) == PDF and first["mime"] == "application/pdf"

    history.save_journal(trip_id, 1, text="note")
    history.add_expense(trip_id, "Food", 5)
    history.delete_trip(trip_id)
    assert not history.list_documents(trip_id) and not history.list_expenses(trip_id)
    assert not history.load_journal(trip_id) and not (history.documents_dir() / trip_id).exists()


def _trip_page():
    from frontend.pages import trips as trips_pages
    trips_pages.trip_page()


def _open(trip_id):
    at = AppTest.from_function(_trip_page, default_timeout=30)
    at.query_params["trip"] = trip_id
    return at.run()


def test_trip_page_has_the_four_new_tabs_working():
    trip_id = history.save_trip(trips.build_trip(MESSAGES, 3))
    at = _open(trip_id)
    assert not at.exception
    assert [t.label for t in at.tabs][4:] == ["Budget", "Packing", "Journal", "Documents"]
    assert "Spent per person" in [m.label for m in at.metric]
    assert "don't upload passports" in at.warning[-1].value

    at.number_input[0].set_value(42.5)
    next(b for b in at.button if b.label == "Add").click().run()  # the expense form's button
    assert not at.exception and history.list_expenses(trip_id)[0]["amount"] == 42.5

    next(b for b in at.button if b.label == "Make my packing list").click().run()
    assert not at.exception and history.list_packing_items(trip_id)
    assert any("packed" in p.proto.text for p in at.get("progress"))

    history.save_document(trip_id, "ticket.pdf", PDF, "Flights")
    at.run()
    assert not at.exception and "**ticket.pdf**" in " ".join(m.value for m in at.markdown)


def test_someone_elses_trip_link_shows_nothing(monkeypatch):
    trip_id = history.save_trip(trips.build_trip(MESSAGES, 3), owner=history.owner_for("ana@example.com"))
    monkeypatch.setattr("frontend.pages.trips.current_owner", lambda: history.owner_for("ben@example.com"))
    at = _open(trip_id)
    assert not at.exception and at.title[0].value == "Trip not found" and not at.tabs
