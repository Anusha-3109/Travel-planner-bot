"""Saved chats and the request log (history.py), in a temporary database."""

import time
from datetime import date, datetime

import pytest

from backend.storage import history


def test_chats_are_saved_loaded_renamed_bookmarked_and_deleted():
    chat_id = history.create_chat("  Plan a 4-night trip from London to Rome starting 09 November 2026 for 2 people  ")
    history.save_messages(chat_id, [{"role": "user", "content": "Hi"}, {"role": "assistant", "content": "Hello"}])
    chat = history.load_chat(chat_id)
    assert len(chat["title"]) == history.TITLE_CHARS and chat["title"].startswith("Plan a 4-night trip from London")
    assert chat["title"].endswith("…")
    assert [m["content"] for m in chat["messages"]] == ["Hi", "Hello"] and not chat["bookmarked"]
    history.rename_chat(chat_id, "Rome trip")
    history.set_bookmark(chat_id, True)
    assert history.list_chats()[0] | {"created_at": 0, "updated_at": 0} == {
        "id": chat_id, "title": "Rome trip", "bookmarked": True, "created_at": 0, "updated_at": 0, "mode": "plan"}
    history.delete_chat(chat_id)
    assert history.load_chat(chat_id) is None and history.list_chats() == []


def test_chats_are_grouped_by_day_with_bookmarks_first():
    def chat(day: date, bookmarked=False):
        return {"id": str(day), "title": "t", "bookmarked": bookmarked,
                "updated_at": datetime(day.year, day.month, day.day, 12).timestamp()}
    today = date(2026, 10, 26)
    groups = history.group_chats([chat(today), chat(date(2026, 10, 25)), chat(date(2026, 10, 22)),
                                  chat(date(2026, 9, 1)), chat(date(2026, 9, 2), bookmarked=True)], today)
    assert list(groups) == ["Bookmarked", "Today", "Yesterday", "Previous 7 days", "Older"]
    assert [c["id"] for c in groups["Older"]] == ["2026-09-01"]


def test_request_log_keeps_rows_after_a_chat_is_deleted():
    chat_id = history.create_chat("Museums in Boston?")
    history.log_request(chat_id, "anthropic/claude-haiku-5.5", "answered", seconds=4.2,
                        usage={"input_tokens": 900, "output_tokens": 100, "cost_usd": 0.0015},
                        tools=["search_destination_options"], searches={"serpapi": 0, "google": 1})
    history.log_request(None, "anthropic/claude-haiku-5.5", "refused", "prompt injection", 0.1)
    history.delete_chat(chat_id)
    answered, refused = history.requests_since(1)
    assert answered["chat_id"] is None and answered["tools"] == ["search_destination_options"]
    assert answered["google"] == 1 and answered["cost_usd"] == 0.0015
    assert (refused["status"], refused["reason"]) == ("refused", "prompt injection")
    with pytest.raises(ValueError):
        history.log_request(None, "m", "maybe")


def test_old_requests_are_outside_the_range(monkeypatch):
    real_time = time.time
    monkeypatch.setattr(history.time, "time", lambda: real_time() - 40 * 86400)
    history.log_request(None, "m", "answered")
    monkeypatch.setattr(history.time, "time", real_time)
    history.log_request(None, "m", "error", "unexpected error")
    assert [r["status"] for r in history.requests_since(30)] == ["error"]
    assert len(history.requests_since(90)) == 2


def test_delete_all_clears_chats_and_the_log():
    history.create_chat("Hi there")
    history.log_request(None, "m", "answered")
    history.delete_all()
    assert history.list_chats() == [] and history.requests_since(365) == []


def test_each_owner_sees_only_their_own_chats_trips_and_log():
    ana, ben = history.owner_for("Ana@Example.com "), history.owner_for("ben@example.com")
    assert ana == history.owner_for("ana@example.com") and ana.startswith("user-") and "ana" not in ana
    chat = history.create_chat("Museums in Rome", owner=ana)
    trip = history.save_trip({"title": "Rome, 2 nights"}, chat, owner=ana)
    history.log_request(chat, "model", "answered", owner=ana)
    assert [c["id"] for c in history.list_chats(ana)] == [chat] and history.list_chats(ben) == []
    assert history.load_chat(chat, ben) is None and history.load_trip(trip, ben) is None  # a guessed id finds nothing
    assert len(history.requests_since(1, ana)) == 1 and history.requests_since(1, ben) == []
    history.delete_all(ben)  # deletes only Ben's data
    assert history.load_chat(chat, ana) and history.load_trip(trip, ana)


def test_data_saved_before_sign_in_goes_to_the_author():
    chat = history.create_chat("Saved without sign-in")
    trip = history.save_trip({"title": "Boston, 2 nights"})
    author = history.owner_for("author@example.com")
    assert history.claim_local_data(author) == 2
    assert history.load_chat(chat, author) and history.load_trip(trip, author)
    assert history.list_chats() == [] and history.list_trips() == []
