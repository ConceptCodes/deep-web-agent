"""Private per-turn JSONL audit logs for agent activity."""

from __future__ import annotations

import json
import os
import re
import threading
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit
from uuid import UUID, uuid4

from langchain_core.callbacks import BaseCallbackHandler

_PROJECT_ROOT = Path(__file__).resolve().parents[2]
_AUDIT_ROOT = _PROJECT_ROOT / ".deep_web_agent" / "audit"
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
_MAX_LOG_VALUE_CHARS = 500


def _safe_url(value: str) -> str:
    """Keep the URL destination while removing credentials, query, and fragment."""
    try:
        parsed = urlsplit(value)
        if parsed.scheme not in {"http", "https"} or not parsed.hostname:
            return _redact_string(value)
        host = parsed.hostname
        if parsed.port:
            host = f"{host}:{parsed.port}"
        return f"{parsed.scheme}://{host}{parsed.path}" + ("?[REDACTED]" if parsed.query else "")
    except ValueError:
        return "[REDACTED URL]"


def _redact_string(value: str) -> str:
    redacted = _BEARER_TOKEN.sub("Bearer [REDACTED]", value)
    redacted = _KEY_VALUE_SECRET.sub(r"\1\2[REDACTED]", redacted)
    if len(redacted) > _MAX_LOG_VALUE_CHARS:
        redacted = redacted[:_MAX_LOG_VALUE_CHARS] + "…[truncated]"
    return redacted


def _safe_value(value: Any, key: str | None = None) -> Any:
    if key is not None and _SENSITIVE_KEY.search(key):
        return "[REDACTED]"
    if isinstance(value, dict):
        return {str(item_key): _safe_value(item, str(item_key)) for item_key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_safe_value(item) for item in value]
    if isinstance(value, str):
        return _safe_url(value) if key and key.lower() in {"url", "href"} else _redact_string(value)
    if value is None or isinstance(value, (bool, int, float)):
        return value
    return f"<{type(value).__name__}>"


def _ensure_audit_root() -> Path:
    _AUDIT_ROOT.mkdir(mode=0o700, parents=True, exist_ok=True)
    resolved_root = _AUDIT_ROOT.resolve(strict=True)
    if not resolved_root.is_relative_to(_PROJECT_ROOT):
        raise OSError("Audit log directory must stay inside the project.")
    resolved_root.chmod(0o700)
    return resolved_root


class AuditLogHandler(BaseCallbackHandler):
    """Record lifecycle and tool activity without storing prompts or page contents."""

    def __init__(self) -> None:
        self.run_id = uuid4()
        audit_root = _ensure_audit_root()
        self.path = audit_root / f"{self.run_id}.jsonl"
        self._lock = threading.Lock()
        self.log_event("run_started")

    def log_event(self, event: str, **fields: Any) -> None:
        record = {
            "timestamp": datetime.now(UTC).isoformat(),
            "run_id": str(self.run_id),
            "event": event,
            **{key: _safe_value(value, key) for key, value in fields.items()},
        }
        line = (json.dumps(record, ensure_ascii=False, separators=(",", ":")) + "\n").encode("utf-8")
        flags = os.O_WRONLY | os.O_CREAT | os.O_APPEND
        if hasattr(os, "O_NOFOLLOW"):
            flags |= os.O_NOFOLLOW
        with self._lock:
            descriptor = os.open(self.path, flags, 0o600)
            try:
                remaining = memoryview(line)
                while remaining:
                    written = os.write(descriptor, remaining)
                    if written == 0:
                        raise OSError("Could not write audit event.")
                    remaining = remaining[written:]
            finally:
                os.close(descriptor)

    def on_chain_start(
        self,
        serialized: dict[str, Any],
        inputs: dict[str, Any],
        *,
        run_id: UUID,
        parent_run_id: UUID | None = None,
        name: str | None = None,
        **kwargs: Any,
    ) -> None:
        self.log_event(
            "chain_started",
            name=name or serialized.get("name", "chain"),
            callback_run_id=str(run_id),
            parent_run_id=str(parent_run_id) if parent_run_id else None,
            input_keys=sorted(str(key) for key in inputs),
        )

    def on_chain_end(
        self,
        outputs: dict[str, Any],
        *,
        run_id: UUID,
        parent_run_id: UUID | None = None,
        **kwargs: Any,
    ) -> None:
        self.log_event(
            "chain_finished",
            callback_run_id=str(run_id),
            parent_run_id=str(parent_run_id) if parent_run_id else None,
            output_keys=sorted(str(key) for key in outputs) if isinstance(outputs, dict) else [],
        )

    def on_chain_error(
        self,
        error: BaseException,
        *,
        run_id: UUID,
        parent_run_id: UUID | None = None,
        **kwargs: Any,
    ) -> None:
        self.log_event(
            "chain_failed",
            callback_run_id=str(run_id),
            parent_run_id=str(parent_run_id) if parent_run_id else None,
            error_type=type(error).__name__,
        )

    def on_tool_start(
        self,
        serialized: dict[str, Any],
        input_str: str,
        *,
        run_id: UUID,
        parent_run_id: UUID | None = None,
        inputs: dict[str, Any] | None = None,
        **kwargs: Any,
    ) -> None:
        self.log_event(
            "tool_started",
            tool=serialized.get("name", "tool"),
            callback_run_id=str(run_id),
            parent_run_id=str(parent_run_id) if parent_run_id else None,
            arguments=_safe_value(inputs, "arguments") if inputs is not None else {"length": len(input_str)},
        )

    def on_tool_end(
        self,
        output: Any,
        *,
        run_id: UUID,
        parent_run_id: UUID | None = None,
        **kwargs: Any,
    ) -> None:
        output_text = output if isinstance(output, str) else ""
        self.log_event(
            "tool_finished",
            callback_run_id=str(run_id),
            parent_run_id=str(parent_run_id) if parent_run_id else None,
            result_characters=len(output_text),
            status=(
                "error"
                if output_text.startswith(("Browser action failed:", "Vision evaluation failed:"))
                else "completed"
            ),
        )

    def on_tool_error(
        self,
        error: BaseException,
        *,
        run_id: UUID,
        parent_run_id: UUID | None = None,
        **kwargs: Any,
    ) -> None:
        self.log_event(
            "tool_failed",
            callback_run_id=str(run_id),
            parent_run_id=str(parent_run_id) if parent_run_id else None,
            error_type=type(error).__name__,
        )

    def on_chat_model_start(
        self,
        serialized: dict[str, Any],
        messages: list[list[Any]],
        *,
        run_id: UUID,
        parent_run_id: UUID | None = None,
        **kwargs: Any,
    ) -> None:
        self.log_event(
            "model_started",
            model=serialized.get("name", "chat_model"),
            callback_run_id=str(run_id),
            parent_run_id=str(parent_run_id) if parent_run_id else None,
            message_count=sum(len(batch) for batch in messages),
        )

    def on_llm_end(
        self,
        response: Any,
        *,
        run_id: UUID,
        parent_run_id: UUID | None = None,
        **kwargs: Any,
    ) -> None:
        self.log_event(
            "model_finished",
            callback_run_id=str(run_id),
            parent_run_id=str(parent_run_id) if parent_run_id else None,
        )

    def on_llm_error(
        self,
        error: BaseException,
        *,
        run_id: UUID,
        parent_run_id: UUID | None = None,
        **kwargs: Any,
    ) -> None:
        self.log_event(
            "model_failed",
            callback_run_id=str(run_id),
            parent_run_id=str(parent_run_id) if parent_run_id else None,
            error_type=type(error).__name__,
        )


def create_audit_handler() -> AuditLogHandler:
    """Create a private JSONL log for one CLI turn."""
    return AuditLogHandler()
