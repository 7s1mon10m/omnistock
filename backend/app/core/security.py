"""Password hashing and JWT helpers.

Passwords use PBKDF2-HMAC-SHA256 from the standard library so a small
deployment needs no extra native dependency.  Tokens are signed with HS256 via
PyJWT.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import os
import secrets
import time
from typing import Any

import jwt

from app.core.config import settings

PBKDF2_ALGO = "pbkdf2_sha256"


# --------------------------------------------------------------------- passwords
def hash_password(password: str, rounds: int | None = None) -> str:
    """Return a self-describing hash string: ``algo$rounds$salt$hash``."""
    rounds = rounds or settings.AUTH_PBKDF2_ROUNDS
    salt = os.urandom(16)
    derived = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, rounds)
    return "$".join(
        [
            PBKDF2_ALGO,
            str(rounds),
            base64.b64encode(salt).decode("ascii"),
            base64.b64encode(derived).decode("ascii"),
        ]
    )


def verify_password(password: str, stored: str | None) -> bool:
    """Constant-time verification against a stored hash string."""
    if not stored:
        return False
    try:
        algo, rounds, salt_b64, hash_b64 = stored.split("$")
    except ValueError:
        return False
    if algo != PBKDF2_ALGO:
        return False
    try:
        salt = base64.b64decode(salt_b64)
        expected = base64.b64decode(hash_b64)
    except (ValueError, TypeError):
        return False
    derived = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, int(rounds))
    return hmac.compare_digest(derived, expected)


def needs_rehash(stored: str) -> bool:
    """True when a stored hash used fewer rounds than currently configured."""
    try:
        rounds = int(stored.split("$")[1])
    except (ValueError, IndexError):
        return True
    return rounds < settings.AUTH_PBKDF2_ROUNDS


# ------------------------------------------------------------------------ tokens
def create_access_token(subject: str, claims: dict[str, Any] | None = None) -> str:
    now = int(time.time())
    payload: dict[str, Any] = {
        "sub": str(subject),
        "type": "access",
        "iat": now,
        "exp": now + settings.AUTH_ACCESS_TTL_MINUTES * 60,
    }
    if claims:
        payload.update(claims)
    return jwt.encode(payload, settings.AUTH_SECRET_KEY, algorithm=settings.AUTH_ALGORITHM)


def create_refresh_token(subject: str, jti: str) -> str:
    now = int(time.time())
    payload = {
        "sub": str(subject),
        "type": "refresh",
        "jti": jti,
        "iat": now,
        "exp": now + settings.AUTH_REFRESH_TTL_DAYS * 86400,
    }
    return jwt.encode(payload, settings.AUTH_SECRET_KEY, algorithm=settings.AUTH_ALGORITHM)


def decode_token(token: str) -> dict[str, Any]:
    """Decode and validate a token, raising :class:`jwt.PyJWTError` subclasses."""
    return jwt.decode(token, settings.AUTH_SECRET_KEY, algorithms=[settings.AUTH_ALGORITHM])


def new_refresh_jti() -> str:
    return secrets.token_urlsafe(32)


def refresh_token_expires_at() -> int:
    return int(time.time()) + settings.AUTH_REFRESH_TTL_DAYS * 86400
