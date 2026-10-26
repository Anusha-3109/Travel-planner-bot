"""Saved chats, saved trips and the request log, in a SQLite file on this computer.

Chats keep every message with its tool results (so result cards can be drawn
again), the model and currency used, and a bookmark flag. Saved trips keep a
costed plan with its prices and places, for the trip page. The request log has
one row per question: when it was asked, how long the answer took, whether it
was answered, refused or failed (and why), tokens, cost, tool calls and live
searches. The dashboard is built from it.

The file (.history/chats.sqlite3) is git-ignored. No API keys are stored.
"""

import json
import sqlite3
import time
import uuid
from contextlib import closing
from datetime import date, datetime, timedelta

import config

TITLE_CHARS = 60
SCHEMA = """
CREATE TABLE IF NOT EXISTS chats (
    id TEXT PRIMARY KEY, title TEXT NOT NULL, created_at REAL NOT NULL, updated_at REAL NOT NULL,
    bookmarked INTEGER NOT NULL DEFAULT 0, messages TEXT NOT NULL DEFAULT '[]');
CREATE TABLE IF NOT EXISTS requests (
    id INTEGER PRIMARY KEY AUTOINCREMENT, chat_id TEXT, asked_at REAL NOT NULL, model TEXT,
    status TEXT NOT NULL, reason TEXT, seconds REAL, input_tokens INTEGER DEFAULT 0, output_tokens INTEGER DEFAULT 0,
    cost_usd REAL, tools TEXT NOT NULL DEFAULT '[]', serpapi INTEGER DEFAULT 0, google INTEGER DEFAULT 0);
CREATE INDEX IF NOT EXISTS requests_by_time ON requests (asked_at);
"""
# Columns added after the first version; existing files get them on the next start.
ADDED_COLUMNS = {"chats": {"mode": "TEXT NOT NULL DEFAULT 'plan'"}, "requests": {"mode": "TEXT"}}
STATUSES = ("answered", "refused", "limit", "error")


def _connect() -> sqlite3.Connection:
    config.HISTORY_DB.parent.mkdir(parents=True, exist_ok=True)
    connection = sqlite3.connect(config.HISTORY_DB)
    connection.row_factory = sqlite3.Row
    connection.executescript(SCHEMA)
    for table, columns in ADDED_COLUMNS.items():
        present = {row["name"] for row in connection.execute(f"PRAGMA table_info({table})")}
        for name, definition in columns.items():
            if name not in present:
                connection.execute(f"ALTER TABLE {table} ADD COLUMN {name} {definition}")
    return connection


def title_for(question: str) -> str:
    text = " ".join(question.split())
    return text if len(text) <= TITLE_CHARS else text[:TITLE_CHARS - 1].rstrip() + "…"


# --- Chats --------------------------------------------------------------------

def create_chat(first_question: str, mode: str = "plan") -> str:
    chat_id, now = uuid.uuid4().hex[:12], time.time()
    with closing(_connect()) as db, db:
        db.execute("INSERT INTO chats (id, title, created_at, updated_at, mode) VALUES (?, ?, ?, ?, ?)",
                   (chat_id, title_for(first_question), now, now, mode))
    return chat_id


def set_chat_mode(chat_id: str, mode: str) -> None:
    with closing(_connect()) as db, db:
        db.execute("UPDATE chats SET mode = ? WHERE id = ?", (mode, chat_id))


def save_messages(chat_id: str, messages: list[dict]) -> None:
    with closing(_connect()) as db, db:
        db.execute("UPDATE chats SET messages = ?, updated_at = ? WHERE id = ?",
                   (json.dumps(messages, ensure_ascii=False), time.time(), chat_id))


def load_chat(chat_id: str) -> dict | None:
    with closing(_connect()) as db:
        row = db.execute("SELECT * FROM chats WHERE id = ?", (chat_id,)).fetchone()
    return None if row is None else {**dict(row), "messages": json.loads(row["messages"]),
                                     "bookmarked": bool(row["bookmarked"])}


def list_chats() -> list[dict]:
    """Every chat without its messages, most recently used first."""
    with closing(_connect()) as db:
        rows = db.execute("SELECT id, title, created_at, updated_at, bookmarked, mode FROM chats "
                          "ORDER BY updated_at DESC").fetchall()
    return [{**dict(row), "bookmarked": bool(row["bookmarked"])} for row in rows]


def rename_chat(chat_id: str, title: str) -> None:
    title = title_for(title) or "Untitled chat"
    with closing(_connect()) as db, db:
        db.execute("UPDATE chats SET title = ? WHERE id = ?", (title, chat_id))


def set_bookmark(chat_id: str, bookmarked: bool) -> None:
    with closing(_connect()) as db, db:
        db.execute("UPDATE chats SET bookmarked = ? WHERE id = ?", (int(bookmarked), chat_id))


def delete_chat(chat_id: str) -> None:
    """Deletes the chat; its request log rows stay (without the link) for the dashboard."""
    with closing(_connect()) as db, db:
        db.execute("DELETE FROM chats WHERE id = ?", (chat_id,))
        db.execute("UPDATE requests SET chat_id = NULL WHERE chat_id = ?", (chat_id,))


def delete_all() -> None:
    with closing(_connect_trips()) as db, db:
        db.execute("DELETE FROM chats")
        db.execute("DELETE FROM requests")
        db.execute("DELETE FROM trips")


def group_chats(chats: list[dict], today: date | None = None) -> dict[str, list[dict]]:
    """Bookmarked chats, then Today, Yesterday, Previous 7 days and Older (empty groups left out)."""
    today = today or date.today()
    groups: dict[str, list[dict]] = {"Bookmarked": [], "Today": [], "Yesterday": [], "Previous 7 days": [],
                                     "Older": []}
    for chat in chats:
        if chat["bookmarked"]:
            groups["Bookmarked"].append(chat)
            continue
        day = datetime.fromtimestamp(chat["updated_at"]).date()
        if day == today:
            groups["Today"].append(chat)
        elif day == today - timedelta(days=1):
            groups["Yesterday"].append(chat)
        elif day > today - timedelta(days=7):
            groups["Previous 7 days"].append(chat)
        else:
            groups["Older"].append(chat)
    return {name: items for name, items in groups.items() if items}


# --- Request log --------------------------------------------------------------

def log_request(chat_id: str | None, model: str, status: str, reason: str | None = None,
                seconds: float | None = None, usage: dict | None = None, tools: list[str] | None = None,
                searches: dict | None = None, mode: str | None = None) -> None:
    if status not in STATUSES:
        raise ValueError(f"Unknown request status: {status}")
    usage, searches = usage or {}, searches or {}
    with closing(_connect()) as db, db:
        db.execute(
            "INSERT INTO requests (chat_id, asked_at, model, status, reason, seconds, input_tokens, output_tokens, "
            "cost_usd, tools, serpapi, google, mode) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (chat_id, time.time(), model, status, reason, seconds, usage.get("input_tokens", 0),
             usage.get("output_tokens", 0), usage.get("cost_usd"), json.dumps(tools or []),
             searches.get("serpapi", 0), searches.get("google", 0), mode))


def requests_since(days: int) -> list[dict]:
    """Request log rows from the last `days` days, oldest first."""
    since = time.time() - days * 86400
    with closing(_connect()) as db:
        rows = db.execute("SELECT * FROM requests WHERE asked_at >= ? ORDER BY asked_at", (since,)).fetchall()
    return [{**dict(row), "tools": json.loads(row["tools"])} for row in rows]


# --- Saved trips ----------------------------------------------------------------

TRIPS_SCHEMA = """
CREATE TABLE IF NOT EXISTS trips (
    id TEXT PRIMARY KEY, chat_id TEXT, title TEXT NOT NULL, created_at REAL NOT NULL, trip TEXT NOT NULL);
"""


def _connect_trips() -> sqlite3.Connection:
    connection = _connect()
    connection.executescript(TRIPS_SCHEMA)
    return connection


def save_trip(trip: dict, chat_id: str | None = None) -> str:
    """Saves a trip built by trips.build_trip and returns its id."""
    trip_id = uuid.uuid4().hex[:12]
    with closing(_connect_trips()) as db, db:
        db.execute("INSERT INTO trips (id, chat_id, title, created_at, trip) VALUES (?, ?, ?, ?, ?)",
                   (trip_id, chat_id, trip["title"], time.time(), json.dumps(trip, ensure_ascii=False)))
    return trip_id


def load_trip(trip_id: str) -> dict | None:
    with closing(_connect_trips()) as db:
        row = db.execute("SELECT * FROM trips WHERE id = ?", (trip_id,)).fetchone()
    return None if row is None else {**json.loads(row["trip"]), "id": row["id"], "chat_id": row["chat_id"],
                                     "created_at": row["created_at"]}


def list_trips() -> list[dict]:
    """Every saved trip, newest first."""
    with closing(_connect_trips()) as db:
        rows = db.execute("SELECT * FROM trips ORDER BY created_at DESC").fetchall()
    return [{**json.loads(row["trip"]), "id": row["id"], "chat_id": row["chat_id"], "created_at": row["created_at"]}
            for row in rows]


def delete_trip(trip_id: str) -> None:
    with closing(_connect_trips()) as db, db:
        db.execute("DELETE FROM trips WHERE id = ?", (trip_id,))
