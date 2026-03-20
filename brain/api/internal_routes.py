"""Internal-only routes used by other backend services."""

from __future__ import annotations

import json
from typing import Any

from fastapi import APIRouter, HTTPException

from protocol.schemas import InternalEnrichRequest

router = APIRouter(tags=["Internal"])


def get_or_create_session(
    session_id: str | None = None,
    persona_id: str = "default",
    project_id: str = "default",
):
    from memory.memory import get_or_create_session as _get_or_create_session

    return _get_or_create_session(session_id, persona_id, project_id=project_id)


def append_session_message(
    session_id: str,
    persona_id: str,
    role: str,
    content: str,
    project_id: str = "default",
):
    from memory.memory import append_session_message as _append_session_message

    return _append_session_message(session_id, persona_id, role, content, project_id=project_id)


def log_event(name: str, **kwargs: Any) -> None:
    from safety.observability import log_event as _log_event

    _log_event(name, **kwargs)


def _normalize_enriched_items(payload: InternalEnrichRequest) -> list[dict[str, Any]]:
    items = list(payload.enriched_context)
    if not items and payload.context:
        items.append(payload.context)

    normalized: list[dict[str, Any]] = []
    for item in items:
        content = str(item.get("content", "")).strip()
        if not content:
            continue

        item_type = str(item.get("type", "context")).strip() or "context"
        extras = {
            key: value
            for key, value in item.items()
            if key not in {"type", "content"} and value not in (None, "", [], {})
        }
        normalized.append(
            {
                "type": item_type,
                "content": content,
                "extras": extras,
            }
        )
    return normalized


def _format_enriched_message(item: dict[str, Any], media_refs: list[dict[str, Any]]) -> str:
    lines = [
        f"[enriched_context:{item['type']}]",
        item["content"],
    ]

    if item["extras"]:
        lines.append(
            f"extras: {json.dumps(item['extras'], ensure_ascii=False, sort_keys=True)}"
        )

    media_paths = [str(ref.get("path", "")).strip() for ref in media_refs if str(ref.get("path", "")).strip()]
    if media_paths:
        lines.append(f"media_refs: {', '.join(media_paths)}")

    return "\n".join(lines)


@router.post("/internal/enrich")
async def internal_enrich(payload: InternalEnrichRequest):
    items = _normalize_enriched_items(payload)
    if not items:
        raise HTTPException(status_code=400, detail="enriched_context 不可為空")

    session = get_or_create_session(
        payload.session_id,
        payload.persona_id,
        project_id=payload.project_id,
    )

    for item in items:
        append_session_message(
            session.session_id,
            payload.persona_id,
            "system",
            _format_enriched_message(item, payload.media_refs),
            project_id=payload.project_id,
        )

    log_event(
        "internal_enrich",
        trace_id=payload.trace_id,
        session_id=session.session_id,
        project_id=payload.project_id,
        persona_id=payload.persona_id,
        stored_count=len(items),
    )
    return {
        "status": "ok",
        "trace_id": payload.trace_id,
        "session_id": session.session_id,
        "stored_count": len(items),
    }
