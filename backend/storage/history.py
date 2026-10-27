"""Saved chats, saved trips and the request log, in a SQLite file on this computer.

Chats keep every message with its tool results (so result cards can be drawn
again), the model and currency used, and a bookmark flag. Saved trips keep a
costed plan with its prices and places, for the trip page, and what the
traveller adds to a trip: expenses, a packing list, a journal and documents.
Uploaded documents are files next to the SQLite file (in documents/), not in
it, so saving a note never rewrites the files. The request log has
one row per question: when it was asked, how long the answer took, whether it
was answered, refused or failed (and why), tokens, cost, tool calls and live
searches. The dashboard is built from it.

Every chat, request and trip has an owner: the signed-in user (a hash of their
Google email, never the email itself), or "local" when sign-in isn't set up.
Reading and listing only ever return the owner's own rows, so a guessed chat or
trip id from someone else finds nothing. Expenses, packing lists, journals and
documents belong to a trip, so they're reached only through an owned trip.

The file (.history/chats.sqlite3) is git-ignored. No API keys are stored.
"""

import hashlib
import json
import re
import shutil
import sqlite3
import time
import uuid
from contextlib import closing
from datetime import date, datetime, timedelta
from pathlib import Path

from backend import config

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
LOCAL_OWNER = "local"  # the owner on a computer without sign-in, and of everything saved before it
# Columns added after the first version; existing files get them on the next start.
ADDED_COLUMNS = {"chats": {"mode": "TEXT NOT NULL DEFAULT 'plan'", "owner": f"TEXT NOT NULL DEFAULT '{LOCAL_OWNER}'"},
                 "requests": {"mode": "TEXT", "owner": f"TEXT NOT NULL DEFAULT '{LOCAL_OWNER}'"},
                 "trips": {"owner": f"TEXT NOT NULL DEFAULT '{LOCAL_OWNER}'"}}
STATUSES = ("answered", "refused", "limit", "error")


def _connect() -> sqlite3.Connection:
    config.HISTORY_DB.parent.mkdir(parents=True, exist_ok=True)
    connection = sqlite3.connect(config.HISTORY_DB)
    connection.row_factory = sqlite3.Row
    connection.executescript(SCHEMA + TRIPS_SCHEMA)
    for table, columns in ADDED_COLUMNS.items():
        present = {row["name"] for row in connection.execute(f"PRAGMA table_info({table})")}
        for name, definition in columns.items():
            if name not in present:
                connection.execute(f"ALTER TABLE {table} ADD COLUMN {name} {definition}")
    return connection


def owner_for(email: str) -> str:
    """The owner id for a signed-in user: a hash of their email, so the email itself isn't stored."""
    return "user-" + hashlib.sha256(email.strip().lower().encode()).hexdigest()[:20]


def title_for(question: str) -> str:
    text = " ".join(question.split())
    return text if len(text) <= TITLE_CHARS else text[:TITLE_CHARS - 1].rstrip() + "…"


# --- Chats --------------------------------------------------------------------

def create_chat(first_question: str, mode: str = "plan", owner: str = LOCAL_OWNER) -> str:
    chat_id, now = uuid.uuid4().hex[:12], time.time()
    with closing(_connect()) as db, db:
        db.execute("INSERT INTO chats (id, title, created_at, updated_at, mode, owner) VALUES (?, ?, ?, ?, ?, ?)",
                   (chat_id, title_for(first_question), now, now, mode, owner))
    return chat_id


def set_chat_mode(chat_id: str, mode: str) -> None:
    with closing(_connect()) as db, db:
        db.execute("UPDATE chats SET mode = ? WHERE id = ?", (mode, chat_id))


def save_messages(chat_id: str, messages: list[dict]) -> None:
    with closing(_connect()) as db, db:
        db.execute("UPDATE chats SET messages = ?, updated_at = ? WHERE id = ?",
                   (json.dumps(messages, ensure_ascii=False), time.time(), chat_id))


def load_chat(chat_id: str, owner: str = LOCAL_OWNER) -> dict | None:
    """The owner's chat, or None (also for someone else's chat)."""
    with closing(_connect()) as db:
        row = db.execute("SELECT * FROM chats WHERE id = ? AND owner = ?", (chat_id, owner)).fetchone()
    return None if row is None else {**dict(row), "messages": json.loads(row["messages"]),
                                     "bookmarked": bool(row["bookmarked"])}


def list_chats(owner: str = LOCAL_OWNER) -> list[dict]:
    """The owner's chats without their messages, most recently used first."""
    with closing(_connect()) as db:
        rows = db.execute("SELECT id, title, created_at, updated_at, bookmarked, mode FROM chats WHERE owner = ? "
                          "ORDER BY updated_at DESC", (owner,)).fetchall()
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


def delete_all(owner: str = LOCAL_OWNER) -> None:
    """Deletes everything the owner saved: chats, request log, trips and what was added to them."""
    trip_ids = [trip["id"] for trip in list_trips(owner)]
    with closing(_connect_trips()) as db, db:
        db.execute("DELETE FROM chats WHERE owner = ?", (owner,))
        db.execute("DELETE FROM requests WHERE owner = ?", (owner,))
        db.execute("DELETE FROM trips WHERE owner = ?", (owner,))
        for table in TRIP_EXTRA_TABLES:
            db.executemany(f"DELETE FROM {table} WHERE trip_id = ?", [(trip_id,) for trip_id in trip_ids])
    for trip_id in trip_ids:
        shutil.rmtree(documents_dir() / trip_id, ignore_errors=True)


def claim_local_data(owner: str) -> int:
    """Gives everything saved without sign-in (owner "local") to this owner, for example the app's
    author when sign-in is first turned on. Returns how many chats and trips moved."""
    with closing(_connect_trips()) as db, db:
        moved = sum(db.execute(f"UPDATE {table} SET owner = ? WHERE owner = ?", (owner, LOCAL_OWNER)).rowcount
                    for table in ("chats", "trips"))
        db.execute("UPDATE requests SET owner = ? WHERE owner = ?", (owner, LOCAL_OWNER))
    return moved


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
                searches: dict | None = None, mode: str | None = None, owner: str = LOCAL_OWNER) -> None:
    if status not in STATUSES:
        raise ValueError(f"Unknown request status: {status}")
    usage, searches = usage or {}, searches or {}
    with closing(_connect()) as db, db:
        db.execute(
            "INSERT INTO requests (chat_id, asked_at, model, status, reason, seconds, input_tokens, output_tokens, "
            "cost_usd, tools, serpapi, google, mode, owner) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (chat_id, time.time(), model, status, reason, seconds, usage.get("input_tokens", 0),
             usage.get("output_tokens", 0), usage.get("cost_usd"), json.dumps(tools or []),
             searches.get("serpapi", 0), searches.get("google", 0), mode, owner))


def requests_since(days: int, owner: str = LOCAL_OWNER) -> list[dict]:
    """The owner's request log rows from the last `days` days, oldest first."""
    since = time.time() - days * 86400
    with closing(_connect()) as db:
        rows = db.execute("SELECT * FROM requests WHERE asked_at >= ? AND owner = ? ORDER BY asked_at",
                          (since, owner)).fetchall()
    return [{**dict(row), "tools": json.loads(row["tools"])} for row in rows]


# --- Saved trips ----------------------------------------------------------------

TRIPS_SCHEMA = """
CREATE TABLE IF NOT EXISTS trips (
    id TEXT PRIMARY KEY, chat_id TEXT, title TEXT NOT NULL, created_at REAL NOT NULL, trip TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS expenses (
    id INTEGER PRIMARY KEY AUTOINCREMENT, trip_id TEXT NOT NULL, day INTEGER, category TEXT NOT NULL,
    amount REAL NOT NULL, note TEXT NOT NULL DEFAULT '', created_at REAL NOT NULL);
CREATE TABLE IF NOT EXISTS packing_items (
    id INTEGER PRIMARY KEY AUTOINCREMENT, trip_id TEXT NOT NULL, name TEXT NOT NULL, section TEXT NOT NULL,
    packed INTEGER NOT NULL DEFAULT 0, created_at REAL NOT NULL);
CREATE TABLE IF NOT EXISTS journal_entries (
    trip_id TEXT NOT NULL, day INTEGER NOT NULL, text TEXT NOT NULL DEFAULT '', rating INTEGER,
    updated_at REAL NOT NULL, PRIMARY KEY (trip_id, day));
CREATE TABLE IF NOT EXISTS documents (
    id TEXT PRIMARY KEY, trip_id TEXT NOT NULL, name TEXT NOT NULL, tag TEXT NOT NULL, day INTEGER,
    mime TEXT NOT NULL, size INTEGER NOT NULL, created_at REAL NOT NULL);
"""
TRIP_EXTRA_TABLES = ("expenses", "packing_items", "journal_entries", "documents")


def _connect_trips() -> sqlite3.Connection:
    return _connect()


def save_trip(trip: dict, chat_id: str | None = None, owner: str = LOCAL_OWNER) -> str:
    """Saves a trip built by trips.build_trip and returns its id."""
    trip_id = uuid.uuid4().hex[:12]
    with closing(_connect_trips()) as db, db:
        db.execute("INSERT INTO trips (id, chat_id, title, created_at, trip, owner) VALUES (?, ?, ?, ?, ?, ?)",
                   (trip_id, chat_id, trip["title"], time.time(), json.dumps(trip, ensure_ascii=False), owner))
    return trip_id


def load_trip(trip_id: str, owner: str = LOCAL_OWNER) -> dict | None:
    """The owner's trip, or None (also for someone else's trip)."""
    with closing(_connect_trips()) as db:
        row = db.execute("SELECT * FROM trips WHERE id = ? AND owner = ?", (trip_id, owner)).fetchone()
    return None if row is None else {**json.loads(row["trip"]), "id": row["id"], "chat_id": row["chat_id"],
                                     "created_at": row["created_at"]}


def list_trips(owner: str = LOCAL_OWNER) -> list[dict]:
    """The owner's saved trips, newest first."""
    with closing(_connect_trips()) as db:
        rows = db.execute("SELECT * FROM trips WHERE owner = ? ORDER BY created_at DESC", (owner,)).fetchall()
    return [{**json.loads(row["trip"]), "id": row["id"], "chat_id": row["chat_id"], "created_at": row["created_at"]}
            for row in rows]


def delete_trip(trip_id: str) -> None:
    """Deletes the trip with everything added to it: expenses, packing list, journal and documents."""
    with closing(_connect_trips()) as db, db:
        db.execute("DELETE FROM trips WHERE id = ?", (trip_id,))
        for table in TRIP_EXTRA_TABLES:
            db.execute(f"DELETE FROM {table} WHERE trip_id = ?", (trip_id,))
    shutil.rmtree(documents_dir() / trip_id, ignore_errors=True)


# --- What the traveller adds to a trip -------------------------------------------

def add_expense(trip_id: str, category: str, amount: float, day: int | None = None, note: str = "") -> None:
    if amount <= 0:
        raise ValueError("An expense must be more than 0.")
    with closing(_connect_trips()) as db, db:
        db.execute("INSERT INTO expenses (trip_id, day, category, amount, note, created_at) VALUES (?, ?, ?, ?, ?, ?)",
                   (trip_id, day, category, round(amount, 2), note.strip()[:200], time.time()))


def list_expenses(trip_id: str) -> list[dict]:
    """A trip's expenses by day (expenses without a day last), in the order they were added."""
    with closing(_connect_trips()) as db:
        rows = db.execute("SELECT * FROM expenses WHERE trip_id = ? ORDER BY day IS NULL, day, id",
                          (trip_id,)).fetchall()
    return [dict(row) for row in rows]


def delete_expense(expense_id: int) -> None:
    with closing(_connect_trips()) as db, db:
        db.execute("DELETE FROM expenses WHERE id = ?", (expense_id,))


def add_packing_items(trip_id: str, items: list[tuple[str, str]]) -> int:
    """Adds (name, section) items, skipping names the list already has (ignoring case).
    Returns how many were added."""
    added = 0
    with closing(_connect_trips()) as db, db:
        have = {row["name"].lower() for row in db.execute("SELECT name FROM packing_items WHERE trip_id = ?",
                                                          (trip_id,))}
        for name, section in items:
            name = " ".join(name.split())[:80]
            if name and name.lower() not in have:
                have.add(name.lower())
                added += 1
                db.execute("INSERT INTO packing_items (trip_id, name, section, created_at) VALUES (?, ?, ?, ?)",
                           (trip_id, name, section, time.time()))
    return added


def list_packing_items(trip_id: str) -> list[dict]:
    with closing(_connect_trips()) as db:
        rows = db.execute("SELECT * FROM packing_items WHERE trip_id = ? ORDER BY id", (trip_id,)).fetchall()
    return [{**dict(row), "packed": bool(row["packed"])} for row in rows]


def set_packed(item_id: int, packed: bool) -> None:
    with closing(_connect_trips()) as db, db:
        db.execute("UPDATE packing_items SET packed = ? WHERE id = ?", (int(packed), item_id))


def delete_packing_item(item_id: int) -> None:
    with closing(_connect_trips()) as db, db:
        db.execute("DELETE FROM packing_items WHERE id = ?", (item_id,))


def save_journal(trip_id: str, day: int, text: str | None = None, rating: int | None = None) -> None:
    """Saves a day's note and/or rating (0-5 stars); a value left as None keeps what was saved."""
    entry = load_journal(trip_id).get(day, {"text": "", "rating": None})
    text = entry["text"] if text is None else text.strip()[:5000]
    rating = entry["rating"] if rating is None else max(0, min(5, rating))
    with closing(_connect_trips()) as db, db:
        db.execute("INSERT OR REPLACE INTO journal_entries (trip_id, day, text, rating, updated_at) "
                   "VALUES (?, ?, ?, ?, ?)", (trip_id, day, text, rating, time.time()))


def load_journal(trip_id: str) -> dict[int, dict]:
    """The trip's journal: day number -> {text, rating, updated_at}."""
    with closing(_connect_trips()) as db:
        rows = db.execute("SELECT * FROM journal_entries WHERE trip_id = ?", (trip_id,)).fetchall()
    return {row["day"]: {"text": row["text"], "rating": row["rating"], "updated_at": row["updated_at"]}
            for row in rows}


# The types documents may have, with their file ending and the bytes such a file starts with.
DOCUMENT_TYPES = {"application/pdf": (".pdf", b"%PDF"), "image/png": (".png", b"\x89PNG"),
                  "image/jpeg": (".jpg", b"\xff\xd8\xff"), "image/webp": (".webp", b"RIFF")}
MAX_DOCUMENT_BYTES = 5 * 1024 * 1024


def documents_dir() -> Path:
    return config.HISTORY_DB.parent / "documents"


def _safe_name(name: str) -> str:
    return (re.sub(r"[^\w .()-]", "_", Path(name).name).strip(" .") or "file")[:100]


def save_document(trip_id: str, name: str, data: bytes, tag: str, day: int | None = None) -> str:
    """Stores an uploaded PDF or image for the trip and returns its id. The type is read from the
    file's first bytes, not its name, and only PDFs, PNGs, JPEGs and WebPs up to 5 MB are kept."""
    if len(data) > MAX_DOCUMENT_BYTES:
        raise ValueError("The file is larger than 5 MB.")
    mime = next((m for m, (_, magic) in DOCUMENT_TYPES.items() if data.startswith(magic)), None)
    if mime is None or (mime == "image/webp" and data[8:12] != b"WEBP"):
        raise ValueError("Only PDF, PNG, JPEG and WebP files can be uploaded.")
    document_id = uuid.uuid4().hex[:12]
    folder = documents_dir() / trip_id
    folder.mkdir(parents=True, exist_ok=True)
    (folder / f"{document_id}{DOCUMENT_TYPES[mime][0]}").write_bytes(data)
    with closing(_connect_trips()) as db, db:
        db.execute("INSERT INTO documents (id, trip_id, name, tag, day, mime, size, created_at) "
                   "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                   (document_id, trip_id, _safe_name(name), tag, day, mime, len(data), time.time()))
    return document_id


def list_documents(trip_id: str, day: int | None = None) -> list[dict]:
    """A trip's documents, newest first; with `day`, only that day's."""
    query, args = "SELECT * FROM documents WHERE trip_id = ?", [trip_id]
    if day is not None:
        query, args = query + " AND day = ?", [*args, day]
    with closing(_connect_trips()) as db:
        rows = db.execute(query + " ORDER BY created_at DESC", args).fetchall()
    return [dict(row) for row in rows]


def _document_path(document: dict) -> Path:
    return documents_dir() / document["trip_id"] / f"{document['id']}{DOCUMENT_TYPES[document['mime']][0]}"


def read_document(document: dict) -> bytes:
    return _document_path(document).read_bytes()


def delete_document(document_id: str) -> None:
    with closing(_connect_trips()) as db, db:
        row = db.execute("SELECT * FROM documents WHERE id = ?", (document_id,)).fetchone()
        db.execute("DELETE FROM documents WHERE id = ?", (document_id,))
    if row is not None:
        _document_path(dict(row)).unlink(missing_ok=True)
