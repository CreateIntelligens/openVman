"""大腦層 FastAPI 入口"""

import asyncio
import json
import logging
from contextlib import asynccontextmanager, suppress
from time import perf_counter
from typing import AsyncIterator
from uuid import uuid4

from fastapi import FastAPI, File, Form, HTTPException, Request, Response, UploadFile
from sse_starlette.sse import EventSourceResponse

from agent_loop import stream_agent_reply
from chat_service import (
    GenerationContext,
    execute_generation,
    finalize_generation,
    prepare_generation,
    record_generation_failure,
)
from config import API_INTERNAL_PORT, get_settings
from db import ensure_tables, get_db
from embedder import encode_text, get_embedder
from guardrails import enforce_guardrails
from indexer import rebuild_knowledge_index
from knowledge_admin import (
    list_workspace_documents,
    move_workspace_document,
    read_workspace_document,
    save_uploaded_document,
    save_workspace_document,
)
from message_envelope import build_message_envelope
from memory import add_memory as store_memory, get_or_create_session, list_session_messages
from memory_governance import maybe_run_memory_maintenance
from observability import get_metrics_store, log_event, log_exception
from personas import (
    clone_persona_scaffold,
    create_persona_scaffold,
    delete_persona_scaffold,
    list_personas,
)
from retrieval import search_records
from workspace import ensure_workspace_scaffold

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("brain")


def get_request_text(body: dict[str, object], key: str, default: str = "") -> str:
    """Read a request body field as trimmed text."""
    return str(body.get(key, default)).strip()


def build_health_payload() -> dict[str, object]:
    """組裝 health response。"""
    cfg = get_settings()
    db = get_db()
    metrics = get_metrics_store().snapshot()
    return {
        "status": "ok",
        "tables": db.table_names(),
        "workspace_documents": len(list_workspace_documents()),
        "personas": len(list_personas()),
        "chat_enabled": True,
        "embedding_model": cfg.embedding_model,
        "llm_provider": cfg.brain_llm_provider,
        "llm_model": cfg.brain_llm_model,
        "metrics_summary": {
            "counter_count": len(metrics["counters"]),
            "timing_count": len(metrics["timings"]),
        },
    }


async def warmup_resources() -> None:
    """背景預熱重資源，避免第一個請求承擔初始化成本。"""
    logger.info("背景預熱開始...")
    ensure_workspace_scaffold()
    await asyncio.to_thread(get_embedder)
    await asyncio.to_thread(ensure_tables)
    await asyncio.to_thread(maybe_run_memory_maintenance, True)
    logger.info("背景預熱完成")


async def cancel_task(task: asyncio.Task[None] | None) -> None:
    """在 shutdown 時安全取消背景任務。"""
    if task is None or task.done():
        return

    task.cancel()
    with suppress(asyncio.CancelledError):
        await task


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    """啟動時先讓服務可用，再背景預熱重資源。"""
    logger.info("初始化 LanceDB 連線...")
    ensure_workspace_scaffold()
    get_db()
    app.state.warmup_task = asyncio.create_task(warmup_resources())
    logger.info("大腦層就緒")
    yield
    await cancel_task(getattr(app.state, "warmup_task", None))


app = FastAPI(
    title="openVman Brain",
    version="0.1.0",
    lifespan=lifespan,
    docs_url="/api/docs",
    redoc_url="/api/redoc",
    openapi_url="/api/openapi.json",
)


@app.middleware("http")
async def metrics_middleware(request: Request, call_next):
    trace_id = request.headers.get("x-trace-id", "").strip() or str(uuid4())
    request.state.trace_id = trace_id
    start = perf_counter()

    try:
        response = await call_next(request)
    except Exception as exc:
        duration_ms = round((perf_counter() - start) * 1000, 2)
        get_metrics_store().increment(
            "http_requests_total",
            method=request.method,
            path=request.url.path,
            status=500,
        )
        get_metrics_store().observe(
            "http_request_duration_ms",
            duration_ms,
            method=request.method,
            path=request.url.path,
        )
        log_exception(
            "http_request_error",
            exc,
            trace_id=trace_id,
            method=request.method,
            path=request.url.path,
            duration_ms=duration_ms,
        )
        raise

    duration_ms = round((perf_counter() - start) * 1000, 2)
    response.headers["X-Trace-Id"] = trace_id
    get_metrics_store().increment(
        "http_requests_total",
        method=request.method,
        path=request.url.path,
        status=response.status_code,
    )
    get_metrics_store().observe(
        "http_request_duration_ms",
        duration_ms,
        method=request.method,
        path=request.url.path,
    )
    log_event(
        "http_request",
        trace_id=trace_id,
        method=request.method,
        path=request.url.path,
        status=response.status_code,
        duration_ms=duration_ms,
    )
    return response


@app.get("/api/health")
async def health():
    return build_health_payload()


@app.get("/api/metrics")
async def metrics():
    return get_metrics_store().snapshot()


@app.get("/api/personas")
async def personas():
    items = list_personas()
    return {"personas": items, "persona_count": len(items)}


@app.post("/api/admin/personas")
async def create_persona(request: Request):
    body = await request.json()
    persona_id = get_request_text(body, "persona_id")
    label = get_request_text(body, "label")
    try:
        result = create_persona_scaffold(persona_id, label)
        log_event("persona_created", persona_id=persona_id)
        return result
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.delete("/api/admin/personas")
async def delete_persona(request: Request):
    body = await request.json()
    persona_id = get_request_text(body, "persona_id")
    try:
        result = delete_persona_scaffold(persona_id)
        log_event("persona_deleted", persona_id=persona_id)
        return result
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.post("/api/admin/personas/clone")
async def clone_persona(request: Request):
    body = await request.json()
    source_persona_id = get_request_text(body, "source_persona_id")
    target_persona_id = get_request_text(body, "target_persona_id")
    try:
        result = clone_persona_scaffold(source_persona_id, target_persona_id)
        log_event(
            "persona_cloned",
            source_persona_id=source_persona_id,
            target_persona_id=target_persona_id,
        )
        return result
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.post("/api/embed")
async def embed(request: Request):
    """測試用：向量化文字"""
    body = await request.json()
    texts = body.get("texts", [])
    if not texts:
        raise HTTPException(status_code=400, detail="texts 不可為空")

    vectors = get_embedder().encode(texts)
    return {
        "count": len(vectors),
        "dim": len(vectors[0]) if vectors else 0,
        "vectors": [v[:5] for v in vectors],
    }


@app.post("/api/search")
async def search(request: Request):
    """測試用：在 LanceDB 中語意搜尋"""
    body = await request.json()
    envelope = build_message_envelope(request, body, content_key="query")
    query = envelope.content
    table_name = body.get("table", "memories")
    top_k = body.get("top_k", 5)

    if not query:
        raise HTTPException(status_code=400, detail="query 不可為空")
    if table_name not in {"knowledge", "memories"}:
        raise HTTPException(status_code=400, detail="table 僅支援 knowledge 或 memories")
    try:
        enforce_guardrails("search", query, envelope.context)
    except ValueError as exc:
        get_metrics_store().increment("guardrail_blocks_total", action="search")
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    query_vec = encode_text(query)
    results = search_records(
        table_name=table_name,
        query_vector=query_vec,
        top_k=top_k,
        persona_id=envelope.context.persona_id,
    )
    log_event(
        "search_complete",
        trace_id=envelope.context.trace_id,
        table=table_name,
        top_k=top_k,
        result_count=len(results),
    )

    return {
        "trace_id": envelope.context.trace_id,
        "query": query,
        "table": table_name,
        "results": results,
    }


@app.post("/api/add_memory")
async def add_memory(request: Request):
    """測試用：新增一筆記憶。"""
    body = await request.json()
    envelope = build_message_envelope(request, body, content_key="text")
    text = envelope.content
    source = body.get("source", "user")

    if not text:
        raise HTTPException(status_code=400, detail="text 不可為空")
    try:
        enforce_guardrails("add_memory", text, envelope.context)
    except ValueError as exc:
        get_metrics_store().increment("guardrail_blocks_total", action="add_memory")
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    vector = encode_text(text)
    store_memory(
        text=text,
        vector=vector,
        source=source,
        metadata=body.get("metadata", {}),
        persona_id=envelope.context.persona_id,
    )
    log_event(
        "memory_added",
        trace_id=envelope.context.trace_id,
        source=source,
    )

    return {
        "status": "ok",
        "trace_id": envelope.context.trace_id,
        "text": text,
    }


@app.post("/api/generate")
async def generate(request: Request):
    """Generate a reply using workspace context, retrieval, and recent session history."""
    envelope = await read_generation_request(request)

    try:
        context = prepare_generation(envelope)
        result = await asyncio.to_thread(execute_generation, context)
        response = finalize_generation(context, result.reply)
        response["tool_steps"] = result.tool_steps
        log_event(
            "generate_complete",
            trace_id=context.trace_id,
            session_id=context.session_id,
            tool_steps=len(result.tool_steps),
        )
        return response
    except ValueError as exc:
        get_metrics_store().increment("guardrail_blocks_total", action="generate")
        record_generation_failure("generate", "validation", str(exc))
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:  # pragma: no cover - external provider failures
        log_exception(
            "generate_error",
            exc,
            trace_id=getattr(request.state, "trace_id", ""),
        )
        record_generation_failure("generate", "llm_failure", str(exc))
        raise HTTPException(status_code=502, detail="LLM 生成失敗") from exc


@app.post("/api/generate/stream")
async def generate_stream(request: Request):
    """Stream chat generation through SSE."""
    envelope = await read_generation_request(request)

    try:
        context = prepare_generation(envelope)
    except ValueError as exc:
        get_metrics_store().increment("guardrail_blocks_total", action="stream_generate")
        record_generation_failure("stream_generate", "validation", str(exc))
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    return EventSourceResponse(stream_generation_events(context))


@app.get("/api/chat/history")
async def get_chat_history(session_id: str, persona_id: str = "default"):
    try:
        session = get_or_create_session(session_id, persona_id)
        return {
            "session_id": session.session_id,
            "persona_id": session.persona_id,
            "history": list_session_messages(session.session_id, session.persona_id),
        }
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.get("/api/admin/knowledge/documents")
async def list_knowledge_documents():
    documents = list_workspace_documents()
    return {
        "documents": documents,
        "document_count": len(documents),
    }


@app.get("/api/admin/knowledge/document")
async def get_knowledge_document(path: str):
    try:
        return read_workspace_document(path)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail="找不到指定文件") from exc


@app.put("/api/admin/knowledge/document")
async def put_knowledge_document(request: Request):
    body = await request.json()
    path = get_request_text(body, "path")
    content = str(body.get("content", ""))

    try:
        document = save_workspace_document(path, content)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    return {"status": "ok", "document": document}


@app.post("/api/admin/knowledge/move")
async def post_move_knowledge_document(request: Request):
    body = await request.json()
    source_path = get_request_text(body, "source_path")
    target_path = get_request_text(body, "target_path")

    try:
        document = move_workspace_document(source_path, target_path)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc

    return {"status": "ok", "document": document}


@app.post("/api/admin/knowledge/upload")
async def upload_knowledge_documents(
    files: list[UploadFile] = File(...),
    target_dir: str = Form(""),
):
    uploaded: list[dict[str, object]] = []
    try:
        for upload in files:
            uploaded.append(
                save_uploaded_document(
                    upload.filename or "",
                    await upload.read(),
                    target_dir,
                )
            )
    except UnicodeDecodeError as exc:
        raise HTTPException(status_code=400, detail="檔案需為 UTF-8 編碼") from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    return {"status": "ok", "files": uploaded}


@app.post("/api/admin/knowledge/reindex")
async def reindex_knowledge():
    try:
        result = await asyncio.to_thread(rebuild_knowledge_index)
        log_event("knowledge_reindex", **result)
        return result
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:  # pragma: no cover - indexing failures
        log_exception("knowledge_reindex_error", exc)
        record_generation_failure("reindex", "index_failure", str(exc))
        raise HTTPException(status_code=500, detail="知識重建失敗") from exc


@app.post("/api/admin/memory/maintain")
async def maintain_memory():
    try:
        result = await asyncio.to_thread(maybe_run_memory_maintenance, True)
        log_event("memory_maintenance", **result)
        return result
    except Exception as exc:  # pragma: no cover - maintenance failures
        log_exception("memory_maintenance_error", exc)
        record_generation_failure("memory_maintain", "maintenance_failure", str(exc))
        raise HTTPException(status_code=500, detail="記憶整理失敗") from exc


def _sse_event(event: str, payload: dict[str, object]) -> dict[str, str]:
    return {
        "event": event,
        "data": json.dumps(payload, ensure_ascii=False),
    }


async def read_generation_request(request: Request):
    body = await request.json()
    return build_message_envelope(request, body, content_key="message")


async def stream_generation_events(context: GenerationContext) -> AsyncIterator[dict[str, str]]:
    reply_parts: list[str] = []
    tool_steps: list[dict[str, object]] = []

    try:
        yield _sse_event("session", {"session_id": context.session_id, "trace_id": context.trace_id})
        yield _sse_event(
            "context",
            {
                "trace_id": context.trace_id,
                "knowledge_count": len(context.knowledge_results),
                "memory_count": len(context.memory_results),
                "request_context": context.request_context,
            },
        )
        result = await asyncio.to_thread(execute_generation, context)
        tool_steps = result.tool_steps
        for tool_step in tool_steps:
            get_metrics_store().increment("tool_calls_total", tool_name=str(tool_step.get("name", "")))
            yield _sse_event("tool", tool_step)
        async for token in stream_agent_reply(result.reply):
            reply_parts.append(token)
            yield _sse_event("token", {"token": token})

        payload = finalize_generation(context, "".join(reply_parts))
        payload["tool_steps"] = tool_steps
        log_event(
            "stream_generate_complete",
            trace_id=context.trace_id,
            session_id=context.session_id,
            tool_steps=len(tool_steps),
        )
        yield _sse_event("done", payload)
    except asyncio.CancelledError:
        record_generation_failure("stream_generate", "cancelled", context.user_message[:120])
        raise
    except ValueError as exc:
        record_generation_failure("stream_generate", "validation", str(exc))
        yield _sse_event("error", {"trace_id": context.trace_id, "message": str(exc)})
    except Exception as exc:  # pragma: no cover - external provider failures
        log_exception("stream_generate_error", exc, trace_id=context.trace_id)
        record_generation_failure("stream_generate", "llm_failure", str(exc))
        yield _sse_event("error", {"trace_id": context.trace_id, "message": "LLM 串流生成失敗"})


if __name__ == "__main__":
    import uvicorn

    cfg = get_settings()
    uvicorn.run(
        "main:app",
        host="0.0.0.0",
        port=API_INTERNAL_PORT,
        reload=cfg.is_dev,
    )
