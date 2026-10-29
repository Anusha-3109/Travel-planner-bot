"""Password hashing with scrypt (in Python's hashlib). Only a salted hash is stored, never the password.

A stored hash looks like "scrypt$16384$8$1$<salt>$<hash>". The settings are part of it, so they can be
made stronger later and old hashes still check.
"""

import hashlib
import hmac
import secrets
import unicodedata

N, R, P = 2**14, 8, 1  # about 16 MB and a few hundredths of a second per check: slow for anyone guessing
SALT_BYTES, HASH_BYTES = 16, 32
MIN_LENGTH, MAX_LENGTH = 10, 200


def _scrypt(password: str, salt: bytes, n: int, r: int, p: int) -> bytes:
    # NFKC makes "ü" typed as one character or as u + accent the same password.
    text = unicodedata.normalize("NFKC", password).encode()
    return hashlib.scrypt(text, salt=salt, n=n, r=r, p=p, maxmem=64 * 1024 * 1024, dklen=HASH_BYTES)


def hash_password(password: str) -> str:
    """The salted hash to store. A random salt means two equal passwords get different hashes."""
    salt = secrets.token_bytes(SALT_BYTES)
    return f"scrypt${N}${R}${P}${salt.hex()}${_scrypt(password, salt, N, R, P).hex()}"


def check_password(password: str, stored: str) -> bool:
    """Hashes the typed password with the stored salt and compares in constant time, so the time
    taken doesn't show how much of it was right."""
    try:
        name, n, r, p, salt, expected = stored.split("$")
        if name != "scrypt":
            return False
        digest = _scrypt(password, bytes.fromhex(salt), int(n), int(r), int(p))
    except ValueError:
        return False
    return hmac.compare_digest(digest, bytes.fromhex(expected))


# Checked when nobody has the typed name, so a wrong name takes as long as a wrong password.
DUMMY_HASH = hash_password(secrets.token_hex(16))
