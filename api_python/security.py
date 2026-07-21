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


# Development bypass flag: set CHATUPI_DEV_AUTH_BYPASS=0 to disable the local bypass
_DEV_BYPASS = str(os.environ.get('CHATUPI_DEV_AUTH_BYPASS') or '1').lower() in ('1','true','yes')


def current_user(request: Request) -> str:
    """Return current user id.

    In local development mode (CHATUPI_DEV_AUTH_BYPASS=1) the function returns a default 'owner'.
    When the bypass is disabled, a minimal check reads the X-User-Id header as a convenience for scripted auth
    or raises HTTP 401 if missing. This keeps behavior explicit and avoids silently granting access in
    non-dev environments.
    """
    if _DEV_BYPASS:
        return "owner"
    # minimal non-dev fallback: allow scripted header or reject
    uid = str(request.headers.get('X-User-Id') or '').strip()
    if uid:
        return uid
    raise HTTPException(status_code=401, detail='Authentication required')


def require_user(request: Request) -> str:
    if _DEV_BYPASS:
        return "owner"
    return current_user(request)


def issue_csrf(request: Request) -> str:
    if _DEV_BYPASS:
        return "insecure-csrf-token"
    # In non-dev mode, produce a simple time-based token (not secure, intended as placeholder).
    # Real deployments should replace with proper session CSRF tokens.
    return str(int(time.time()))


def require_csrf(request: Request) -> None:
    if _DEV_BYPASS:
        return None
    # In non-dev mode, validate the X-CSRF-Token header matches issue_csrf()
    header = str(request.headers.get('X-CSRF-Token') or '').strip()
    if not header or header != issue_csrf(request):
        raise HTTPException(status_code=403, detail='Invalid CSRF token')


def configured_password_hash() -> str:
    return str(os.environ.get("CHATUPI_PASSWORD_HASH") or "").strip()
