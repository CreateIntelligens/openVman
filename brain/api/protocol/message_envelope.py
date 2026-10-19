"""Normalized request envelope shared across endpoints."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any
from uuid import uuid4

from fastapi import Request

from safety.internal_auth import (
    PRINCIPAL_ID_HEADER,
    PRINCIPAL_TYPE_HEADER,
    USER_ID_HEADER,
)


@dataclass(slots=True)
class RequestContext:
    trace_id: str
    session_id: str | None
    message_type: str
    channel: str
    locale: str
    persona_id: str
    project_id: str
    client_ip: str
    metadata: dict[str, Any]
    # Backend 驗過身分後帶來的呼叫者（api_key:<id>、embed_key:<id>、user:<id>）。
    # Brain 只收 Backend 的請求，client_ip 永遠是 Backend，限流要靠這個分人。
    principal: str = ""


ALLOWED_ROLES = frozenset({"system", "user", "assistant", "tool", "control"})

METADATA_ORIGINAL_USER_MESSAGE = "original_user_message"
METADATA_ACTION_REQUESTS = "action_requests"


@dataclass(slots=True)
class MessageEnvelope:
    content: str
    context: RequestContext


@dataclass(slots=True)
class BrainMessage:
    """Normalized internal message passed through all brain pipeline stages."""

    role: str
    content: str
    trace_id: str
    session_id: str | None
    persona_id: str
    project_id: str
    locale: str
    channel: str
    metadata: dict[str, Any]


def build_message_envelope(
    request: Request,
    body: dict[str, Any],
    *,
    content_key: str = "message",
    default_message_type: str = "user",
) -> MessageEnvelope:
    """Normalize legacy and structured request payloads into one envelope."""
    raw_message = body.get(content_key, "")
    message_payload = raw_message if isinstance(raw_message, dict) else {}
    content = read_text(message_payload, "content", fallback=raw_message)
    session_id = read_text(body, "session_id") or read_text(message_payload, "session_id") or None
    context = RequestContext(
        trace_id=_resolve_trace_id(request, body, message_payload),
        session_id=session_id,
        message_type=read_text(body, "message_type")
        or read_text(message_payload, "message_type")
        or default_message_type,
        channel=read_text(body, "channel")
        or read_text(message_payload, "channel")
        or read_text(dict(request.headers), "x-brain-channel")
        or "web",
        locale=read_text(body, "locale")
        or read_text(message_payload, "locale")
        or read_text(dict(request.headers), "accept-language")
        or "zh-TW",
        persona_id=read_text(body, "persona_id")
        or read_text(message_payload, "persona_id")
        or "default",
        project_id=read_text(body, "project_id")
        or read_text(message_payload, "project_id")
        or read_text(dict(request.headers), "x-brain-project")
        or "default",
        client_ip=request.client.host if request.client else "",
        metadata=merge_metadata(body.get("metadata"), message_payload.get("metadata")),
        principal=_principal(request),
    )
    return MessageEnvelope(content=content, context=context)


def _principal(request: Any) -> str:
    """Caller identity Backend forwarded, with the same fallbacks as trusted_request_context."""
    headers = dict(getattr(request, "headers", None) or {})
    principal_id = (
        read_text(headers, PRINCIPAL_ID_HEADER.lower())
        or read_text(headers, USER_ID_HEADER.lower())
    )
    if not principal_id:
        return ""
    principal_type = read_text(headers, PRINCIPAL_TYPE_HEADER.lower()) or "user"
    return f"{principal_type}:{principal_id}"


def serialize_context(context: RequestContext) -> dict[str, Any]:
    return asdict(context)


def normalize_to_brain_message(envelope: MessageEnvelope) -> BrainMessage:
    """Convert a MessageEnvelope into a BrainMessage for pipeline consumption."""
    ctx = envelope.context
    return BrainMessage(
        role=ctx.message_type,
        content=envelope.content,
        trace_id=ctx.trace_id,
        session_id=ctx.session_id,
        persona_id=ctx.persona_id,
        project_id=ctx.project_id,
        locale=ctx.locale,
        channel=ctx.channel,
        metadata=dict(ctx.metadata),
    )


def create_brain_message(
    role: str,
    content: str,
    *,
    context: RequestContext,
) -> BrainMessage:
    """Create a BrainMessage for internal stages (system prompt, assistant reply, etc.)."""
    return BrainMessage(
        role=role,
        content=content,
        trace_id=context.trace_id,
        session_id=context.session_id,
        persona_id=context.persona_id,
        project_id=context.project_id,
        locale=context.locale,
        channel=context.channel,
        metadata=dict(context.metadata),
    )


def _resolve_trace_id(
    request: Request,
    body: dict[str, Any],
    message_payload: dict[str, Any],
) -> str:
    state_trace_id = getattr(request.state, "trace_id", "")
    return (
        state_trace_id
        or read_text(body, "trace_id")
        or read_text(message_payload, "trace_id")
        or request.headers.get("x-trace-id", "").strip()
        or str(uuid4())
    )


def merge_metadata(*values: object) -> dict[str, Any]:
    merged: dict[str, Any] = {}
    for value in values:
        if isinstance(value, dict):
            merged.update(value)
    return merged


def read_text(payload: dict[str, Any], key: str, fallback: object = "") -> str:
    value = payload.get(key, fallback)
    if value is None:
        return ""
    return str(value).strip()
