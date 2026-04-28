"""Protocol error helpers for chat endpoints."""

from __future__ import annotations

from dataclasses import dataclass
from time import time
from typing import Any

from protocol.protocol_events import ProtocolValidationError, validate_server_event


@dataclass(frozen=True, slots=True)
class ToolEvent:
    trace_id: str
    tool_call_id: str
    name: str
    arguments: str
    result: str
    event: str = "tool"


@dataclass(frozen=True, slots=True)
class ToolErrorEvent:
    trace_id: str
    error: str
    partial_steps_count: int
    tool_call_id: str = ""
    name: str = ""
    status: str = "phase_error"
    event: str = "tool_error"


@dataclass(frozen=True, slots=True)
class DoneEvent:
    trace_id: str
    session_id: str
    reply: str
    knowledge_results: list[dict[str, Any]]
    memory_results: list[dict[str, Any]]
    tool_steps: list[dict[str, Any]]
    event: str = "done"


def build_protocol_error(
    error_code: str,
    message: str,
    *,
    retry_after_ms: int | None = None,
) -> dict[str, object]:
    """Build and validate a server_error protocol event."""
    payload: dict[str, object] = {
        "event": "server_error",
        "error_code": error_code,
        "message": message,
        "timestamp": int(time()),
    }
    if retry_after_ms is not None:
        payload["retry_after_ms"] = retry_after_ms
    try:
        validate_server_event(payload)
    except ProtocolValidationError:
        payload["error_code"] = "INTERNAL_ERROR"
        validate_server_event(payload)
    return payload


def protocol_error_code_for_exception(message: str) -> str:
    normalized = message.strip()
    if normalized.startswith("session 已"):
        return "SESSION_EXPIRED"
    return "BRAIN_UNAVAILABLE"


def build_exception_protocol_error(exc: Exception) -> dict[str, object]:
    """Map validation-style exceptions into the shared protocol error payload."""
    message = str(exc)
    return build_protocol_error(protocol_error_code_for_exception(message), message)

