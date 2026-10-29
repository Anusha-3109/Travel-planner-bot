"""Password accounts (backend/accounts/): hashing, sign-up checks, sign-in by name or email, the lockout,
remember-me tokens and one-time links, in a temporary database. Emails are caught, never sent."""

import re
import string

import pytest

from backend import config
from backend.accounts import accounts, mail, passwords
from backend.storage import history

PASSWORD = "test-password-123"  # a test value, only ever in this temporary database


class Clock:
    """Stands in for the time module, so tests can jump past lockouts and link lifetimes."""
    def __init__(self):
        self.now = 1_800_000_000.0

    def time(self):
        return self.now


@pytest.fixture
def clock(monkeypatch):
    fake = Clock()
    monkeypatch.setattr(accounts, "time", fake)
    return fake


@pytest.fixture
def outbox(monkeypatch):
    """Emails set up, with requests.post replaced: every email lands in this list."""
    sent = []

    class Response:
        def raise_for_status(self):
            pass

    def post(url, json, headers, timeout):
        sent.append(json)
        return Response()

    monkeypatch.setattr(config, "BREVO_API_KEY", "test-brevo-key")
    monkeypatch.setattr(config, "MAIL_FROM", "tripmate@example.com")
    monkeypatch.setattr(mail.requests, "post", post)
    return sent


def _link_token(email: dict, kind: str) -> str:
    return re.search(rf"\?{kind}=([\w\-]+)", email["textContent"]).group(1)


def _account(username="anna", email="anna@example.com", confirmed=True) -> dict:
    assert accounts.sign_up(username, email, PASSWORD, PASSWORD) == []
    row = next(a for a in accounts.waiting_accounts() if a["username"] == username)
    if confirmed:
        accounts.confirm_account(row["id"])
    return row


# --- hashing -------------------------------------------------------------------

def test_passwords_are_hashed_with_a_random_salt_and_checked():
    first, second = passwords.hash_password(PASSWORD), passwords.hash_password(PASSWORD)
    assert first != second and PASSWORD not in first and first.startswith("scrypt$16384$8$1$")
    assert passwords.check_password(PASSWORD, first) and passwords.check_password(PASSWORD, second)
    assert not passwords.check_password(PASSWORD + "x", first)
    assert not passwords.check_password(PASSWORD, "not a hash") and not passwords.check_password(PASSWORD, "")


def test_the_same_password_typed_two_ways_matches():
    composed, decomposed = "Grüße-aus-Köln", "Grüße-aus-Köln"
    assert passwords.check_password(decomposed, passwords.hash_password(composed))


def test_the_database_never_holds_the_password_or_a_token(outbox):
    accounts.sign_up("anna", "anna@example.com", PASSWORD, PASSWORD, "https://app")
    token = _link_token(outbox[0], "confirm")
    data = config.HISTORY_DB.read_bytes()
    assert PASSWORD.encode() not in data and token.encode() not in data


# --- sign-up --------------------------------------------------------------------

@pytest.mark.parametrize("username, email, password, repeat, errors", [
    ("an", "anna@example.com", PASSWORD, PASSWORD, ["username_invalid"]),
    ("anna@home", "anna@example.com", PASSWORD, PASSWORD, ["username_invalid"]),
    ("anna", "not-an-email", PASSWORD, PASSWORD, ["email_invalid"]),
    ("anna", "anna@example.com", "short-pw", "short-pw", ["password_short"]),
    ("anna", "anna@example.com", "x" * 201, "x" * 201, ["password_long"]),
    ("anna", "anna@example.com", PASSWORD, PASSWORD + "!", ["password_mismatch"]),
])
def test_sign_up_checks_every_field(username, email, password, repeat, errors):
    assert accounts.sign_up(username, email, password, repeat) == errors
    assert accounts.waiting_accounts() == []


def test_usernames_and_emails_are_unique_in_any_letter_case():
    _account()
    assert accounts.sign_up("ANNA", "other@example.com", PASSWORD, PASSWORD) == ["account_taken"]
    assert accounts.sign_up("bob", " Anna@Example.COM ", PASSWORD, PASSWORD) == ["account_taken"]
    assert accounts.sign_up("bob", "bob@example.com", PASSWORD, PASSWORD) == []


def test_a_new_account_waits_until_its_email_is_confirmed():
    row = _account(confirmed=False)
    assert accounts.sign_in("anna", PASSWORD) == "not_confirmed"
    accounts.confirm_account(row["id"])
    assert accounts.sign_in("anna", PASSWORD)["username"] == "anna"
    assert accounts.waiting_accounts() == []


def test_the_emailed_confirm_link_confirms_once(outbox):
    assert accounts.sign_up("anna", "anna@example.com", PASSWORD, PASSWORD, "https://app", "en") == []
    assert outbox[0]["to"] == [{"email": "anna@example.com"}] and "https://app?confirm=" in outbox[0]["textContent"]
    token = _link_token(outbox[0], "confirm")
    assert accounts.confirm_email(token) and not accounts.confirm_email(token)
    assert accounts.sign_in("anna@example.com", PASSWORD)["username"] == "anna"


def test_without_emails_set_up_nothing_is_sent(monkeypatch):
    def post(*args, **kwargs):
        raise AssertionError("no email should be sent")
    monkeypatch.setattr(mail.requests, "post", post)
    assert not mail.ready()
    assert accounts.sign_up("anna", "anna@example.com", PASSWORD, PASSWORD, "https://app") == []
    accounts.request_reset("anna@example.com", "https://app")


# --- sign-in ----------------------------------------------------------------------

def test_sign_in_by_username_or_email_in_any_letter_case():
    _account()
    by_name, by_email = accounts.sign_in("Anna", PASSWORD), accounts.sign_in(" ANNA@example.com ", PASSWORD)
    assert by_name == by_email
    assert by_name == {"id": by_name["id"], "username": "anna", "email": "anna@example.com",
                       "owner": history.owner_for("anna@example.com")}


def test_a_password_account_has_the_same_owner_as_google_with_that_email():
    _account(email="Anna@Example.com")
    assert accounts.sign_in("anna", PASSWORD)["owner"] == history.owner_for("anna@example.com")


def test_a_wrong_name_and_a_wrong_password_get_the_same_answer():
    _account()
    assert accounts.sign_in("anna", "wrong-password-1") == accounts.sign_in("nobody", PASSWORD) == accounts.WRONG
    assert accounts.sign_in("nobody@example.com", PASSWORD) == accounts.WRONG


def test_an_unknown_name_still_runs_the_slow_password_check(monkeypatch):
    checked = []
    monkeypatch.setattr(accounts, "check_password", lambda password, stored: checked.append(stored) or False)
    assert accounts.sign_in("nobody", PASSWORD) == accounts.WRONG
    assert checked == [passwords.DUMMY_HASH]


def test_five_wrong_passwords_lock_the_account_for_fifteen_minutes(clock):
    _account()
    for _ in range(accounts.MAX_TRIES):
        assert accounts.sign_in("anna", "wrong-password-1") == accounts.WRONG
    assert accounts.sign_in("anna", PASSWORD) == "locked"
    assert accounts.sign_in("anna@example.com", PASSWORD) == "locked"  # the email doesn't give more tries
    assert accounts.locked_minutes("anna") == 15
    clock.now += 14 * 60
    assert accounts.sign_in("anna", PASSWORD) == "locked" and accounts.locked_minutes("anna") == 1
    clock.now += 61
    assert accounts.locked_minutes("anna") == 0
    assert accounts.sign_in("anna", PASSWORD)["username"] == "anna"


def test_a_right_password_clears_the_wrong_tries(clock):
    _account()
    for _ in range(accounts.MAX_TRIES - 1):
        accounts.sign_in("anna", "wrong-password-1")
    assert accounts.sign_in("anna", PASSWORD)["username"] == "anna"
    accounts.sign_in("anna", "wrong-password-1")
    assert accounts.sign_in("anna", PASSWORD)["username"] == "anna"


def test_unknown_names_are_locked_too(clock):
    for _ in range(accounts.MAX_TRIES):
        accounts.sign_in("nobody", PASSWORD)
    assert accounts.sign_in("nobody", PASSWORD) == "locked"


# --- remember me ------------------------------------------------------------------

def test_a_remember_me_token_signs_in_for_thirty_days_until_signed_out(clock):
    account = _account()
    token = accounts.remember(account["id"])
    assert accounts.remembered_account(token)["username"] == "anna"
    clock.now += 29 * 86400
    assert accounts.remembered_account(token)["username"] == "anna"
    clock.now += 2 * 86400
    assert accounts.remembered_account(token) is None
    fresh = accounts.remember(account["id"])
    accounts.forget(fresh)
    assert accounts.remembered_account(fresh) is None
    assert accounts.remembered_account("made-up") is None and accounts.remembered_account("") is None


def test_a_remember_me_token_is_not_a_reset_link():
    token = accounts.remember(_account()["id"])
    assert accounts.reset_password(token, "new-password-456", "new-password-456") == ["link_expired"]


# --- forgotten passwords ------------------------------------------------------------

def test_a_reset_link_sets_a_new_password_once(outbox, clock):
    account = _account()
    remembered = accounts.remember(account["id"])
    accounts.request_reset("Anna@example.com", "https://app", "en")
    token = _link_token(outbox[-1], "reset")
    assert accounts.token_valid(token, "reset")
    assert accounts.reset_password(token, "short", "short") == ["password_short"]
    assert accounts.token_valid(token, "reset")  # a typo doesn't use up the link
    assert accounts.reset_password(token, "new-password-456", "new-password-456") == []
    assert accounts.sign_in("anna", "new-password-456")["username"] == "anna"
    assert accounts.sign_in("anna", PASSWORD) == accounts.WRONG
    assert accounts.reset_password(token, "other-password-7", "other-password-7") == ["link_expired"]
    assert not accounts.token_valid(token, "reset")
    assert accounts.remembered_account(remembered) is None  # other browsers are signed out


def test_a_reset_link_expires_after_thirty_minutes(outbox, clock):
    _account()
    accounts.request_reset("anna@example.com", "https://app")
    token = _link_token(outbox[-1], "reset")
    clock.now += 31 * 60
    assert not accounts.token_valid(token, "reset")
    assert accounts.reset_password(token, "new-password-456", "new-password-456") == ["link_expired"]


def test_a_reset_for_an_unknown_email_sends_nothing_and_says_nothing(outbox):
    assert accounts.request_reset("nobody@example.com", "https://app") is None
    assert accounts.request_reset("anna", "https://app") is None  # only emails, not usernames
    assert outbox == []


def test_reset_emails_are_limited_to_one_every_two_minutes(outbox, clock):
    _account()
    resets = lambda: [email for email in outbox if "?reset=" in email["textContent"]]
    accounts.request_reset("anna@example.com", "https://app")
    accounts.request_reset("anna@example.com", "https://app")
    assert len(resets()) == 1
    clock.now += accounts.RESET_EVERY_SECONDS + 1
    accounts.request_reset("anna@example.com", "https://app")
    assert len(resets()) == 2


def test_a_reset_also_confirms_the_email_and_ends_a_lockout(outbox, clock):
    _account(confirmed=False)
    for _ in range(accounts.MAX_TRIES):
        accounts.sign_in("anna", "wrong-password-1")
    accounts.request_reset("anna@example.com", "https://app")
    assert accounts.reset_password(_link_token(outbox[-1], "reset"), "new-password-456", "new-password-456") == []
    assert accounts.sign_in("anna", "new-password-456")["username"] == "anna"


def test_deleting_an_account_ends_its_sign_in():
    account = _account()
    token = accounts.remember(account["id"])
    accounts.delete_account(account["id"])
    assert accounts.sign_in("anna", PASSWORD) == accounts.WRONG and accounts.remembered_account(token) is None


# --- emails ----------------------------------------------------------------------

def test_emails_come_in_english_and_german(outbox):
    for kind, texts in mail.TEXTS.items():
        assert set(texts) == {"en", "de"}
        fields = [{name for _, name, _, _ in string.Formatter().parse(body) if name} for _, body in texts.values()]
        assert fields[0] == fields[1] == {"username", "link"}, kind
    accounts.sign_up("anna", "anna@example.com", PASSWORD, PASSWORD, "https://app", "de")
    assert outbox[0]["subject"] == "Bestätige dein TripMate-Konto" and "Hallo anna" in outbox[0]["textContent"]


def test_a_failed_email_is_logged_without_the_key(monkeypatch, caplog):
    from backend.security.redaction import protect_logs
    protect_logs()
    monkeypatch.setattr(config, "BREVO_API_KEY", "test-brevo-key-0123456789")
    monkeypatch.setattr(config, "MAIL_FROM", "tripmate@example.com")

    def post(*args, **kwargs):
        raise mail.requests.ConnectionError("refused for test-brevo-key-0123456789")
    monkeypatch.setattr(mail.requests, "post", post)
    assert not mail.send("reset", "anna@example.com", "en", username="anna", link="https://app")
    assert "test-brevo-key" not in caplog.text and "Couldn't send the reset email" in caplog.text


def test_the_owner_can_confirm_accounts_from_the_terminal(capsys):
    from backend.accounts.__main__ import main
    _account("anna", "Anna@example.com", confirmed=False)
    assert main(["waiting"]) == 0 and "anna  anna@example.com" in capsys.readouterr().out
    assert main(["confirm", "nobody"]) == 1
    assert main(["confirm", "ANNA@example.com"]) == 0
    assert accounts.sign_in("anna", PASSWORD)["username"] == "anna"
    assert main([]) == 2


def test_the_owner_can_make_a_reset_link_from_the_terminal(capsys, monkeypatch):
    from backend.accounts.__main__ import main
    monkeypatch.setattr(config, "APP_URL", "https://tripmate.example/")
    _account()
    assert main(["reset-link", "nobody"]) == 1
    assert main(["reset-link", "Anna@example.com"]) == 0
    link = capsys.readouterr().out.strip().splitlines()[-1]
    assert link.startswith("https://tripmate.example/?reset=")
    token = link.split("reset=")[1]
    assert accounts.reset_password(token, "new-password-456", "new-password-456") == []
    assert accounts.sign_in("anna", "new-password-456")["username"] == "anna"
