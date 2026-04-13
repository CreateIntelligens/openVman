from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException, Request

from memory.embedder import encode_query_with_fallback
from memory.retrieval import search_records
from protocol.message_envelope import build_message_envelope
from protocol.schemas import SearchRequest
from safety.guardrails import enforce_guardrails
from safety.observability import get_metrics_store, log_event

router = APIRouter(prefix="/brain", tags=["Search & Embeddings"])


def _log_search_complete(context: Any, payload: SearchRequest, route: Any, count: int) -> None:
    log_event(
        "search_complete",
        trace_id=context.trace_id,
        table=payload.table,
        embedding_version=route.version,
        top_k=payload.top_k,
        result_count=count,
        project_id=context.project_id,
    )


@router.post("/search", summary="向量語意搜尋")
async def search(request: Request, payload: SearchRequest):
    envelope = build_message_envelope(request, payload.model_dump(), content_key="query")
    query = envelope.content
    if not query:
        raise HTTPException(status_code=400, detail="query 不可為空")

    try:
        enforce_guardrails("search", query, envelope.context)
        embedding_route = encode_query_with_fallback(
            query,
            project_id=envelope.context.project_id,
            table_names=(payload.table,),
        )
        results = search_records(
            table_name=payload.table,
            query_vector=embedding_route.vector,
            top_k=payload.top_k,
            query_text=query,
            query_type=payload.query_type,
            persona_id=envelope.context.persona_id,
            project_id=envelope.context.project_id,
            embedding_version=embedding_route.version,
        )
    except ValueError as exc:
        get_metrics_store().increment("guardrail_blocks_total", action="search")
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    _log_search_complete(envelope.context, payload, embedding_route, len(results))
    return {
        "trace_id": envelope.context.trace_id,
        "query": query,
        "table": payload.table,
        "embedding_version": embedding_route.version,
        "embedding_attempts": embedding_route.attempted_versions,
        "results": results,
    }

