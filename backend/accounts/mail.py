"""Emails for accounts (confirm an address, reset a password), sent through Brevo's email API.

Without BREVO_API_KEY and MAIL_FROM nothing is sent: sign-ups then wait for the owner to confirm them,
and "Forgot your password?" says to ask the owner. The texts are in English and German, like the pages.
"""

import logging

import requests

from backend import config

BREVO_URL = "https://api.brevo.com/v3/smtp/email"
log = logging.getLogger(__name__)

TEXTS = {
    "confirm": {
        "en": ("Confirm your TripMate account",
               "Hello {username},\n\nopen this link to confirm your email address and start using TripMate:\n\n"
               "{link}\n\nThe link works for 24 hours. If you didn't sign up, you can ignore this email."),
        "de": ("Bestätige dein TripMate-Konto",
               "Hallo {username},\n\nöffne diesen Link, um deine E-Mail-Adresse zu bestätigen und TripMate zu "
               "nutzen:\n\n{link}\n\nDer Link gilt 24 Stunden. Wenn du dich nicht registriert hast, kannst du "
               "diese E-Mail ignorieren."),
    },
    "reset": {
        "en": ("Choose a new TripMate password",
               "Hello {username},\n\nopen this link to choose a new password:\n\n{link}\n\n"
               "The link works once, for 30 minutes. If you didn't ask for it, you can ignore this email; "
               "your password stays the same."),
        "de": ("Wähle ein neues TripMate-Passwort",
               "Hallo {username},\n\nöffne diesen Link, um ein neues Passwort zu wählen:\n\n{link}\n\n"
               "Der Link funktioniert einmal, 30 Minuten lang. Wenn du ihn nicht angefordert hast, kannst du "
               "diese E-Mail ignorieren; dein Passwort bleibt gleich."),
    },
}


def ready() -> bool:
    """True when emails can be sent (a Brevo key and a sender address are set)."""
    return bool(config.BREVO_API_KEY and config.MAIL_FROM)


def send(kind: str, to: str, language: str, **values) -> bool:
    """Sends one of the TEXTS emails. False if it isn't set up or the email service refused it."""
    if not ready():
        return False
    subject, body = TEXTS[kind]["de" if language == "de" else "en"]
    try:
        response = requests.post(
            BREVO_URL, timeout=config.LIVE_TIMEOUT_SECONDS,
            headers={"api-key": config.BREVO_API_KEY, "accept": "application/json"},
            json={"sender": {"name": "TripMate", "email": config.MAIL_FROM}, "to": [{"email": to}],
                  "subject": subject, "textContent": body.format(**values)})
        response.raise_for_status()
        return True
    except requests.RequestException as error:  # logged through redaction, so the key never shows
        log.warning("Couldn't send the %s email: %s", kind, error)
        return False
