"""Shared privacy policy for terminal activity and audit logging."""

from __future__ import annotations

import re
from typing import Any
from urllib.parse import urlsplit

_SENSITIVE_KEY = re.compile(
    r"password|passwd|secret|token|api[_-]?key|authorization|cookie|credential|"
    r"^value$|^text$|^content$|^prompt$|^question$|^query$",
    re.IGNORECASE,
)
_BEARER_TOKEN = re.compile(r"(?i)\bBearer\s+[A-Za-z0-9._~+/=-]+")
_KEY_VALUE_SECRET = re.compile(
    r"(?i)\b(api[_-]?key|access[_-]?token|refresh[_-]?token|password|secret)"
    r"(\s*[:=]\s*)[^\s&,;]+"
)
_MAX_VALUE_CHARS = 500


def _safe_url(value: str) -> str:
    """Keep the URL destination while removing credentials, query, and fragment."""
    try:
        parsed = urlsplit(value)
        if parsed.scheme not in {"http", "https"} or not parsed.hostname:
            return _redact_string(value)
        host = parsed.hostname
        if ":" in host:
            host = f"[{host}]"
        if parsed.port:
            host = f"{host}:{parsed.port}"
        return _redact_string(
            f"{parsed.scheme}://{host}{parsed.path}"
            + ("?[REDACTED]" if parsed.query else "")
        )
    except ValueError:
        return "[REDACTED URL]"


def _redact_string(value: str) -> str:
    redacted = _BEARER_TOKEN.sub("Bearer [REDACTED]", value)
    redacted = _KEY_VALUE_SECRET.sub(r"\1\2[REDACTED]", redacted)
    if len(redacted) > _MAX_VALUE_CHARS:
        redacted = redacted[:_MAX_VALUE_CHARS] + "…[truncated]"
    return redacted


def sanitize_activity(value: Any, key: str | None = None) -> Any:
    """Return a JSON-compatible copy for terminal activity and audit fields.

    Redact sensitive keys recursively, remove credentials/query/fragment from
    URL and href fields, and mask recognized secrets in strings. Bound string
    values to 500 characters and describe unknown objects without rendering them.
    This policy does not guarantee removal of arbitrary secrets from free text.
    """
    if key is not None and _SENSITIVE_KEY.search(key):
        return "[REDACTED]"
    if isinstance(value, dict):
        return {str(item_key): sanitize_activity(item, str(item_key)) for item_key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [sanitize_activity(item) for item in value]
    if isinstance(value, str):
        return _safe_url(value) if key and key.lower() in {"url", "href"} else _redact_string(value)
    if value is None or isinstance(value, (bool, int, float)):
        return value
    return f"<{type(value).__name__}>"


