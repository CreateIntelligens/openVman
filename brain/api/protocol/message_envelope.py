"""Normalized request envelope shared across endpoints."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any
from uuid import uuid4

from fastapi import Request


@dataclass(slots=True)
class RequestContext:
    trace_id: str
    session_id: str | None
    message_type: str
    channel: str
    locale: str
    persona_id: str
    client_ip: str
    metadata: dict[str, Any]


ALLOWED_ROLES = frozenset({"system", "user", "assistant", "tool", "control"})


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
    content = _read_text(message_payload, "content", fallback=raw_message)
    session_id = _read_text(body, "session_id") or _read_text(message_payload, "session_id") or None
    context = RequestContext(
        trace_id=_resolve_trace_id(request, body, message_payload),
        session_id=session_id,
        message_type=_read_text(body, "message_type")
        or _read_text(message_payload, "message_type")
        or default_message_type,
        channel=_read_text(body, "channel")
        or _read_text(message_payload, "channel")
        or _read_text(dict(request.headers), "x-brain-channel")
        or "web",
        locale=_read_text(body, "locale")
        or _read_text(message_payload, "locale")
        or _read_text(dict(request.headers), "accept-language")
        or "zh-TW",
        persona_id=_read_text(body, "persona_id")
        or _read_text(message_payload, "persona_id")
        or "default",
        client_ip=request.client.host if request.client else "",
        metadata=_merge_metadata(body.get("metadata"), message_payload.get("metadata")),
    )
    return MessageEnvelope(content=content, context=context)


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
        or _read_text(body, "trace_id")
        or _read_text(message_payload, "trace_id")
        or request.headers.get("x-trace-id", "").strip()
        or str(uuid4())
    )


def _merge_metadata(*values: object) -> dict[str, Any]:
    merged: dict[str, Any] = {}
    for value in values:
        if isinstance(value, dict):
            merged.update(value)
    return merged


def _read_text(payload: dict[str, Any], key: str, fallback: object = "") -> str:
    if key in payload:
        return str(payload[key]).strip()
    return str(fallback).strip()
