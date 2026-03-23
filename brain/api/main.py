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
from core.slash_command import try_rewrite_slash
from core.sse_events import (
    build_exception_protocol_error,
    build_protocol_error,
    sse_error_to_dict,
    sse_event_to_dict,
)
from health_payload import build_health_payload
from internal_routes import router as internal_router
from infra.db import ensure_tables, get_db
from infra.project_admin import (
    create_project,
    delete_project,
    get_project_info,
    list_projects,
)
from knowledge.indexer import rebuild_knowledge_index
from knowledge.knowledge_admin import (
    create_workspace_directory,
    delete_workspace_directory,
    delete_workspace_document,
    list_knowledge_base_directories,
    list_knowledge_base_documents,
    list_workspace_documents,
    move_workspace_document,
    read_workspace_document,
    save_uploaded_document,
    save_workspace_document,
)

from knowledge.workspace import ensure_workspace_scaffold, parse_identity
from memory.embedder import encode_query_with_fallback, encode_text, get_embedder
from memory.memory import (
    add_memory as store_memory,
    delete_memory as remove_memory,
    delete_session_for_project,
    list_memories as query_memories,
    list_session_messages,
    list_sessions_for_project,
)
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
from protocol.schemas import (
    AddMemoryRequest,
    AdminActionRequest,
    ChatRequest,
    EmbedRequest,
    KnowledgeDocumentMoveRequest,
    KnowledgeDocumentPutRequest,
    PersonaCloneRequest,
    PersonaCreateRequest,
    PersonaDeleteRequest,
    ProjectCreateRequest,
    ProjectDeleteRequest,
    ProtocolValidateRequest,
    SearchRequest,
    SkillCreateRequest,
    SkillFilesUpdateRequest,
)
from safety.guardrails import enforce_guardrails
from safety.observability import get_metrics_store, log_event, log_exception
from tools.skill_manager import get_skill_manager
from tools.tool_registry import get_tool_registry

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("brain")

_OPENAPI_TAGS = [
    {"name": "System", "description": "Health, metrics, and identity endpoints."},
    {"name": "Tools & Skills", "description": "Tool registry and skill management APIs."},
    {"name": "Projects", "description": "Project administration endpoints."},
    {"name": "Personas", "description": "Persona listing and administration endpoints."},
    {"name": "Chat", "description": "Chat generation and history endpoints."},
    {"name": "Search & Embeddings", "description": "Embedding generation and semantic search endpoints."},
    {"name": "Memory & Sessions", "description": "Memory storage, maintenance, and session management endpoints."},
    {"name": "Knowledge", "description": "Knowledge ingestion and knowledge management endpoints."},
    {"name": "Protocol", "description": "Protocol validation endpoints."},
    {"name": "Internal", "description": "Internal service-to-service endpoints."},
]

_TAG_SYSTEM = ["System"]
_TAG_TOOLS = ["Tools & Skills"]
_TAG_PROJECTS = ["Projects"]
_TAG_PERSONAS = ["Personas"]
_TAG_CHAT = ["Chat"]
_TAG_SEARCH = ["Search & Embeddings"]
_TAG_MEMORY = ["Memory & Sessions"]
_TAG_KNOWLEDGE = ["Knowledge"]
_TAG_PROTOCOL = ["Protocol"]


# ---------------------------------------------------------------------------
# Startup & Lifespan
# ---------------------------------------------------------------------------

async def warmup_resources() -> None:
    """背景預熱重資源，避免第一個請求承擔初始化成本。"""
    logger.info("背景預熱開始...")
    ensure_workspace_scaffold("default")
    await asyncio.to_thread(get_embedder)
    await asyncio.to_thread(ensure_tables, "default")
    await asyncio.to_thread(maybe_run_memory_maintenance, True, "default")
    logger.info("背景預熱完成")


async def cancel_task(task: asyncio.Task[None] | None) -> None:
    """在 shutdown 時 safe 取消背景任務。"""
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
    docs_url="/brain/docs",
    redoc_url="/brain/redoc",
    openapi_url="/brain/openapi.json",
    swagger_ui_oauth2_redirect_url="/brain/docs/oauth2-redirect",
    openapi_tags=_OPENAPI_TAGS,
)
app.include_router(internal_router)


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
# Health & Metrics & Identity
# ---------------------------------------------------------------------------

@app.get("/brain/health", tags=_TAG_SYSTEM)
async def health(project_id: str = "default"):
    return build_health_payload(project_id)


@app.get("/brain/metrics", tags=_TAG_SYSTEM)
async def metrics():
    return get_metrics_store().snapshot()


@app.get("/brain/identity", tags=_TAG_SYSTEM)
async def get_identity(persona_id: str = "default", project_id: str = "default"):
    return parse_identity(project_id, persona_id)


# ---------------------------------------------------------------------------
# Tools & Skills
# ---------------------------------------------------------------------------

def _skill_deps() -> tuple:
    """Return (registry, manager) pair used by all skill endpoints."""
    return get_tool_registry(), get_skill_manager()


def _maybe_rewrite_slash(payload: ChatRequest) -> dict:
    """If the message is a slash command, rewrite it; return the raw payload dict."""
    raw = payload.model_dump()
    _, manager = _skill_deps()
    slash = try_rewrite_slash(raw["message"], manager)
    if slash is not None:
        raw["message"] = slash.rewritten
    return raw


@app.get("/brain/tools", tags=_TAG_TOOLS)
async def list_tools():
    """List all registered tools and loaded skill plugins."""
    registry, manager = _skill_deps()

    all_tools = registry.list_tools()
    serialize = lambda t: {"name": t.name, "description": t.description, "parameters": t.parameters}
    builtin_tools = [serialize(t) for t in all_tools if ":" not in t.name]
    skill_tools = [serialize(t) for t in all_tools if ":" in t.name]

    skills = [
        {
            "id": s.manifest.id,
            "name": s.manifest.name,
            "description": s.manifest.description,
            "version": s.manifest.version,
            "enabled": s.enabled,
            "tools": [t.name for t in s.manifest.tools],
            "warnings": s.warnings,
        }
        for s in manager.list_skills()
    ]

    return {"tools": builtin_tools, "skill_tools": skill_tools, "skills": skills}


@app.patch("/brain/skills/{skill_id}/toggle", tags=_TAG_TOOLS)
async def toggle_skill(skill_id: str):
    """Enable or disable a skill."""
    registry, manager = _skill_deps()
    try:
        skill = manager.toggle_skill(skill_id, registry)
        return {"status": "ok", "skill_id": skill_id, "enabled": skill.enabled}
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@app.post("/brain/skills", tags=_TAG_TOOLS)
async def create_skill(payload: SkillCreateRequest):
    """Create a new skill with skeleton files."""
    registry, manager = _skill_deps()
    try:
        skill = manager.create_skill(payload.skill_id, payload.name, payload.description, registry)
        return {
            "status": "ok",
            "skill_id": skill.manifest.id,
            "name": skill.manifest.name,
            "warnings": skill.warnings,
        }
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.get("/brain/skills/{skill_id}/files", tags=_TAG_TOOLS)
async def get_skill_files(skill_id: str):
    """Read raw skill.yaml and main.py contents."""
    _registry, manager = _skill_deps()
    try:
        files = manager.get_skill_files(skill_id)
        return {"skill_id": skill_id, "files": files}
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@app.put("/brain/skills/{skill_id}/files", tags=_TAG_TOOLS)
async def update_skill_files(skill_id: str, payload: SkillFilesUpdateRequest):
    """Update skill files and hot-reload."""
    registry, manager = _skill_deps()
    try:
        skill = manager.update_skill_files(skill_id, payload.files, registry)
        return {
            "status": "ok",
            "skill_id": skill.manifest.id,
            "enabled": skill.enabled,
            "warnings": skill.warnings,
        }
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.delete("/brain/skills/{skill_id}", tags=_TAG_TOOLS)
async def delete_skill(skill_id: str):
    """Delete a skill and its directory."""
    registry, manager = _skill_deps()
    try:
        manager.delete_skill(skill_id, registry)
        return {"status": "ok", "skill_id": skill_id}
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@app.post("/brain/skills/reload", tags=_TAG_TOOLS)
async def reload_all_skills():
    """Reload all skills from disk."""
    registry, manager = _skill_deps()
    skills = manager.reload_all(registry)
    all_warnings = {s.manifest.id: s.warnings for s in skills if s.warnings}
    return {
        "status": "ok",
        "skills_count": len(skills),
        "skills": [s.manifest.id for s in skills],
        "warnings": all_warnings,
    }


# ---------------------------------------------------------------------------
# Projects
# ---------------------------------------------------------------------------

@app.get("/brain/projects", tags=_TAG_PROJECTS)
async def list_projects_route():
    projects = list_projects()
    return {"projects": projects, "project_count": len(projects)}


@app.post("/brain/projects", tags=_TAG_PROJECTS)
async def create_project_route(payload: ProjectCreateRequest):
    try:
        result = create_project(payload.label)
        log_event("project_created", project_id=result["project_id"])
        return result
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.delete("/brain/projects", tags=_TAG_PROJECTS)
async def delete_project_route(payload: ProjectDeleteRequest):
    try:
        result = delete_project(payload.project_id)
        log_event("project_deleted", project_id=payload.project_id)
        return result
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.get("/brain/projects/{project_id}", tags=_TAG_PROJECTS)
async def get_project_route(project_id: str):
    try:
        return get_project_info(project_id)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


# ---------------------------------------------------------------------------
# Personas
# ---------------------------------------------------------------------------

@app.get("/brain/personas", tags=_TAG_PERSONAS)
async def list_personas_route(project_id: str = "default"):
    items = list_personas(project_id)
    return {"personas": items, "persona_count": len(items)}


@app.post("/brain/personas", tags=_TAG_PERSONAS)
async def create_persona_route(payload: PersonaCreateRequest):
    try:
        result = create_persona_scaffold(payload.persona_id, payload.label, payload.project_id)
        log_event("persona_created", persona_id=payload.persona_id, project_id=payload.project_id)
        return result
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.delete("/brain/personas", tags=_TAG_PERSONAS)
async def delete_persona_route(payload: PersonaDeleteRequest):
    try:
        result = delete_persona_scaffold(payload.persona_id, payload.project_id)
        log_event("persona_deleted", persona_id=payload.persona_id, project_id=payload.project_id)
        return result
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.post("/brain/personas/clone", tags=_TAG_PERSONAS)
async def clone_persona_route(payload: PersonaCloneRequest):
    try:
        result = clone_persona_scaffold(payload.source_persona_id, payload.target_persona_id, payload.project_id)
        log_event(
            "persona_cloned",
            source_persona_id=payload.source_persona_id,
            target_persona_id=payload.target_persona_id,
            project_id=payload.project_id,
        )
        return result
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


# ---------------------------------------------------------------------------
# Chat
# ---------------------------------------------------------------------------

@app.post("/brain/chat", tags=_TAG_CHAT)
async def chat(request: Request, payload: ChatRequest):
    """Generate a reply using workspace context, retrieval, and recent session history."""
    try:
        raw = _maybe_rewrite_slash(payload)
        envelope = build_message_envelope(request, raw, content_key="message")
        context = prepare_generation(envelope)
        result = await asyncio.to_thread(execute_generation, context)
        response = finalize_generation(context, result.reply)
        response["tool_steps"] = result.tool_steps
        log_event(
            "chat_complete",
            trace_id=context.trace_id,
            session_id=context.session_id,
            tool_steps=len(result.tool_steps),
            project_id=context.project_id,
        )
        return response
    except (ValueError, ProtocolValidationError) as exc:
        get_metrics_store().increment("guardrail_blocks_total", action="chat")
        record_generation_failure("chat", "validation", str(exc))
        error_payload = build_exception_protocol_error(exc)
        raise HTTPException(status_code=400, detail=error_payload) from exc
    except Exception as exc:  # pragma: no cover
        log_exception("chat_error", exc, trace_id=getattr(request.state, "trace_id", ""))
        record_generation_failure("chat", "llm_failure", str(exc))
        error_payload = build_protocol_error("LLM_OVERLOAD", "LLM 生成失敗", retry_after_ms=3000)
        raise HTTPException(status_code=502, detail=error_payload) from exc


@app.post("/brain/chat/stream", tags=_TAG_CHAT)
async def chat_stream(request: Request, payload: ChatRequest):
    """Stream chat generation through SSE."""
    raw = _maybe_rewrite_slash(payload)
    try:
        envelope = build_message_envelope(request, raw, content_key="message")
        context = prepare_generation(envelope)
    except (ValueError, ProtocolValidationError) as exc:
        get_metrics_store().increment("guardrail_blocks_total", action="chat_stream")
        record_generation_failure("chat_stream", "validation", str(exc))
        error_payload = build_exception_protocol_error(exc)
        raise HTTPException(status_code=400, detail=error_payload) from exc
    except Exception as exc:  # pragma: no cover
        log_exception("chat_stream_init_error", exc, trace_id=getattr(request.state, "trace_id", ""))
        error_payload = build_protocol_error("LLM_OVERLOAD", "LLM 串流初始化失敗")
        raise HTTPException(status_code=502, detail=error_payload) from exc

    return EventSourceResponse(_stream_generation_events(context))


@app.get("/brain/chat/history", tags=_TAG_CHAT)
async def get_chat_history(session_id: str, persona_id: str = "default", project_id: str = "default"):
    try:
        messages = list_session_messages(session_id, persona_id, project_id=project_id)
        return {"session_id": session_id, "persona_id": persona_id, "history": messages}
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


# ---------------------------------------------------------------------------
# Search & Embedding
# ---------------------------------------------------------------------------

@app.post("/brain/embed", tags=_TAG_SEARCH)
async def embed(payload: EmbedRequest):
    """向量化文字"""
    vectors = get_embedder().encode(payload.texts)
    return {
        "count": len(vectors),
        "dim": len(vectors[0]) if vectors else 0,
        "vectors": [v[:5] for v in vectors],
    }


@app.post("/brain/search", tags=_TAG_SEARCH)
async def search(request: Request, payload: SearchRequest):
    """在 LanceDB 中語意搜尋"""
    envelope = build_message_envelope(request, payload.model_dump(), content_key="query")
    query = envelope.content
    project_id = envelope.context.project_id

    if not query:
        raise HTTPException(status_code=400, detail="query 不可為空")

    try:
        enforce_guardrails("search", query, envelope.context)
    except ValueError as exc:
        get_metrics_store().increment("guardrail_blocks_total", action="search")
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    embedding_route = encode_query_with_fallback(
        query,
        project_id=project_id,
        table_names=(payload.table,),
    )
    results = search_records(
        table_name=payload.table,
        query_vector=embedding_route.vector,
        top_k=payload.top_k,
        query_text=query,
        query_type=payload.query_type,
        persona_id=envelope.context.persona_id,
        project_id=project_id,
        embedding_version=embedding_route.version,
    )
    log_event(
        "search_complete",
        trace_id=envelope.context.trace_id,
        table=payload.table,
        embedding_version=embedding_route.version,
        top_k=payload.top_k,
        result_count=len(results),
        project_id=project_id,
    )

    return {
        "trace_id": envelope.context.trace_id,
        "query": query,
        "table": payload.table,
        "embedding_version": embedding_route.version,
        "embedding_attempts": embedding_route.attempted_versions,
        "results": results,
    }


# ---------------------------------------------------------------------------
# Memory & Sessions
# ---------------------------------------------------------------------------

@app.post("/brain/memories", tags=_TAG_MEMORY)
async def add_memory(request: Request, payload: AddMemoryRequest):
    """新增一筆記憶。"""
    envelope = build_message_envelope(request, payload.model_dump(), content_key="text")
    text = envelope.content
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
        source=payload.source,
        metadata=payload.metadata,
        persona_id=envelope.context.persona_id,
        project_id=project_id,
    )
    log_event(
        "memory_added",
        trace_id=envelope.context.trace_id,
        source=payload.source,
        project_id=project_id,
    )

    return {"status": "ok", "trace_id": envelope.context.trace_id, "text": text}


@app.get("/brain/memories", tags=_TAG_MEMORY)
async def list_memories(project_id: str = "default", page: int = 1, page_size: int = 20):
    try:
        return query_memories(project_id=project_id, page=page, page_size=page_size)
    except Exception as exc:
        log_exception("list_memories_error", exc)
        raise HTTPException(status_code=500, detail="無法讀取記憶列表") from exc


@app.delete("/brain/memories", tags=_TAG_MEMORY)
async def delete_memory(payload: AddMemoryRequest):
    if not payload.text:
        raise HTTPException(status_code=400, detail="text 不可為空")
    try:
        remove_memory(project_id=payload.project_id, text=payload.text)
        log_event("memory_deleted", project_id=payload.project_id)
        return {"status": "ok"}
    except Exception as exc:
        log_exception("delete_memory_error", exc)
        raise HTTPException(status_code=500, detail="刪除記憶失敗") from exc


@app.get("/brain/sessions", tags=_TAG_MEMORY)
async def list_sessions(project_id: str = "default", persona_id: str | None = None):
    try:
        sessions = list_sessions_for_project(project_id=project_id, persona_id=persona_id)
        return {"sessions": sessions, "session_count": len(sessions)}
    except Exception as exc:
        log_exception("list_sessions_error", exc)
        raise HTTPException(status_code=500, detail="無法讀取 session 列表") from exc


@app.delete("/brain/sessions/{session_id}", tags=_TAG_MEMORY)
async def delete_session(session_id: str, project_id: str = "default"):
    deleted = delete_session_for_project(project_id=project_id, session_id=session_id)
    if not deleted:
        raise HTTPException(status_code=404, detail="Session 不存在")
    log_event("session_deleted", session_id=session_id, project_id=project_id)
    return {"status": "ok", "session_id": session_id}


# ---------------------------------------------------------------------------
# Knowledge Management
# ---------------------------------------------------------------------------

@app.get("/brain/knowledge/documents", tags=_TAG_KNOWLEDGE)
async def list_knowledge_documents_route(project_id: str = "default"):
    documents = list_workspace_documents(project_id)
    return {"documents": documents, "document_count": len(documents)}


@app.get("/brain/knowledge/base/documents", tags=_TAG_KNOWLEDGE)
async def list_knowledge_base_documents_route(project_id: str = "default"):
    documents = list_knowledge_base_documents(project_id)
    directories = list_knowledge_base_directories(project_id)
    return {"documents": documents, "document_count": len(documents), "directories": directories}


@app.get("/brain/knowledge/document", tags=_TAG_KNOWLEDGE)
async def get_knowledge_document_route(path: str, project_id: str = "default"):
    try:
        return read_workspace_document(path, project_id)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail="找不到指定文件") from exc


@app.put("/brain/knowledge/document", tags=_TAG_KNOWLEDGE)
async def save_knowledge_document_route(payload: KnowledgeDocumentPutRequest):
    try:
        document = save_workspace_document(payload.path, payload.content, payload.project_id)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return {"status": "ok", "document": document}


@app.delete("/brain/knowledge/document", tags=_TAG_KNOWLEDGE)
async def delete_knowledge_document_route(path: str, project_id: str = "default"):
    try:
        delete_workspace_document(path, project_id)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail="找不到指定文件") from exc
    asyncio.create_task(_background_reindex(project_id))
    return {"status": "ok"}


@app.post("/brain/knowledge/move", tags=_TAG_KNOWLEDGE)
async def move_knowledge_document_route(payload: KnowledgeDocumentMoveRequest):
    try:
        document = move_workspace_document(payload.source_path, payload.target_path, payload.project_id)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    asyncio.create_task(_background_reindex(payload.project_id))
    return {"status": "ok", "document": document}


@app.post("/brain/knowledge/directory", tags=_TAG_KNOWLEDGE)
async def create_knowledge_directory_route(payload: KnowledgeDocumentPutRequest):
    try:
        return create_workspace_directory(payload.path, payload.project_id)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.delete("/brain/knowledge/directory", tags=_TAG_KNOWLEDGE)
async def delete_knowledge_directory_route(path: str, project_id: str = "default"):
    try:
        return delete_workspace_directory(path, project_id)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@app.post("/brain/knowledge/upload", tags=_TAG_KNOWLEDGE)
async def upload_knowledge_documents_route(
    files: list[UploadFile] = File(...),
    target_dir: str = Form(""),
    project_id: str = Form("default"),
):
    uploaded: list[dict[str, object]] = []
    try:
        for upload in files:
            uploaded.append(
                save_uploaded_document(upload.filename or "", await upload.read(), target_dir, project_id)
            )
    except UnicodeDecodeError as exc:
        raise HTTPException(status_code=400, detail="檔案需為 UTF-8 編碼") from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    asyncio.create_task(_background_reindex(project_id))
    return {"status": "ok", "files": uploaded}


@app.post("/brain/knowledge/reindex", tags=_TAG_KNOWLEDGE)
async def reindex_knowledge_route(payload: AdminActionRequest):
    try:
        result = await asyncio.to_thread(rebuild_knowledge_index, payload.project_id)
        log_event("knowledge_reindex", project_id=payload.project_id, **result)
        return result
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:  # pragma: no cover
        log_exception("knowledge_reindex_error", exc)
        record_generation_failure("reindex", "index_failure", str(exc))
        raise HTTPException(status_code=500, detail="知識重建失敗") from exc


# ---------------------------------------------------------------------------
# Memory Maintenance
# ---------------------------------------------------------------------------

@app.post("/brain/memories/maintain", tags=_TAG_MEMORY)
async def maintain_memory_route(payload: AdminActionRequest):
    """記憶整理：去重、摘要、歸檔過期 transcripts。"""
    try:
        result = await asyncio.to_thread(maybe_run_memory_maintenance, True, payload.project_id)
        log_event("memory_maintenance", project_id=payload.project_id, **result)
        return result
    except Exception as exc:
        log_exception("memory_maintenance_error", exc)
        record_generation_failure("memory_maintain", "maintenance_failure", str(exc))
        raise HTTPException(status_code=500, detail="記憶整理失敗") from exc


# ---------------------------------------------------------------------------
# Protocol Validation
# ---------------------------------------------------------------------------

@app.post("/brain/protocol/validate", tags=_TAG_PROTOCOL)
async def protocol_validate(payload: ProtocolValidateRequest):
    """Validate a protocol event payload against the versioned contract."""
    try:
        if payload.direction == "client_to_server":
            event = validate_client_event(payload.payload, payload.version)
        else:
            event = validate_server_event(payload.payload, payload.version)
        return {"valid": True, "event": event.event, "version": payload.version}
    except ProtocolValidationError as exc:
        return {
            "valid": False,
            "event": exc.event,
            "version": exc.version,
            "error": str(exc),
            "details": exc.details,
        }


# ---------------------------------------------------------------------------
# Internal Helpers
# ---------------------------------------------------------------------------

async def _background_reindex(project_id: str) -> None:
    """Run reindex in background thread, log errors but don't raise."""
    try:
        result = await asyncio.to_thread(rebuild_knowledge_index, project_id)
        log_event("knowledge_reindex_auto", project_id=project_id, **result)
    except Exception as exc:
        log_exception("knowledge_reindex_auto_error", exc, project_id=project_id)


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
            "chat_stream_complete",
            trace_id=context.trace_id,
            session_id=context.session_id,
            tool_steps=tool_count,
            project_id=context.project_id,
        )
    except asyncio.CancelledError:
        record_generation_failure("chat_stream", "cancelled", context.user_message[:120])
        raise
    except ValueError as exc:
        record_generation_failure("chat_stream", "validation", str(exc))
        yield sse_error_to_dict(build_exception_protocol_error(exc), context.trace_id)
    except Exception as exc:  # pragma: no cover
        log_exception("chat_stream_error", exc, trace_id=context.trace_id)
        record_generation_failure("chat_stream", "llm_failure", str(exc))
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
