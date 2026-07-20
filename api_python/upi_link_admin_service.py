from __future__ import annotations

import json
import re
import uuid
from typing import Any

from .db import get_primary_db
from .portal_tools_service import sanitize_upi_extract_message


UPI_LINK_SUBMIT_OVERRIDE_SETTING_ID = "upi_link_submit_override"


def _mask_url(url: str) -> str:
    value = str(url or "").strip()
    if not value:
        return ""
    if len(value) <= 36:
        return "***"
    return f"{value[:22]}…{value[-10:]}"


def _mask_proxy(proxy: str) -> str:
    value = str(proxy or "").strip()
    if not value:
        return ""
    value = re.sub(r"(://[^:/@]+:)[^@]+@", r"\1***@", value)
    return value[:180]


def get_upi_link_submit_override() -> str:
    with get_primary_db() as conn:
        row = conn.execute(
            "SELECT content FROM settings WHERE id = ?",
            (UPI_LINK_SUBMIT_OVERRIDE_SETTING_ID,),
        ).fetchone()
    mode = str(row["content"] if row else "online").strip().lower()
    return mode if mode in {"online", "offline"} else "online"


def set_upi_link_submit_override(mode: str) -> str:
    normalized = str(mode or "").strip().lower()
    if normalized not in {"online", "offline"}:
        raise ValueError("mode must be online or offline")
    with get_primary_db() as conn:
        conn.execute(
            """
            INSERT INTO settings (id, content, updated_at)
            VALUES (?, ?, CURRENT_TIMESTAMP)
            ON CONFLICT(id) DO UPDATE SET
                content = excluded.content,
                updated_at = CURRENT_TIMESTAMP
            """,
            (UPI_LINK_SUBMIT_OVERRIDE_SETTING_ID, normalized),
        )
        conn.commit()
    return normalized


def insert_upi_link_record(
    *,
    job_id: str,
    user_id: str = "",
    email: str = "",
    promo_state: str = "",
    status: str = "processing",
    long_url: str = "",
    currency: str = "INR",
    result_message: str = "",
    result_message_raw: str = "",
    steps_json: str = "",
    debug_json: str = "",
    fail_stage: str = "",
    amount: int | None = None,
) -> str:
    record_id = str(job_id or uuid.uuid4().hex).strip() or uuid.uuid4().hex
    normalized_status = str(status or "processing").strip().lower()
    if normalized_status not in {"processing", "completed", "failed"}:
        normalized_status = "processing"
    raw = sanitize_upi_extract_message(result_message_raw or result_message)
    message = sanitize_upi_extract_message(result_message or raw)[:512]
    url = str(long_url or "").strip()
    with get_primary_db() as conn:
        conn.execute(
            """
            INSERT INTO upi_link_extractions
                (id, job_id, user_id, email, promo_state, status, long_url,
                 long_url_masked, currency, result_message, result_message_raw,
                 steps_json, debug_json, fail_stage, amount)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(id) DO UPDATE SET
                user_id = excluded.user_id,
                email = excluded.email,
                promo_state = excluded.promo_state,
                status = excluded.status,
                long_url = excluded.long_url,
                long_url_masked = excluded.long_url_masked,
                currency = excluded.currency,
                result_message = excluded.result_message,
                result_message_raw = excluded.result_message_raw,
                steps_json = excluded.steps_json,
                debug_json = excluded.debug_json,
                fail_stage = excluded.fail_stage,
                amount = excluded.amount,
                updated_at = CURRENT_TIMESTAMP
            """,
            (
                record_id,
                record_id,
                str(user_id or "")[:128],
                str(email or "")[:255],
                str(promo_state or "")[:32],
                normalized_status,
                url or None,
                _mask_url(url),
                str(currency or "INR")[:8] or "INR",
                message,
                raw[:8000] or None,
                str(steps_json or "") or None,
                str(debug_json or "") or None,
                str(fail_stage or "")[:64],
                amount,
            ),
        )
        conn.commit()
    return record_id


def finalize_upi_link_record(
    job_id: str,
    *,
    status: str,
    long_url: str = "",
    currency: str = "INR",
    result_message: str = "",
    result_message_raw: str = "",
    steps_json: str = "",
    debug_json: str = "",
    fail_stage: str = "",
    amount: int | None = None,
) -> None:
    record_id = str(job_id or "").strip()
    if not record_id:
        return
    normalized_status = str(status or "failed").strip().lower()
    if normalized_status not in {"processing", "completed", "failed"}:
        normalized_status = "failed"
    raw = sanitize_upi_extract_message(result_message_raw or result_message)
    message = sanitize_upi_extract_message(result_message or raw)[:512]
    url = str(long_url or "").strip()
    with get_primary_db() as conn:
        conn.execute(
            """
            UPDATE upi_link_extractions
            SET status = ?, long_url = ?, long_url_masked = ?, currency = ?,
                result_message = ?, result_message_raw = ?, steps_json = ?,
                debug_json = ?, fail_stage = ?, amount = ?,
                updated_at = CURRENT_TIMESTAMP
            WHERE id = ?
            """,
            (
                normalized_status,
                url or None,
                _mask_url(url),
                str(currency or "INR")[:8] or "INR",
                message,
                raw[:8000] or None,
                str(steps_json or "") or None,
                str(debug_json or "") or None,
                str(fail_stage or "")[:64],
                amount,
                record_id,
            ),
        )
        conn.commit()


def list_upi_link_records(*, search: str = "", limit: int = 80, offset: int = 0) -> dict[str, Any]:
    term = str(search or "").strip()[:128]
    limit = min(max(int(limit), 1), 200)
    offset = max(int(offset), 0)
    where = "1 = 1"
    params: list[Any] = []
    if term:
        where += " AND (email LIKE ? OR user_id LIKE ? OR id LIKE ? OR result_message LIKE ?)"
        like = f"%{term}%"
        params.extend([like, like, like, like])
    with get_primary_db() as conn:
        total_row = conn.execute(
            f"SELECT COUNT(*) AS cnt FROM upi_link_extractions WHERE {where}", params
        ).fetchone()
        rows = conn.execute(
            f"""
            SELECT id, job_id, user_id, email, promo_state, status, long_url,
                   long_url_masked, currency, result_message, result_message_raw,
                   steps_json, debug_json, fail_stage, amount,
                   CAST(strftime('%s', created_at) AS INTEGER) * 1000 AS timestamp
            FROM upi_link_extractions
            WHERE {where}
            ORDER BY created_at DESC
            LIMIT ? OFFSET ?
            """,
            [*params, limit, offset],
        ).fetchall()
    items: list[dict[str, Any]] = []
    for row in rows:
        item = dict(row)
        for source, target, fallback in (
            ("steps_json", "steps", []),
            ("debug_json", "debug", {}),
        ):
            try:
                parsed = json.loads(item.get(source) or "")
                item[target] = parsed if isinstance(parsed, type(fallback)) else fallback
            except (TypeError, json.JSONDecodeError):
                item[target] = fallback
        items.append(
            {
                "id": item.get("id"),
                "job_id": item.get("job_id") or item.get("id"),
                "user_id": item.get("user_id") or "",
                "email": item.get("email") or "",
                "promo_state": item.get("promo_state") or "",
                "status": item.get("status") or "",
                "long_url": item.get("long_url") or "",
                "long_url_masked": item.get("long_url_masked") or "",
                "currency": item.get("currency") or "INR",
                "message": item.get("result_message") or "",
                "message_raw": item.get("result_message_raw") or "",
                "fail_stage": item.get("fail_stage") or "",
                "amount": item.get("amount"),
                "steps": item["steps"],
                "debug": item["debug"],
                "timestamp": int(item.get("timestamp") or 0),
            }
        )
    return {"items": items, "total": int(total_row["cnt"] if total_row else 0)}


__all__ = [
    "_mask_proxy",
    "finalize_upi_link_record",
    "get_upi_link_submit_override",
    "insert_upi_link_record",
    "list_upi_link_records",
    "set_upi_link_submit_override",
]
