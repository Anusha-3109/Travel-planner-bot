"""The sign-in screens (frontend/pages/sign_in.py) with password accounts turned on, in English and German.
Accounts are test accounts in a temporary database; emails are caught, never sent."""

import re

import pytest
from streamlit.testing.v1 import AppTest

from backend import config
from backend.accounts import accounts, mail
from tests.test_accounts import PASSWORD, _account

NEW_PASSWORD = "new-test-password-9"


@pytest.fixture
def accounts_on(monkeypatch):
    monkeypatch.setattr(config, "OPENROUTER_API_KEY", "test-key")
    monkeypatch.setattr(config, "APP_PASSWORD", "")
    monkeypatch.setattr(config, "PASSWORD_ACCOUNTS", True)
    monkeypatch.setattr("frontend.components.common.google_enabled", lambda: False)
    monkeypatch.setattr("frontend.pages.sign_in.google_enabled", lambda: False)
    monkeypatch.setattr("frontend.components.common.ensure_index", lambda on_progress=None: 0)


@pytest.fixture
def outbox(monkeypatch):
    sent = []
    monkeypatch.setattr(config, "BREVO_API_KEY", "test-brevo-key")
    monkeypatch.setattr(config, "MAIL_FROM", "tripmate@example.com")
    monkeypatch.setattr(mail, "send", lambda kind, to, language, **values: sent.append((kind, to, values)) or True)
    return sent


def _app() -> AppTest:
    at = AppTest.from_file("../app.py", default_timeout=30)
    at.run()
    assert not at.exception
    return at


def _button(at: AppTest, label: str):
    return next(b for b in at.button if b.label == label)


def _sign_in(at: AppTest, name: str, password: str, remember=False, label="Sign in") -> AppTest:
    at.text_input[0].input(name)
    at.text_input[1].input(password)
    if remember:
        at.checkbox[0].check()
    return _button(at, label).click().run()


def test_the_sign_in_form_without_google(accounts_on):
    at = _app()
    assert [i.label for i in at.text_input] == ["Username or email address", "Password"]
    assert [c.label for c in at.checkbox] == ["Remember me"]
    assert [b.label for b in at.button] == ["Sign in", "Forgot your password?", "Sign up"]  # no Google button
    assert not at.chat_input


def test_sign_up_waits_for_the_owner_then_signs_in_by_name_or_email(accounts_on):
    at = _app()
    _button(at, "Sign up").click().run()
    assert [i.label for i in at.text_input] == ["Username", "Email address", "Password", "Repeat password"]
    for field, value in zip(at.text_input, ["anna", "anna@example.com", PASSWORD, PASSWORD]):
        field.input(value)
    _button(at, "Create account").click().run()
    assert not at.exception and "owner confirms new accounts" in at.success[0].value
    _sign_in(at, "anna", PASSWORD)
    assert "waiting for the TripMate owner" in at.error[0].value and not at.chat_input
    accounts.confirm_account(accounts.waiting_accounts()[0]["id"])
    _sign_in(at, "anna@example.com", PASSWORD)
    assert not at.exception and at.chat_input
    assert "Signed in as anna" in [c.value for c in at.sidebar.caption]


def test_sign_up_shows_every_problem(accounts_on):
    at = _app()
    _button(at, "Sign up").click().run()
    for field, value in zip(at.text_input, ["a", "not-an-email", "short", "other"]):
        field.input(value)
    _button(at, "Create account").click().run()
    assert [e.value for e in at.error] == [
        "Usernames have 3 to 30 letters, digits, dots, dashes or underscores.", "Please enter a valid email address.",
        "The password needs at least 10 characters.", "The two passwords don't match."]


def test_with_emails_set_up_sign_up_sends_a_confirm_link(accounts_on, outbox):
    at = _app()
    _button(at, "Sign up").click().run()
    for field, value in zip(at.text_input, ["anna", "anna@example.com", PASSWORD, PASSWORD]):
        field.input(value)
    _button(at, "Create account").click().run()
    assert "sent a link to anna@example.com" in at.success[0].value
    [(kind, to, values)] = outbox
    assert (kind, to, values["username"]) == ("confirm", "anna@example.com", "anna")
    assert "?confirm=" in values["link"]


def test_a_wrong_password_and_the_lockout_in_german(accounts_on):
    _account()
    at = _app()
    at.session_state.language = "de"
    at.run()
    assert [i.label for i in at.text_input] == ["Benutzername oder E-Mail-Adresse", "Passwort"]
    for _ in range(accounts.MAX_TRIES):
        _sign_in(at, "anna", "wrong-password-1", label="Anmelden")
    assert at.error[0].value == "Falscher Benutzername, falsche E-Mail oder falsches Passwort."
    at.text_input[1].input(PASSWORD)
    _button(at, "Anmelden").click().run()
    assert at.error[0].value.startswith("Zu viele falsche Versuche. Bitte warte 15 Minuten")
    assert not at.chat_input


def test_remember_me_keeps_a_token_for_the_cookie_and_sign_out_ends_it(accounts_on, monkeypatch):
    _account()
    at = _sign_in(_app(), "anna", PASSWORD, remember=True)
    token = at.session_state.cookie
    assert at.chat_input and accounts.remembered_account(token)["username"] == "anna"

    # A new visit with the cookie in the browser is signed in straight away.
    monkeypatch.setattr("frontend.components.cookie.remembered_token", lambda: token)
    at = _app()
    assert at.chat_input and "Signed in as anna" in [c.value for c in at.sidebar.caption]
    next(b for b in at.sidebar.button if b.label == "Sign out").click().run()
    assert not at.chat_input and at.session_state.cookie == "" and accounts.remembered_account(token) is None


def test_without_remember_me_no_cookie_is_set(accounts_on):
    _account()
    at = _sign_in(_app(), "anna", PASSWORD)
    assert at.chat_input and "cookie" not in at.session_state


def test_forgot_password_without_emails_says_to_ask_the_owner(accounts_on):
    at = _app()
    _button(at, "Forgot your password?").click().run()
    assert "ask the TripMate owner" in at.info[0].value and not at.text_input
    _button(at, "Back to sign in").click().run()
    assert at.text_input[0].label == "Username or email address"


def test_forgot_password_says_the_same_for_any_email(accounts_on, outbox):
    _account()
    at = _app()
    _button(at, "Forgot your password?").click().run()
    answers = []
    for email in ("anna@example.com", "nobody@example.com"):
        at.text_input[0].input(email)
        _button(at, "Send reset link").click().run()
        answers.append(at.success[0].value)
    assert answers[0] == answers[1] and answers[0].startswith("If an account has this email")
    assert [(kind, to) for kind, to, _ in outbox if kind == "reset"] == [("reset", "anna@example.com")]


def test_the_reset_link_page_sets_a_new_password_once(accounts_on, outbox):
    _account()
    accounts.request_reset("anna@example.com", "https://app")
    link = next(values["link"] for kind, _, values in outbox if kind == "reset")
    token = re.search(r"reset=([\w\-]+)", link).group(1)
    at = AppTest.from_file("../app.py", default_timeout=30)
    at.query_params["reset"] = token
    at.run()
    assert [i.label for i in at.text_input] == ["New password", "Repeat password"]
    at.text_input[0].input(NEW_PASSWORD)
    at.text_input[1].input(NEW_PASSWORD + "x")
    _button(at, "Save new password").click().run()
    assert at.error[0].value == "The two passwords don't match."
    at.text_input[1].input(NEW_PASSWORD)
    _button(at, "Save new password").click().run()
    assert not at.exception and "new password is saved" in at.success[0].value
    _sign_in(at, "anna", NEW_PASSWORD)
    assert at.chat_input

    used = AppTest.from_file("../app.py", default_timeout=30)
    used.query_params["reset"] = token
    used.run()
    assert used.error[0].value.startswith("This link has expired or was already used") and not used.text_input


def test_the_confirm_link_confirms_the_email(accounts_on):
    _account(confirmed=False)
    token = accounts.new_token(accounts.waiting_accounts()[0]["id"], "confirm")
    at = AppTest.from_file("../app.py", default_timeout=30)
    at.query_params["confirm"] = token
    at.run()
    assert at.success[0].value == "Your email is confirmed. You can sign in now."
    assert accounts.waiting_accounts() == []


def _settings_open(account: dict) -> AppTest:
    """Settings kept open on every run, as the browser does while it's used, for a signed-in account."""
    def page():
        from frontend.components.common import init_state
        from frontend.pages.settings import settings_dialog
        init_state()
        settings_dialog()

    at = AppTest.from_function(page, default_timeout=30)
    at.session_state.account = account
    at.run()
    assert not at.exception
    return at


def test_the_owner_confirms_waiting_accounts_in_settings(accounts_on, monkeypatch):
    monkeypatch.setattr(config, "OWNER_EMAIL", "Owner@example.com")
    _account("owner", "owner@example.com")
    _account("bob", "bob@example.com", confirmed=False)
    at = _settings_open(accounts.sign_in("owner", PASSWORD))
    assert any(e.label == "Accounts waiting for confirmation (1)" for e in at.expander)
    _button(at, "Confirm").click().run()
    assert accounts.waiting_accounts() == [] and accounts.sign_in("bob", PASSWORD)["username"] == "bob"


def test_settings_doesnt_show_waiting_accounts_to_others(accounts_on, monkeypatch):
    monkeypatch.setattr(config, "OWNER_EMAIL", "owner@example.com")
    at = _settings_open(accounts.sign_in("anna", PASSWORD) if _account() else None)
    assert not any(e.label.startswith("Accounts waiting") for e in at.expander)


def test_the_language_can_be_switched_before_signing_in(accounts_on):
    at = _app()
    at.button_group[0].set_value("de").run()
    assert at.text_input[0].label == "Benutzername oder E-Mail-Adresse"
    assert [b.label for b in at.button] == ["Anmelden", "Passwort vergessen?", "Registrieren"]
