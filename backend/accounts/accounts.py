"""Accounts with a username, an email and a password, in the same SQLite file as the chats.

- Sign-up checks the username, email and password; usernames and emails are unique (any letter case).
- A new account can sign in only after its email is confirmed: by an emailed link, or by the owner
  when emails aren't set up. Otherwise anyone could sign up with someone else's email and see that
  person's chats, because an account's owner id is the same hash of the email as with Google sign-in.
- Sign-in takes the username or the email. A wrong name and a wrong password give the same answer and
  take the same time. After MAX_TRIES wrong passwords within LOCK_SECONDS, the name waits.
- Remember-me cookies, confirm links and reset links are random tokens. Only their sha256 hash is
  stored, so a copy of the database can't be used to sign in. Each kind has its own lifetime, and
  confirm and reset links work once.
"""

import hashlib
import re
import secrets
import sqlite3
import time
from contextlib import closing

from backend import config
from backend.accounts import mail
from backend.accounts.passwords import DUMMY_HASH, MAX_LENGTH, MIN_LENGTH, check_password, hash_password
from backend.storage import history

SCHEMA = """
CREATE TABLE IF NOT EXISTS accounts (
    id INTEGER PRIMARY KEY AUTOINCREMENT, username TEXT NOT NULL UNIQUE COLLATE NOCASE,
    email TEXT NOT NULL UNIQUE COLLATE NOCASE, password_hash TEXT NOT NULL,
    confirmed INTEGER NOT NULL DEFAULT 0, created_at REAL NOT NULL);
CREATE TABLE IF NOT EXISTS failed_sign_ins (name TEXT NOT NULL, failed_at REAL NOT NULL);
CREATE TABLE IF NOT EXISTS account_tokens (
    token_hash TEXT PRIMARY KEY, account_id INTEGER NOT NULL, kind TEXT NOT NULL,
    created_at REAL NOT NULL, expires_at REAL NOT NULL, used INTEGER NOT NULL DEFAULT 0);
"""
MAX_TRIES, LOCK_SECONDS = 5, 15 * 60
LIFETIMES = {"remember": 30 * 86400, "confirm": 24 * 3600, "reset": 30 * 60}
RESET_EVERY_SECONDS = 120  # at most one reset email per account every two minutes
USERNAME = re.compile(r"[A-Za-z0-9_.\-]{3,30}")  # no "@", so a name is never mistaken for an email
EMAIL = re.compile(r"[A-Za-z0-9._%+\-]+@[A-Za-z0-9\-]+(\.[A-Za-z0-9\-]+)*\.[A-Za-z]{2,}")
WRONG = "wrong"  # the one error for a wrong name or a wrong password


def _connect() -> sqlite3.Connection:
    config.HISTORY_DB.parent.mkdir(parents=True, exist_ok=True)
    connection = sqlite3.connect(config.HISTORY_DB)
    connection.row_factory = sqlite3.Row
    connection.executescript(SCHEMA)
    return connection


def _hash(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


def _public(row: sqlite3.Row) -> dict:
    """What the app keeps about a signed-in account (never the password hash)."""
    return {"id": row["id"], "username": row["username"], "email": row["email"],
            "owner": history.owner_for(row["email"])}


def _find(name: str) -> sqlite3.Row | None:
    column = "email" if "@" in name else "username"
    with closing(_connect()) as db:
        return db.execute(f"SELECT * FROM accounts WHERE {column} = ?", (name.strip(),)).fetchone()


def find_account(name: str) -> dict | None:
    """The account with this username or email (any letter case), or None."""
    row = _find(name)
    return _public(row) if row else None


# --- sign-up and confirmation -----------------------------------------------------

def check_new_password(password: str, repeat: str) -> list[str]:
    errors = []
    if len(password) < MIN_LENGTH:
        errors.append("password_short")
    elif len(password) > MAX_LENGTH:
        errors.append("password_long")
    if password != repeat:
        errors.append("password_mismatch")
    return errors


def sign_up(username: str, email: str, password: str, repeat: str, link_base: str = "",
            language: str = "en") -> list[str]:
    """Creates an unconfirmed account and emails a confirm link when emails are set up.
    Returns error keys for the page (frontend/i18n.py: "account.error.<key>"), or [] when it worked."""
    username, email = username.strip(), email.strip().lower()
    errors = [] if USERNAME.fullmatch(username) else ["username_invalid"]
    if not EMAIL.fullmatch(email):
        errors.append("email_invalid")
    errors += check_new_password(password, repeat)
    if errors:
        return errors
    try:
        with closing(_connect()) as db, db:
            account_id = db.execute(
                "INSERT INTO accounts (username, email, password_hash, created_at) VALUES (?, ?, ?, ?)",
                (username, email, hash_password(password), time.time())).lastrowid
    except sqlite3.IntegrityError:  # the UNIQUE columns refuse a taken name or email
        return ["account_taken"]
    if mail.ready():
        link = f"{link_base}?confirm={new_token(account_id, 'confirm')}"
        mail.send("confirm", email, language, username=username, link=link)
    return []


def confirm_email(token: str) -> bool:
    """Confirms the account a confirm link belongs to. False if the link is unknown, used or expired."""
    account_id = use_token(token, "confirm")
    if account_id is None:
        return False
    with closing(_connect()) as db, db:
        db.execute("UPDATE accounts SET confirmed = 1 WHERE id = ?", (account_id,))
    return True


def waiting_accounts() -> list[dict]:
    """Accounts whose email isn't confirmed yet, newest first, for the owner to confirm."""
    with closing(_connect()) as db:
        rows = db.execute("SELECT * FROM accounts WHERE confirmed = 0 ORDER BY created_at DESC").fetchall()
    return [_public(row) | {"created_at": row["created_at"]} for row in rows]


def confirm_account(account_id: int) -> None:
    """The owner confirms an account by hand (when emails aren't set up)."""
    with closing(_connect()) as db, db:
        db.execute("UPDATE accounts SET confirmed = 1 WHERE id = ?", (account_id,))


def delete_account(account_id: int) -> None:
    """Removes an account and its tokens. Its chats and trips stay with the email's owner id."""
    with closing(_connect()) as db, db:
        db.execute("DELETE FROM account_tokens WHERE account_id = ?", (account_id,))
        db.execute("DELETE FROM accounts WHERE id = ?", (account_id,))


# --- sign-in and lockout -------------------------------------------------------------

def _recent_failures(db: sqlite3.Connection, key: str) -> list[float]:
    return [row[0] for row in db.execute(
        "SELECT failed_at FROM failed_sign_ins WHERE name = ? AND failed_at > ? ORDER BY failed_at DESC",
        (key, time.time() - LOCK_SECONDS))]


def locked_minutes(name: str) -> int:
    """How many minutes this name still has to wait (0 when it may try)."""
    account = _find(name)
    key = f"account:{account['id']}" if account else name.strip().lower()
    with closing(_connect()) as db:
        failures = _recent_failures(db, key)
    if len(failures) < MAX_TRIES:
        return 0
    return max(1, round((failures[MAX_TRIES - 1] + LOCK_SECONDS - time.time()) / 60))


def sign_in(name: str, password: str) -> dict | str:
    """Signs in by username or email. Returns the account, or an error key: "wrong", "locked"
    or "not_confirmed" (only said after the right password, so it doesn't reveal who has an account)."""
    account = _find(name)
    # Failures count per account, so typing the username and then the email doesn't give more tries.
    key = f"account:{account['id']}" if account else name.strip().lower()
    with closing(_connect()) as db, db:
        if len(_recent_failures(db, key)) >= MAX_TRIES:
            return "locked"
        # Always run the slow check, even for an unknown name, so both take the same time.
        right = check_password(password, account["password_hash"] if account else DUMMY_HASH)
        if not (account and right):
            db.execute("INSERT INTO failed_sign_ins VALUES (?, ?)", (key, time.time()))
            db.execute("DELETE FROM failed_sign_ins WHERE failed_at < ?", (time.time() - LOCK_SECONDS,))
            return WRONG
        db.execute("DELETE FROM failed_sign_ins WHERE name = ?", (key,))
    if not account["confirmed"]:
        return "not_confirmed"
    return _public(account)


# --- tokens: remember me, confirm and reset links ----------------------------------

def new_token(account_id: int, kind: str) -> str:
    """A random token for a cookie or an emailed link. Only its hash is stored."""
    token = secrets.token_urlsafe(32)
    now = time.time()
    with closing(_connect()) as db, db:
        db.execute("DELETE FROM account_tokens WHERE expires_at < ?", (now,))
        db.execute("INSERT INTO account_tokens VALUES (?, ?, ?, ?, ?, 0)",
                   (_hash(token), account_id, kind, now, now + LIFETIMES[kind]))
    return token


def _token_account(db: sqlite3.Connection, token: str, kind: str) -> int | None:
    row = db.execute("SELECT account_id, expires_at, used FROM account_tokens WHERE token_hash = ? AND kind = ?",
                     (_hash(token or ""), kind)).fetchone()
    if not row or row["used"] or row["expires_at"] < time.time():
        return None
    return row["account_id"]


def use_token(token: str, kind: str) -> int | None:
    """The account a one-time link belongs to, marking it used. None if unknown, used or expired."""
    with closing(_connect()) as db, db:
        account_id = _token_account(db, token, kind)
        if account_id is not None:
            db.execute("UPDATE account_tokens SET used = 1 WHERE token_hash = ?", (_hash(token),))
        return account_id


def token_valid(token: str, kind: str) -> bool:
    """True while a link still works, without using it (to show the page or "this link has expired")."""
    with closing(_connect()) as db:
        return _token_account(db, token, kind) is not None


def remember(account_id: int) -> str:
    """A remember-me token for the browser's cookie, valid for 30 days."""
    return new_token(account_id, "remember")


def remembered_account(token: str) -> dict | None:
    """The account a remember-me cookie belongs to, or None if it's unknown or expired."""
    with closing(_connect()) as db:
        account_id = _token_account(db, token, "remember")
        row = account_id and db.execute("SELECT * FROM accounts WHERE id = ? AND confirmed = 1",
                                        (account_id,)).fetchone()
    return _public(row) if row else None


def forget(token: str) -> None:
    """Deletes a remember-me token (on sign-out), so the cookie no longer signs anyone in."""
    with closing(_connect()) as db, db:
        db.execute("DELETE FROM account_tokens WHERE token_hash = ? AND kind = 'remember'", (_hash(token or ""),))


# --- forgotten passwords -----------------------------------------------------------

def request_reset(email: str, link_base: str = "", language: str = "en") -> None:
    """Emails a reset link if an account has this email. Returns nothing either way, so the page
    shows the same message whether or not the email has an account."""
    account = _find(email) if "@" in email else None
    if account is None or not mail.ready():
        return
    with closing(_connect()) as db:
        recent = db.execute("SELECT 1 FROM account_tokens WHERE account_id = ? AND kind = 'reset' AND created_at > ?",
                            (account["id"], time.time() - RESET_EVERY_SECONDS)).fetchone()
    if recent:  # someone pressing the button again and again doesn't flood the inbox
        return
    link = f"{link_base}?reset={new_token(account['id'], 'reset')}"
    mail.send("reset", account["email"], language, username=account["username"], link=link)


def reset_password(token: str, password: str, repeat: str) -> list[str]:
    """Sets a new password with a reset link. Returns error keys, or [] when it worked. Afterwards the
    link no longer works, and remember-me cookies on other browsers stop signing in."""
    errors = check_new_password(password, repeat)
    if errors:
        return errors
    account_id = use_token(token, "reset")
    if account_id is None:
        return ["link_expired"]
    with closing(_connect()) as db, db:
        # A reset link reached the inbox, which also proves the email is theirs.
        db.execute("UPDATE accounts SET password_hash = ?, confirmed = 1 WHERE id = ?",
                   (hash_password(password), account_id))
        db.execute("DELETE FROM account_tokens WHERE account_id = ? AND kind = 'remember'", (account_id,))
        db.execute("DELETE FROM failed_sign_ins WHERE name = ?", (f"account:{account_id}",))
    return []
