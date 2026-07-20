from __future__ import annotations

import asyncio
import json
import os
import re
import time
from contextlib import asynccontextmanager, suppress
from pathlib import Path

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from pydantic import BaseModel, Field
from starlette.middleware.sessions import SessionMiddleware
from starlette.middleware.trustedhost import TrustedHostMiddleware

from .db import cleanup_database, get_primary_db, init_database
from .portal_tools_service import sanitize_upi_extract_message
from .security import (
    clear_login_attempts,
    configured_password_hash,
    current_user,
    issue_csrf,
    login_allowed,
    require_csrf,
    require_user,
    verify_password,
)
from .upi_link_admin_service import (
    _mask_proxy,
    get_upi_link_submit_override,
    list_upi_link_records,
    set_upi_link_submit_override,
)
from .upi_link_service import (
    get_upi_link_status,
    recover_stale_upi_records,
    resolve_upi_promotion_proxy,
    resolve_upi_proxy,
    start_upi_link_extract,
)


ROOT = Path(os.environ.get("VERIFY_APP_ROOT") or Path(__file__).resolve().parents[1])
BASE_PATH = str(os.environ.get("CHATUPI_BASE_PATH") or "/CHATUPI").rstrip("/")
RETENTION_DAYS = int(os.environ.get("CHATUPI_RETENTION_DAYS") or 30)
HOURLY_LIMIT = int(os.environ.get("CHATUPI_HOURLY_LIMIT") or 10)
SECRET_KEY = str(os.environ.get("CHATUPI_SECRET_KEY") or "")
templates = Jinja2Templates(directory=str(Path(__file__).parent / "templates"))


class LoginBody(BaseModel):
    password: str = Field(min_length=1, max_length=512)


class ExtractBody(BaseModel):
    access_token: str = Field(min_length=20, max_length=200_000)


class ModeBody(BaseModel):
    mode: str


async def _cleanup_loop() -> None:
    while True:
        await asyncio.sleep(3600)
        with suppress(Exception):
            await asyncio.to_thread(cleanup_database, RETENTION_DAYS)
            cutoff = time.time() - min(max(RETENTION_DAYS, 1), 3650) * 86400
            for folder in (ROOT / "run-output" / "upi-link-jobs", ROOT / "run-output" / "upi-link-debug"):
                if not folder.exists():
                    continue
                for path in folder.glob("*.json"):
                    if path.stat().st_mtime < cutoff:
                        path.unlink(missing_ok=True)


@asynccontextmanager
async def lifespan(_: FastAPI):
    if len(SECRET_KEY) < 48:
        raise RuntimeError("CHATUPI_SECRET_KEY is missing or too short")
    if not configured_password_hash().startswith("pbkdf2_sha256$"):
        raise RuntimeError("CHATUPI_PASSWORD_HASH is missing or invalid")
    init_database()
    recover_stale_upi_records(max_age_sec=360)
    cleanup_database(RETENTION_DAYS)
    task = asyncio.create_task(_cleanup_loop())
    try:
        yield
    finally:
        task.cancel()
        with suppress(asyncio.CancelledError):
            await task


app = FastAPI(
    title="CHATUPI",
    docs_url=None,
    redoc_url=None,
    openapi_url=None,
    lifespan=lifespan,
)
app.add_middleware(
    SessionMiddleware,
    secret_key=SECRET_KEY or "startup-validation-will-reject-this-value",
    session_cookie="chatupi_session",
    max_age=8 * 3600,
    path=BASE_PATH or "/",
    same_site="strict",
    https_only=True,
)
_raw_hosts = str(os.environ.get("CHATUPI_ALLOWED_HOSTS") or "localhost,127.0.0.1").strip()
ALLOWED_HOSTS = [h.strip() for h in _raw_hosts.split(",") if h.strip()] or ["localhost", "127.0.0.1"]
app.add_middleware(
    TrustedHostMiddleware,
    allowed_hosts=ALLOWED_HOSTS,
)


@app.exception_handler(HTTPException)
async def http_error(_: Request, exc: HTTPException) -> JSONResponse:
    return JSONResponse({"success": False, "error": str(exc.detail)}, status_code=exc.status_code)


@app.get("/healthz")
async def healthz() -> dict:
    with get_primary_db() as conn:
        conn.execute("SELECT 1").fetchone()
    return {"ok": True, "service": "chatupi"}


@app.get("/login", response_class=HTMLResponse)
async def login_page(request: Request):
    if current_user(request):
        return RedirectResponse(f"{BASE_PATH}/", status_code=303)
    return templates.TemplateResponse(request=request, name="login.html", context={"base_path": BASE_PATH})


@app.get("/", response_class=HTMLResponse)
async def index(request: Request):
    if not current_user(request):
        return RedirectResponse(f"{BASE_PATH}/login", status_code=303)
    csrf = issue_csrf(request)
    return templates.TemplateResponse(
        request=request,
        name="index.html",
        context={"base_path": BASE_PATH, "csrf_token": csrf},
    )


@app.post("/api/auth/login")
async def login(request: Request, body: LoginBody):
    client_key = request.client.host if request.client else "unknown"
    if not login_allowed(client_key):
        raise HTTPException(status_code=429, detail="Too many login attempts. Please try again later.")
    expected = configured_password_hash()
    if not expected or not verify_password(body.password, expected):
        await asyncio.sleep(0.35)
        raise HTTPException(status_code=401, detail="Invalid password")
    clear_login_attempts(client_key)
    request.session.clear()
    request.session["user_id"] = "owner"
    csrf = issue_csrf(request)
    return {"success": True, "csrf_token": csrf}


@app.post("/api/auth/logout")
async def logout(request: Request):
    require_user(request)
    require_csrf(request)
    request.session.clear()
    return {"success": True}


@app.get("/api/config")
async def config(request: Request):
    require_user(request)
    india = resolve_upi_proxy()
    promotion = resolve_upi_promotion_proxy(india)
    dedicated_promotion = str(os.environ.get("UPI_LINK_PROMOTION_PROXY") or "").strip()
    return {
        "success": True,
        "mode": get_upi_link_submit_override(),
        "india_proxy_configured": bool(india),
        "promotion_proxy_configured": bool(dedicated_promotion),
        "india_proxy_masked": _mask_proxy(india),
        "promotion_proxy_masked": _mask_proxy(promotion),
        "hourly_limit": HOURLY_LIMIT,
    }


@app.post("/api/settings/mode")
async def save_mode(request: Request, body: ModeBody):
    require_user(request)
    require_csrf(request)
    try:
        mode = set_upi_link_submit_override(body.mode)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return {"success": True, "mode": mode}


def _hourly_usage(user_id: str) -> int:
    with get_primary_db() as conn:
        row = conn.execute(
            """
            SELECT COUNT(*) AS cnt FROM upi_link_extractions
            WHERE user_id = ? AND created_at >= datetime('now', '-1 hour')
            """,
            (user_id,),
        ).fetchone()
    return int(row["cnt"] if row else 0)


@app.post("/api/extract")
async def extract(request: Request, body: ExtractBody):
    user_id = require_user(request)
    require_csrf(request)
    if get_upi_link_submit_override() == "offline":
        raise HTTPException(status_code=503, detail="UPI extraction is under maintenance")
    india = resolve_upi_proxy()
    promotion = resolve_upi_promotion_proxy(india)
    dedicated_promotion = str(os.environ.get("UPI_LINK_PROMOTION_PROXY") or "").strip()
    if not india or not promotion or not dedicated_promotion:
        raise HTTPException(status_code=503, detail="India proxy or Vietnam promotion proxy is not configured")
    if _hourly_usage(user_id) >= HOURLY_LIMIT:
        raise HTTPException(status_code=429, detail="Hourly job limit reached")
    raw = body.access_token.strip()
    if not (raw.startswith("{") or raw.lower().startswith("bearer ") or raw.count(".") >= 2):
        raise HTTPException(status_code=400, detail="Please paste a full Session JSON or a valid accessToken")
    result = await asyncio.to_thread(start_upi_link_extract, raw, user_id=user_id)
    if not result.get("success"):
        error = sanitize_upi_extract_message(result.get("error")) or "Failed to create job"
        raise HTTPException(status_code=400, detail=error)
    return result


@app.get("/api/status")
async def status(request: Request, job_id: str):
    user_id = require_user(request)
    if not re.fullmatch(r"[a-f0-9]{32}", job_id or ""):
        raise HTTPException(status_code=400, detail="Invalid job_id")
    result = get_upi_link_status(job_id, user_id=user_id)
    if not result.get("success"):
        raise HTTPException(status_code=404, detail=result.get("error") or "Job not found")
    return result


@app.get("/api/records")
async def records(request: Request, search: str = "", limit: int = 80, offset: int = 0):
    require_user(request)
    recover_stale_upi_records(max_age_sec=360)
    return {"success": True, **list_upi_link_records(search=search, limit=limit, offset=offset)}
