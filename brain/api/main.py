"""大腦層 FastAPI 入口"""

import asyncio
import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager, suppress
from time import perf_counter
from uuid import uuid4

from fastapi import FastAPI, File, Form, HTTPException, Request, UploadFile
from sse_starlette.sse import EventSourceResponse

from config import API_INTERNAL_PORT, get_settings
from core.chat_service import (
    GenerationContext,
    execute_generation,
    finalize_generation,
    prepare_generation,
    record_generation_failure,
    stream_generation,
)
from core.sse_events import (
    build_exception_protocol_error,
    build_protocol_error,
    sse_error_to_dict,
    sse_event_to_dict,
)
from infra.db import ensure_tables, get_db
from infra.project_admin import (
    create_project,
    delete_project,
    get_project_info,
    list_projects,
)
from knowledge.indexer import rebuild_knowledge_index
from knowledge.knowledge_admin import (
    list_workspace_documents,
    move_workspace_document,
    read_workspace_document,
    save_uploaded_document,
    save_workspace_document,
)
from knowledge.workspace import ensure_workspace_scaffold
from memory.embedder import encode_text, get_embedder
from memory.memory import add_memory as store_memory, get_or_create_session, list_session_messages
from memory.memory_governance import maybe_run_memory_maintenance
from memory.retrieval import search_records
from personas.personas import (
    clone_persona_scaffold,
    create_persona_scaffold,
    delete_persona_scaffold,
    list_personas,
)
from protocol.message_envelope import build_message_envelope
from protocol.protocol_events import ProtocolValidationError, validate_client_event, validate_server_event
from safety.guardrails import enforce_guardrails
from safety.observability import get_metrics_store, log_event, log_exception

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("brain")


def get_request_text(body: dict[str, object], key: str, default: str = "") -> str:
    """Read a request body field as trimmed text."""
    return str(body.get(key, default)).strip()


def build_health_payload(project_id: str = "default") -> dict[str, object]:
    """組裝 health response。"""
    cfg = get_settings()
    db = get_db(project_id)
    metrics = get_metrics_store().snapshot()
    return {
        "status": "ok",
        "project_id": project_id,
        "tables": db.table_names(),
        "workspace_documents": len(list_workspace_documents(project_id)),
        "personas": len(list_personas(project_id)),
        "chat_enabled": True,
        "embedding_model": cfg.embedding_model,
        "llm_provider": cfg.llm_provider,
        "llm_model": cfg.llm_model,
        "metrics_summary": {
            "counter_count": len(metrics["counters"]),
            "timing_count": len(metrics["timings"]),
        },
    }


async def warmup_resources() -> None:
    """背景預熱重資源，避免第一個請求承擔初始化成本。"""
    logger.info("背景預熱開始...")
    ensure_workspace_scaffold("default")
    await asyncio.to_thread(get_embedder)
    await asyncio.to_thread(ensure_tables, "default")
    await asyncio.to_thread(maybe_run_memory_maintenance, True, "default")
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
    ensure_workspace_scaffold("default")
    get_db("default")

    # Run data migration if needed
    from scripts.migrate_to_projects import run_migration
    await asyncio.to_thread(run_migration)

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
    method = request.method
    path = request.url.path
    store = get_metrics_store()
    start = perf_counter()

    try:
        response = await call_next(request)
    except Exception as exc:
        duration_ms = round((perf_counter() - start) * 1000, 2)
        store.increment("http_requests_total", method=method, path=path, status=500)
        store.observe("http_request_duration_ms", duration_ms, method=method, path=path)
        log_exception(
            "http_request_error", exc,
            trace_id=trace_id, method=method, path=path, duration_ms=duration_ms,
        )
        raise

    duration_ms = round((perf_counter() - start) * 1000, 2)
    response.headers["X-Trace-Id"] = trace_id
    store.increment("http_requests_total", method=method, path=path, status=response.status_code)
    store.observe("http_request_duration_ms", duration_ms, method=method, path=path)
    log_event(
        "http_request",
        trace_id=trace_id, method=method, path=path,
        status=response.status_code, duration_ms=duration_ms,
    )
    return response


# ---------------------------------------------------------------------------
# Health & Metrics
# ---------------------------------------------------------------------------

@app.get("/api/health")
async def health(project_id: str = "default"):
    return build_health_payload(project_id)


@app.get("/api/metrics")
async def metrics():
    return get_metrics_store().snapshot()


# ---------------------------------------------------------------------------
# Project Admin
# ---------------------------------------------------------------------------

@app.get("/api/admin/projects")
async def admin_list_projects():
    projects = list_projects()
    return {"projects": projects, "project_count": len(projects)}


@app.post("/api/admin/projects")
async def admin_create_project(request: Request):
    body = await request.json()
    project_id = get_request_text(body, "project_id")
    label = get_request_text(body, "label")
    try:
        result = create_project(project_id, label)
        log_event("project_created", project_id=project_id)
        return result
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.delete("/api/admin/projects")
async def admin_delete_project(request: Request):
    body = await request.json()
    project_id = get_request_text(body, "project_id")
    try:
        result = delete_project(project_id)
        log_event("project_deleted", project_id=project_id)
        return result
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.get("/api/admin/projects/{project_id}")
async def admin_get_project(project_id: str):
    try:
        return get_project_info(project_id)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


# ---------------------------------------------------------------------------
# Personas
# ---------------------------------------------------------------------------

@app.get("/api/personas")
async def personas(project_id: str = "default"):
    items = list_personas(project_id)
    return {"personas": items, "persona_count": len(items)}


@app.post("/api/admin/personas")
async def create_persona(request: Request):
    body = await request.json()
    persona_id = get_request_text(body, "persona_id")
    label = get_request_text(body, "label")
    project_id = get_request_text(body, "project_id") or "default"
    try:
        result = create_persona_scaffold(persona_id, label, project_id)
        log_event("persona_created", persona_id=persona_id, project_id=project_id)
        return result
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.delete("/api/admin/personas")
async def delete_persona(request: Request):
    body = await request.json()
    persona_id = get_request_text(body, "persona_id")
    project_id = get_request_text(body, "project_id") or "default"
    try:
        result = delete_persona_scaffold(persona_id, project_id)
        log_event("persona_deleted", persona_id=persona_id, project_id=project_id)
        return result
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.post("/api/admin/personas/clone")
async def clone_persona(request: Request):
    body = await request.json()
    source_persona_id = get_request_text(body, "source_persona_id")
    target_persona_id = get_request_text(body, "target_persona_id")
    project_id = get_request_text(body, "project_id") or "default"
    try:
        result = clone_persona_scaffold(source_persona_id, target_persona_id, project_id)
        log_event(
            "persona_cloned",
            source_persona_id=source_persona_id,
            target_persona_id=target_persona_id,
            project_id=project_id,
        )
        return result
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


# ---------------------------------------------------------------------------
# Protocol Validation
# ---------------------------------------------------------------------------

@app.post("/api/protocol/validate")
async def protocol_validate(request: Request):
    """Validate a protocol event payload against the versioned contract."""
    body = await request.json()
    direction = str(body.get("direction", "")).strip()
    payload = body.get("payload")
    version = str(body.get("version", "1.0.0")).strip()

    if not direction or direction not in {"client_to_server", "server_to_client"}:
        raise HTTPException(status_code=400, detail="direction 須為 client_to_server 或 server_to_client")
    if not isinstance(payload, dict):
        raise HTTPException(status_code=400, detail="payload 須為 JSON object")

    try:
        if direction == "client_to_server":
            event = validate_client_event(payload, version)
        else:
            event = validate_server_event(payload, version)
        return {"valid": True, "event": event.event, "version": version}
    except ProtocolValidationError as exc:
        return {
            "valid": False,
            "event": exc.event,
            "version": exc.version,
            "error": str(exc),
            "details": exc.details,
        }


# ---------------------------------------------------------------------------
# Embedding
# ---------------------------------------------------------------------------

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


# ---------------------------------------------------------------------------
# Search & Memory
# ---------------------------------------------------------------------------

@app.post("/api/search")
async def search(request: Request):
    """測試用：在 LanceDB 中語意搜尋"""
    body = await request.json()
    envelope = build_message_envelope(request, body, content_key="query")
    query = envelope.content
    table_name = body.get("table", "memories")
    top_k = body.get("top_k", 5)
    project_id = envelope.context.project_id

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
        project_id=project_id,
    )
    log_event(
        "search_complete",
        trace_id=envelope.context.trace_id,
        table=table_name,
        top_k=top_k,
        result_count=len(results),
        project_id=project_id,
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
    project_id = envelope.context.project_id

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
        project_id=project_id,
    )
    log_event(
        "memory_added",
        trace_id=envelope.context.trace_id,
        source=source,
        project_id=project_id,
    )

    return {
        "status": "ok",
        "trace_id": envelope.context.trace_id,
        "text": text,
    }


# ---------------------------------------------------------------------------
# Chat Generation
# ---------------------------------------------------------------------------

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
            project_id=context.project_id,
        )
        return response
    except ValueError as exc:
        get_metrics_store().increment("guardrail_blocks_total", action="generate")
        record_generation_failure("generate", "validation", str(exc))
        error_payload = build_exception_protocol_error(exc)
        raise HTTPException(status_code=400, detail=error_payload) from exc
    except Exception as exc:  # pragma: no cover - external provider failures
        log_exception(
            "generate_error",
            exc,
            trace_id=getattr(request.state, "trace_id", ""),
        )
        record_generation_failure("generate", "llm_failure", str(exc))
        error_payload = build_protocol_error("LLM_OVERLOAD", "LLM 生成失敗", retry_after_ms=3000)
        raise HTTPException(status_code=502, detail=error_payload) from exc


@app.post("/api/generate/stream")
async def generate_stream(request: Request):
    """Stream chat generation through SSE."""
    envelope = await read_generation_request(request)

    try:
        context = prepare_generation(envelope)
    except ValueError as exc:
        get_metrics_store().increment("guardrail_blocks_total", action="stream_generate")
        record_generation_failure("stream_generate", "validation", str(exc))
        error_payload = build_exception_protocol_error(exc)
        raise HTTPException(status_code=400, detail=error_payload) from exc

    return EventSourceResponse(_stream_generation_events(context))


@app.get("/api/chat/history")
async def get_chat_history(session_id: str, persona_id: str = "default", project_id: str = "default"):
    try:
        session = get_or_create_session(session_id, persona_id, project_id=project_id)
        return {
            "session_id": session.session_id,
            "persona_id": session.persona_id,
            "history": list_session_messages(session.session_id, session.persona_id, project_id=project_id),
        }
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


# ---------------------------------------------------------------------------
# Knowledge Admin
# ---------------------------------------------------------------------------

@app.get("/api/admin/knowledge/documents")
async def list_knowledge_documents(project_id: str = "default"):
    documents = list_workspace_documents(project_id)
    return {
        "documents": documents,
        "document_count": len(documents),
    }


@app.get("/api/admin/knowledge/document")
async def get_knowledge_document(path: str, project_id: str = "default"):
    try:
        return read_workspace_document(path, project_id)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail="找不到指定文件") from exc


@app.put("/api/admin/knowledge/document")
async def put_knowledge_document(request: Request):
    body = await request.json()
    path = get_request_text(body, "path")
    content = str(body.get("content", ""))
    project_id = get_request_text(body, "project_id") or "default"

    try:
        document = save_workspace_document(path, content, project_id)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    return {"status": "ok", "document": document}


@app.post("/api/admin/knowledge/move")
async def post_move_knowledge_document(request: Request):
    body = await request.json()
    source_path = get_request_text(body, "source_path")
    target_path = get_request_text(body, "target_path")
    project_id = get_request_text(body, "project_id") or "default"

    try:
        document = move_workspace_document(source_path, target_path, project_id)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc

    return {"status": "ok", "document": document}


@app.post("/api/admin/knowledge/upload")
async def upload_knowledge_documents(
    files: list[UploadFile] = File(...),
    target_dir: str = Form(""),
    project_id: str = Form("default"),
):
    uploaded: list[dict[str, object]] = []
    try:
        for upload in files:
            uploaded.append(
                save_uploaded_document(
                    upload.filename or "",
                    await upload.read(),
                    target_dir,
                    project_id,
                )
            )
    except UnicodeDecodeError as exc:
        raise HTTPException(status_code=400, detail="檔案需為 UTF-8 編碼") from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    return {"status": "ok", "files": uploaded}


@app.post("/api/admin/knowledge/reindex")
async def reindex_knowledge(request: Request):
    body = await request.json() if request.headers.get("content-type", "").startswith("application/json") else {}
    project_id = get_request_text(body, "project_id") or "default"
    try:
        result = await asyncio.to_thread(rebuild_knowledge_index, project_id)
        log_event("knowledge_reindex", project_id=project_id, **result)
        return result
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:  # pragma: no cover - indexing failures
        log_exception("knowledge_reindex_error", exc)
        record_generation_failure("reindex", "index_failure", str(exc))
        raise HTTPException(status_code=500, detail="知識重建失敗") from exc


@app.post("/api/admin/memory/maintain")
async def maintain_memory(request: Request):
    body = await request.json() if request.headers.get("content-type", "").startswith("application/json") else {}
    project_id = get_request_text(body, "project_id") or "default"
    try:
        result = await asyncio.to_thread(maybe_run_memory_maintenance, True, project_id)
        log_event("memory_maintenance", project_id=project_id, **result)
        return result
    except Exception as exc:  # pragma: no cover - maintenance failures
        log_exception("memory_maintenance_error", exc)
        record_generation_failure("memory_maintain", "maintenance_failure", str(exc))
        raise HTTPException(status_code=500, detail="記憶整理失敗") from exc


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

async def read_generation_request(request: Request):
    body = await request.json()
    return build_message_envelope(request, body, content_key="message")


async def _stream_generation_events(context: GenerationContext) -> AsyncIterator[dict[str, str]]:
    """Yield SSE events from the chat service generator."""
    try:
        tool_count = 0
        async for event in stream_generation(context):
            if event.event == "tool":
                tool_count += 1
                get_metrics_store().increment("tool_calls_total", tool_name=event.name)

            yield sse_event_to_dict(event)

        log_event(
            "stream_generate_complete",
            trace_id=context.trace_id,
            session_id=context.session_id,
            tool_steps=tool_count,
            project_id=context.project_id,
        )
    except asyncio.CancelledError:
        record_generation_failure("stream_generate", "cancelled", context.user_message[:120])
        raise
    except ValueError as exc:
        record_generation_failure("stream_generate", "validation", str(exc))
        yield sse_error_to_dict(
            build_exception_protocol_error(exc),
            context.trace_id,
        )
    except Exception as exc:  # pragma: no cover - external provider failures
        log_exception("stream_generate_error", exc, trace_id=context.trace_id)
        record_generation_failure("stream_generate", "llm_failure", str(exc))
        yield sse_error_to_dict(
            build_protocol_error("LLM_OVERLOAD", "LLM 串流生成失敗", retry_after_ms=3000),
            context.trace_id,
        )


if __name__ == "__main__":
    import uvicorn

    cfg = get_settings()
    uvicorn.run(
        "main:app",
        host="0.0.0.0",
        port=API_INTERNAL_PORT,
        reload=cfg.is_dev,
    )
