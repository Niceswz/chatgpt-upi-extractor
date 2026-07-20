from __future__ import annotations

import os
import sqlite3
from pathlib import Path


SCHEMA = """
CREATE TABLE IF NOT EXISTS settings (
    id TEXT PRIMARY KEY,
    content TEXT NOT NULL DEFAULT '',
    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS upi_link_extractions (
    id TEXT PRIMARY KEY,
    job_id TEXT NOT NULL UNIQUE,
    user_id TEXT NOT NULL DEFAULT '',
    email TEXT NOT NULL DEFAULT '',
    promo_state TEXT NOT NULL DEFAULT '',
    status TEXT NOT NULL CHECK(status IN ('processing', 'completed', 'failed')),
    long_url TEXT,
    long_url_masked TEXT NOT NULL DEFAULT '',
    currency TEXT NOT NULL DEFAULT 'INR',
    result_message TEXT NOT NULL DEFAULT '',
    result_message_raw TEXT,
    steps_json TEXT,
    debug_json TEXT,
    fail_stage TEXT NOT NULL DEFAULT '',
    amount INTEGER,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_upi_extractions_created
    ON upi_link_extractions(created_at DESC);
CREATE INDEX IF NOT EXISTS idx_upi_extractions_user
    ON upi_link_extractions(user_id, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_upi_extractions_status
    ON upi_link_extractions(status, updated_at);
"""


def _database_path() -> Path:
    root = Path(os.environ.get("VERIFY_APP_ROOT") or Path(__file__).resolve().parents[1])
    return Path(os.environ.get("CHATUPI_DATABASE") or root / "data" / "chatupi.sqlite3")


def get_primary_db() -> sqlite3.Connection:
    path = _database_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(path, timeout=30)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    conn.execute("PRAGMA busy_timeout=30000")
    return conn


def init_database() -> None:
    with get_primary_db() as conn:
        conn.executescript(SCHEMA)
        conn.execute(
            "INSERT OR IGNORE INTO settings (id, content) VALUES (?, ?)",
            ("upi_link_submit_override", "online"),
        )
        conn.commit()


def cleanup_database(retention_days: int) -> int:
    days = min(max(int(retention_days), 1), 3650)
    with get_primary_db() as conn:
        cursor = conn.execute(
            "DELETE FROM upi_link_extractions WHERE created_at < datetime('now', ?)",
            (f"-{days} days",),
        )
        conn.commit()
        return max(cursor.rowcount, 0)
