"""SSE event types for streaming generation."""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from time import time
from typing import Any

from protocol.protocol_events import ProtocolValidationError, validate_server_event


@dataclass(frozen=True, slots=True)
class SessionEvent:
    session_id: str
    trace_id: str
    event: str = "session"


@dataclass(frozen=True, slots=True)
class ContextEvent:
    trace_id: str
    knowledge_count: int
    memory_count: int
    request_context: dict[str, Any]
    event: str = "context"


@dataclass(frozen=True, slots=True)
class ToolEvent:
    trace_id: str
    tool_call_id: str
    name: str
    arguments: str
    result: str
    event: str = "tool"


@dataclass(frozen=True, slots=True)
class TokenEvent:
    trace_id: str
    token: str
    event: str = "token"


@dataclass(frozen=True, slots=True)
class PiiWarningEvent:
    trace_id: str
    categories: tuple[str, ...]
    counts: dict[str, int]
    event: str = "pii_warning"


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


SSEEvent = SessionEvent | ContextEvent | ToolEvent | ToolErrorEvent | TokenEvent | PiiWarningEvent | DoneEvent


def _encode_sse_data(payload: dict[str, Any]) -> str:
    return json.dumps(payload, ensure_ascii=False)


def sse_event_to_dict(event: SSEEvent) -> dict[str, str]:
    """Convert an SSE event dataclass to a dict suitable for EventSourceResponse."""
    data = asdict(event)
    event_type = data.pop("event")
    return {
        "event": event_type,
        "id": event.trace_id,
        "data": _encode_sse_data(data),
    }


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


def sse_error_to_dict(error_payload: dict[str, object], trace_id: str) -> dict[str, str]:
    return {
        "event": "error",
        "id": trace_id,
        "data": _encode_sse_data(error_payload),
    }
