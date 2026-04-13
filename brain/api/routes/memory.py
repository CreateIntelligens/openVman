from __future__ import annotations

import asyncio

from fastapi import APIRouter, HTTPException, Request

from memory.embedder import encode_text
from memory.memory import add_memory as store_memory
from memory.memory import delete_memory as remove_memory
from memory.memory import list_memories as query_memories
from memory.memory_governance import maybe_run_memory_maintenance
from protocol.message_envelope import build_message_envelope
from protocol.schemas import AddMemoryRequest, AdminActionRequest
from safety.guardrails import enforce_guardrails
from safety.observability import get_metrics_store, log_event, log_exception
from core.chat_service import record_generation_failure

router = APIRouter(prefix="/brain", tags=["Memory & Sessions"])


@router.get("/memories", summary="列出記憶")
async def list_memories_route(project_id: str = "default", page: int = 1, page_size: int = 20):
    return query_memories(project_id=project_id, page=page, page_size=page_size)


@router.post("/memories", summary="新增記憶")
async def add_memory(request: Request, payload: AddMemoryRequest):
    envelope = build_message_envelope(request, payload.model_dump(), content_key="text")
    text = envelope.content
    if not text:
        raise HTTPException(status_code=400, detail="text 不可為空")

    try:
        enforce_guardrails("add_memory", text, envelope.context)
        store_memory(
            text=text,
            vector=encode_text(text),
            source=payload.source,
            metadata=payload.metadata,
            persona_id=envelope.context.persona_id,
            project_id=envelope.context.project_id,
        )
    except ValueError as exc:
        get_metrics_store().increment("guardrail_blocks_total", action="add_memory")
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    log_event(
        "memory_added",
        trace_id=envelope.context.trace_id,
        source=payload.source,
        project_id=envelope.context.project_id,
    )
    return {"status": "ok", "trace_id": envelope.context.trace_id, "text": text}


@router.delete("/memories", summary="刪除特定記憶")
async def delete_memory(payload: AddMemoryRequest):
    if not payload.text:
        raise HTTPException(status_code=400, detail="text 不可為空")
    try:
        remove_memory(project_id=payload.project_id, text=payload.text)
    except Exception as exc:
        log_exception("delete_memory_error", exc)
        raise HTTPException(status_code=500, detail="刪除記憶失敗") from exc
    log_event("memory_deleted", project_id=payload.project_id)
    return {"status": "ok"}


@router.post("/memories/maintain", summary="執行記憶維護作業")
async def maintain_memory_route(payload: AdminActionRequest):
    try:
        result = await asyncio.to_thread(maybe_run_memory_maintenance, True, payload.project_id)
    except Exception as exc:
        log_exception("memory_maintenance_error", exc)
        record_generation_failure("memory_maintain", "maintenance_failure", str(exc))
        raise HTTPException(status_code=500, detail="記憶整理失敗") from exc
    log_event("memory_maintenance", project_id=payload.project_id, **result)
    return result

