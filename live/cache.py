"""A small on-disk cache for live API answers, so repeated questions are free.

Answers are stored in SQLite (.cache/live.sqlite3) under a hash of the service,
URL and parameters. API keys are never part of the stored key or data. Each
entry expires after a time-to-live chosen by the caller (see
config.CACHE_TTL_SECONDS), so prices don't go stale.
"""

import hashlib
import json
import sqlite3
import time
from contextlib import closing
from dataclasses import dataclass
from pathlib import Path

import config


@dataclass(frozen=True)
class CachedAnswer:
    data: dict
    fetched_at: float  # Unix time when the live service answered


def cache_key(service: str, url: str, params: dict | None = None, body: dict | None = None) -> str:
    payload = json.dumps([service, url, params or {}, body or {}], sort_keys=True, default=str)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _connect(path: Path) -> sqlite3.Connection:
    path.parent.mkdir(parents=True, exist_ok=True)
    connection = sqlite3.connect(path, timeout=10)
    connection.execute("CREATE TABLE IF NOT EXISTS answers "
                       "(key TEXT PRIMARY KEY, data TEXT NOT NULL, fetched_at REAL NOT NULL, expires_at REAL NOT NULL)")
    return connection


def get(key: str, path: Path | None = None, now: float | None = None) -> CachedAnswer | None:
    now = time.time() if now is None else now
    with closing(_connect(path or config.CACHE_DB)) as connection:
        row = connection.execute("SELECT data, fetched_at FROM answers WHERE key = ? AND expires_at > ?",
                                 (key, now)).fetchone()
    return CachedAnswer(json.loads(row[0]), row[1]) if row else None


def put(key: str, data: dict, ttl_seconds: int, path: Path | None = None, now: float | None = None) -> CachedAnswer:
    now = time.time() if now is None else now
    with closing(_connect(path or config.CACHE_DB)) as connection, connection:
        connection.execute("INSERT OR REPLACE INTO answers VALUES (?, ?, ?, ?)",
                           (key, json.dumps(data), now, now + ttl_seconds))
        connection.execute("DELETE FROM answers WHERE expires_at <= ?", (now,))
    return CachedAnswer(data, now)
