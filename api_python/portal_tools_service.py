from __future__ import annotations

import re


def sanitize_upi_extract_message(value: object) -> str:
    text = str(value or "").strip()
    if not text:
        return ""
    text = re.sub(r"(?i)bearer\s+[A-Za-z0-9._~+/=-]+", "Bearer [REDACTED]", text)
    text = re.sub(r"(?i)(access[_-]?token|session[_-]?token)([\"'\s:=]+)[^\s,}\]]+", r"\1\2[REDACTED]", text)
    text = re.sub(r"(?i)(https?://[^:/\s]+:)[^@\s]+@", r"\1***@", text)
    text = re.sub(r"(?i)(password=)[^&\s]+", r"\1***", text)
    return text[:8000]
