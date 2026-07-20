from __future__ import annotations

import hashlib
import hmac
import os
import secrets
import time
from collections import defaultdict, deque

from fastapi import HTTPException, Request


_ATTEMPTS: dict[str, deque[float]] = defaultdict(deque)


def hash_password(password: str, *, salt: str | None = None) -> str:
    actual_salt = salt or secrets.token_hex(16)
    rounds = 310_000
    digest = hashlib.pbkdf2_hmac(
        "sha256", password.encode("utf-8"), bytes.fromhex(actual_salt), rounds
    ).hex()
    return f"pbkdf2_sha256${rounds}${actual_salt}${digest}"


def verify_password(password: str, encoded: str) -> bool:
    try:
        algorithm, rounds_raw, salt, expected = encoded.split("$", 3)
        if algorithm != "pbkdf2_sha256":
            return False
        digest = hashlib.pbkdf2_hmac(
            "sha256",
            password.encode("utf-8"),
            bytes.fromhex(salt),
            int(rounds_raw),
        ).hex()
        return hmac.compare_digest(digest, expected)
    except (TypeError, ValueError):
        return False


def login_allowed(client_key: str, *, limit: int = 8, window: int = 900) -> bool:
    now = time.monotonic()
    attempts = _ATTEMPTS[client_key]
    while attempts and now - attempts[0] > window:
        attempts.popleft()
    if len(attempts) >= limit:
        return False
    attempts.append(now)
    return True


def clear_login_attempts(client_key: str) -> None:
    _ATTEMPTS.pop(client_key, None)


def current_user(request: Request) -> str:
    return str(request.session.get("user_id") or "").strip()


def require_user(request: Request) -> str:
    user_id = current_user(request)
    if not user_id:
        raise HTTPException(status_code=401, detail="Please sign in first")
    return user_id


def issue_csrf(request: Request) -> str:
    token = str(request.session.get("csrf") or "")
    if not token:
        token = secrets.token_urlsafe(32)
        request.session["csrf"] = token
    return token


def require_csrf(request: Request) -> None:
    expected = str(request.session.get("csrf") or "")
    supplied = str(request.headers.get("x-csrf-token") or "")
    if not expected or not supplied or not hmac.compare_digest(expected, supplied):
        raise HTTPException(status_code=403, detail="CSRF validation failed. Please refresh and try again.")


def configured_password_hash() -> str:
    return str(os.environ.get("CHATUPI_PASSWORD_HASH") or "").strip()
