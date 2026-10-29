"""The owner's commands for password accounts, for when there's no email sender and no Google sign-in
to reach Settings (for example on a computer):

    python -m backend.accounts waiting            # accounts waiting for confirmation
    python -m backend.accounts confirm <name>     # confirm one, by username or email
    python -m backend.accounts reset-link <name>  # a one-time link to choose a new password

A reset link works once, for 30 minutes. It points at APP_URL, or http://localhost:8501 when that isn't set.

They use the same database as the app (HISTORY_DIR, or .history/ in the project folder).
"""

import sys

from backend import config
from backend.accounts import accounts


def main(args: list[str]) -> int:
    if args == ["waiting"]:
        waiting = accounts.waiting_accounts()
        for account in waiting:
            print(f"{account['username']}  {account['email']}")
        print(f"{len(waiting)} waiting.")
        return 0
    if len(args) == 2 and args[0] == "confirm":
        name = args[1].strip().lower()
        match = [a for a in accounts.waiting_accounts() if name in (a["username"].lower(), a["email"])]
        if not match:
            print(f"No account waiting with the name or email {args[1]!r}.")
            return 1
        accounts.confirm_account(match[0]["id"])
        print(f"Confirmed {match[0]['username']} ({match[0]['email']}). They can sign in now.")
        return 0
    if len(args) == 2 and args[0] == "reset-link":
        account = accounts.find_account(args[1])
        if account is None:
            print(f"No account with the name or email {args[1]!r}.")
            return 1
        base = (config.APP_URL or "http://localhost:8501").rstrip("/")
        print(f"Reset link for {account['username']}, valid once for 30 minutes:")
        print(f"{base}/?reset={accounts.new_token(account['id'], 'reset')}")
        return 0
    print(__doc__)
    return 2


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
