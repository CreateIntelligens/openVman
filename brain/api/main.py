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
    save_workspace_note,
    save_workspace_document,
    update_workspace_document_meta,
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
    KnowledgeDocumentMetaPatchRequest,
    KnowledgeNoteCreateRequest,
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
    {"name": "Knowledge", "description": "Knowledge document management and indexing endpoints."},
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

@app.get(
    "/brain/health",
    tags=_TAG_SYSTEM,
    summary="大腦層健康檢查",
    description="檢查大腦層的服務狀態與相依性連接情形。\n\n**所需欄位**：\n- `project_id` (Query, str, 預設 'default'): 專案 ID",
)
async def health(project_id: str = "default"):
    return build_health_payload(project_id)


@app.get(
    "/brain/metrics",
    tags=_TAG_SYSTEM,
    summary="大腦層監控指標",
    description="取得 Prometheus 格式的大腦層監控與效能指標列表。",
)
async def metrics():
    return get_metrics_store().snapshot()


@app.get(
    "/brain/identity",
    tags=_TAG_SYSTEM,
    summary="解析前端身份",
    description="根據傳入的專案與人設 ID 回傳詳細配置設定。\n\n**所需欄位**：\n- `persona_id` (Query, str, 預設 'default'): 人設 ID\n- `project_id` (Query, str, 預設 'default'): 專案 ID",
)
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


@app.get(
    "/brain/tools",
    tags=_TAG_TOOLS,
    summary="列出工具與技能",
    description="取得目前所有已註冊的 Tools 以及被載入的 Skills 清單。",
)
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


@app.patch(
    "/brain/skills/{skill_id}/toggle",
    tags=_TAG_TOOLS,
    summary="切換技能啟用狀態",
    description="啟用或停用指定的技能。\n\n**所需欄位**：\n- `skill_id` (Path, str): 技能 ID",
)
async def toggle_skill(skill_id: str):
    """Enable or disable a skill."""
    registry, manager = _skill_deps()
    try:
        skill = manager.toggle_skill(skill_id, registry)
        return {"status": "ok", "skill_id": skill_id, "enabled": skill.enabled}
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@app.post(
    "/brain/skills",
    tags=_TAG_TOOLS,
    summary="建立新技能",
    description="建立並初始化一個新的技能檔案結構。\n\n**所需欄位 (JSON)**：\n- `skill_id` (Body, str): 技能的唯一識別碼\n- `name` (Body, str): 技能名稱\n- `description` (Body, str): 技能的詳細說明",
)
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


@app.get(
    "/brain/skills/{skill_id}/files",
    tags=_TAG_TOOLS,
    summary="取得技能檔案",
    description="讀取指定技能的原始檔內容 (skill.yaml, main.py 等)。\n\n**所需欄位**：\n- `skill_id` (Path, str): 技能 ID",
)
async def get_skill_files(skill_id: str):
    """Read raw skill.yaml and main.py contents."""
    _registry, manager = _skill_deps()
    try:
        files = manager.get_skill_files(skill_id)
        return {"skill_id": skill_id, "files": files}
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@app.put(
    "/brain/skills/{skill_id}/files",
    tags=_TAG_TOOLS,
    summary="更新技能檔案",
    description="更新指定技能的檔案內容並且熱重載。\n\n**所需欄位 (JSON)**：\n- `skill_id` (Path, str): 技能 ID\n- `files` (Body, list[dict]): 檔案變更列表 (含 path 及 content)",
)
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


@app.delete(
    "/brain/skills/{skill_id}",
    tags=_TAG_TOOLS,
    summary="刪除技能",
    description="刪除技能及其目錄內容。\n\n**所需欄位**：\n- `skill_id` (Path, str): 技能 ID",
)
async def delete_skill(skill_id: str):
    """Delete a skill and its directory."""
    registry, manager = _skill_deps()
    try:
        manager.delete_skill(skill_id, registry)
        return {"status": "ok", "skill_id": skill_id}
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@app.post(
    "/brain/skills/reload",
    tags=_TAG_TOOLS,
    summary="重新載入所有技能",
    description="重新從磁碟讀取並載入所有技能狀態。",
)
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

@app.get(
    "/brain/projects",
    tags=_TAG_PROJECTS,
    summary="列出所有專案",
    description="取得大腦層配置的所有已知專案列表。",
)
async def list_projects_route():
    projects = list_projects()
    return {"projects": projects, "project_count": len(projects)}


@app.post(
    "/brain/projects",
    tags=_TAG_PROJECTS,
    summary="建立新專案",
    description="建立一個全新的專案獨立空間。\n\n**所需欄位 (JSON)**：\n- `label` (Body, str): 專案顯示名稱",
)
async def create_project_route(payload: ProjectCreateRequest):
    try:
        result = create_project(payload.label)
        log_event("project_created", project_id=result["project_id"])
        return result
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.delete(
    "/brain/projects",
    tags=_TAG_PROJECTS,
    summary="刪除專案",
    description="刪除指定的專案及其相關資料。\n\n**所需欄位 (JSON)**：\n- `project_id` (Body, str): 要刪除的專案 ID",
)
async def delete_project_route(payload: ProjectDeleteRequest):
    try:
        result = delete_project(payload.project_id)
        log_event("project_deleted", project_id=payload.project_id)
        return result
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.get(
    "/brain/projects/{project_id}",
    tags=_TAG_PROJECTS,
    summary="取得單一專案資訊",
    description="取得特定專案的詳細資訊。\n\n**所需欄位**：\n- `project_id` (Path, str): 專案 ID",
)
async def get_project_route(project_id: str):
    try:
        return get_project_info(project_id)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


# ---------------------------------------------------------------------------
# Personas
# ---------------------------------------------------------------------------

@app.get(
    "/brain/personas",
    tags=_TAG_PERSONAS,
    summary="列出人設清單",
    description="取得現有的 AI 人設 (Persona) 清單。\n\n**所需欄位**：\n- `project_id` (Query, str, 預設 'default'): 專案 ID",
)
async def list_personas_route(project_id: str = "default"):
    items = list_personas(project_id)
    return {"personas": items, "persona_count": len(items)}


@app.post(
    "/brain/personas",
    tags=_TAG_PERSONAS,
    summary="建立新人設",
    description="建立並初始化一個新的 Persona 結構與設定。\n\n**所需欄位 (JSON)**：\n- `persona_id` (Body, str): 新人設的 ID\n- `label` (Body, str): 顯示名稱\n- `project_id` (Body, str, 預設 'default'): 專案 ID",
)
async def create_persona_route(payload: PersonaCreateRequest):
    try:
        result = create_persona_scaffold(payload.persona_id, payload.label, payload.project_id)
        log_event("persona_created", persona_id=payload.persona_id, project_id=payload.project_id)
        return result
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.delete(
    "/brain/personas",
    tags=_TAG_PERSONAS,
    summary="刪除人設",
    description="刪除指定的人設。\n\n**所需欄位 (JSON)**：\n- `persona_id` (Body, str): 要刪除的人設 ID\n- `project_id` (Body, str, 預設 'default'): 專案 ID",
)
async def delete_persona_route(payload: PersonaDeleteRequest):
    try:
        result = delete_persona_scaffold(payload.persona_id, payload.project_id)
        log_event("persona_deleted", persona_id=payload.persona_id, project_id=payload.project_id)
        return result
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.post(
    "/brain/personas/clone",
    tags=_TAG_PERSONAS,
    summary="複製人設",
    description="複製一個現有的人設為新的人設。\n\n**所需欄位 (JSON)**：\n- `source_persona_id` (Body, str): 來源人設 ID\n- `target_persona_id` (Body, str): 新的人設 ID\n- `project_id` (Body, str, 預設 'default'): 專案 ID",
)
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

@app.post(
    "/brain/chat",
    tags=_TAG_CHAT,
    summary="非串流對話",
    description="進行一回合完整的對話生成（同步等待直到產生完整回應）。\n\n**所需欄位 (JSON)**：\n- 見 `ChatRequest` 結構 (包含 message, session_id 等等)",
)
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


@app.post(
    "/brain/chat/stream",
    tags=_TAG_CHAT,
    summary="串流對話 (SSE)",
    description="透過 Server-Sent Events (SSE) 串流回傳對話生成過程與結果。\n\n**所需欄位 (JSON)**：\n- 見 `ChatRequest` 結構",
)
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


@app.get(
    "/brain/chat/history",
    tags=_TAG_CHAT,
    summary="取得聊天紀錄",
    description="取得指定 session 的歷史聊天紀錄。\n\n**所需欄位**：\n- `session_id` (Query, str): 聊天對話的 Session ID\n- `persona_id` (Query, str, 預設 'default'): 人設 ID\n- `project_id` (Query, str, 預設 'default'): 專案 ID",
)
async def get_chat_history(session_id: str, persona_id: str = "default", project_id: str = "default"):
    try:
        messages = list_session_messages(session_id, persona_id, project_id=project_id)
        return {"session_id": session_id, "persona_id": persona_id, "history": messages}
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


# ---------------------------------------------------------------------------
# Search & Embedding
# ---------------------------------------------------------------------------

@app.post(
    "/brain/embed",
    tags=_TAG_SEARCH,
    summary="文字向量化",
    description="將傳入的多筆文字進行 Embedding 轉換並回傳。\n\n**所需欄位 (JSON)**：\n- `texts` (Body, list[str]): 需要被向量化的字串陣列",
)
async def embed(payload: EmbedRequest):
    """向量化文字"""
    vectors = get_embedder().encode(payload.texts)
    return {
        "count": len(vectors),
        "dim": len(vectors[0]) if vectors else 0,
        "vectors": [v[:5] for v in vectors],
    }


@app.post(
    "/brain/search",
    tags=_TAG_SEARCH,
    summary="向量語意搜尋",
    description="使用 Embedding 對 LanceDB 內的資料進行相近度查詢。\n\n**所需欄位 (JSON)**：\n- `query` (Body, str): 查詢字串\n- `table` (Body, str): 要查詢的資料表名稱\n- `top_k` (Body, int, 預設 5): 回傳筆數限制\n- `query_type` (Body, str, 預設 'hybrid'): 搜尋模式 (vector/fts/hybrid)\n- `session_id`, `persona_id`, `project_id` (Body, str): 其他環境參數",
)
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

@app.post(
    "/brain/memories",
    tags=_TAG_MEMORY,
    summary="新增記憶",
    description="新增一筆短期或長期記憶到目前專案與人設中。\n\n**所需欄位 (JSON)**：\n- `text` (Body, str): 記憶內容\n- `source` (Body, str, 選填): 記憶來源 (例如 chat/tool 等)\n- `metadata` (Body, dict, 選填): 額外的結構化資料\n- `project_id` (Body, str, 預設 'default'): 專案 ID",
)
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


@app.get(
    "/brain/memories",
    tags=_TAG_MEMORY,
    summary="列出記憶清單",
    description="分頁取得目前專案中的記憶清單。\n\n**所需欄位**：\n- `project_id` (Query, str, 預設 'default'): 專案 ID\n- `page` (Query, int, 預設 1): 頁碼\n- `page_size` (Query, int, 預設 20): 每頁筆數",
)
async def list_memories(project_id: str = "default", page: int = 1, page_size: int = 20):
    try:
        return query_memories(project_id=project_id, page=page, page_size=page_size)
    except Exception as exc:
        log_exception("list_memories_error", exc)
        raise HTTPException(status_code=500, detail="無法讀取記憶列表") from exc


@app.delete(
    "/brain/memories",
    tags=_TAG_MEMORY,
    summary="刪除特定記憶",
    description="根據精確的文字內容刪除對應的一筆記憶。\n\n**所需欄位 (JSON)**：\n- `text` (Body, str): 要刪除的記憶內容\n- `project_id` (Body, str, 預設 'default'): 專案 ID",
)
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


@app.get(
    "/brain/sessions",
    tags=_TAG_MEMORY,
    summary="列出對話 Session",
    description="取得指定專案或人設下的所有對話 Session 列表。\n\n**所需欄位**：\n- `project_id` (Query, str, 預設 'default'): 專案 ID\n- `persona_id` (Query, str, 選填): 篩選特定的人設 ID",
)
async def list_sessions(project_id: str = "default", persona_id: str | None = None):
    try:
        sessions = list_sessions_for_project(project_id=project_id, persona_id=persona_id)
        return {"sessions": sessions, "session_count": len(sessions)}
    except Exception as exc:
        log_exception("list_sessions_error", exc)
        raise HTTPException(status_code=500, detail="無法讀取 session 列表") from exc


@app.delete(
    "/brain/sessions/{session_id}",
    tags=_TAG_MEMORY,
    summary="刪除對話 Session",
    description="刪除特定的對話內容。\n\n**所需欄位**：\n- `session_id` (Path, str): 欲刪除的 Session ID\n- `project_id` (Query, str, 預設 'default'): 專案 ID",
)
async def delete_session(session_id: str, project_id: str = "default"):
    deleted = delete_session_for_project(project_id=project_id, session_id=session_id)
    if not deleted:
        raise HTTPException(status_code=404, detail="Session 不存在")
    log_event("session_deleted", session_id=session_id, project_id=project_id)
    return {"status": "ok", "session_id": session_id}


# ---------------------------------------------------------------------------
# Knowledge Management
# ---------------------------------------------------------------------------

@app.get(
    "/brain/knowledge/documents",
    tags=_TAG_KNOWLEDGE,
    summary="取得工作區所有文件",
    description="取得當前專案工作區 `workspace/` 底下的所有檔案路徑列表。\n\n**所需欄位**：\n- `project_id` (Query, str, 預設 'default'): 專案 ID",
)
async def list_knowledge_documents_route(project_id: str = "default"):
    documents = list_workspace_documents(project_id)
    return {"documents": documents, "document_count": len(documents)}


@app.get(
    "/brain/knowledge/base/documents",
    tags=_TAG_KNOWLEDGE,
    summary="取得知識庫樹狀結構",
    description="取得專案知識庫目錄中的所有文件與資料夾層級結構 (主要包含 knowledge 資料夾)。\n\n**所需欄位**：\n- `project_id` (Query, str, 預設 'default'): 專案 ID",
)
async def list_knowledge_base_documents_route(project_id: str = "default"):
    documents = list_knowledge_base_documents(project_id)
    directories = list_knowledge_base_directories(project_id)
    return {"documents": documents, "document_count": len(documents), "directories": directories}


@app.get(
    "/brain/knowledge/document",
    tags=_TAG_KNOWLEDGE,
    summary="讀取單一知識文件",
    description="讀取特定路徑的知識文件詳細內容與中繼屬性。\n\n**所需欄位**：\n- `path` (Query, str): 文件相對路徑\n- `project_id` (Query, str, 預設 'default'): 專案 ID",
)
async def get_knowledge_document_route(path: str, project_id: str = "default"):
    try:
        return read_workspace_document(path, project_id)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail="找不到指定文件") from exc


@app.put(
    "/brain/knowledge/document",
    tags=_TAG_KNOWLEDGE,
    summary="儲存知識文件",
    description="寫入或覆蓋特定路徑的知識文件內容。\n\n**所需欄位 (JSON)**：\n- `path` (Body, str): 欲儲存的檔案路徑\n- `content` (Body, str): Markdown 或純文字內容\n- `project_id` (Body, str, 預設 'default'): 專案 ID",
)
async def save_knowledge_document_route(payload: KnowledgeDocumentPutRequest):
    try:
        document = save_workspace_document(payload.path, payload.content, payload.project_id)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    asyncio.create_task(_background_reindex(payload.project_id))
    return {"status": "ok", "document": document}


@app.patch(
    "/brain/knowledge/document/meta",
    tags=_TAG_KNOWLEDGE,
    summary="更新文件中繼屬性 (Metadata)",
    description="變更知識文件的屬性（例如是否啟用索引、來源網址等）。\n\n**所需欄位 (JSON)**：\n- `path` (Body, str): 文件路徑\n- `enabled` (Body, bool, 選填): 是否納入索引\n- `source_type` (Body, str, 選填): 原始來源類型\n- `source_url` (Body, str, 選填): 原始來源URL\n- `project_id` (Body, str, 預設 'default'): 專案 ID",
)
async def patch_knowledge_document_meta_route(payload: KnowledgeDocumentMetaPatchRequest):
    try:
        document = update_workspace_document_meta(
            payload.path,
            payload.project_id,
            enabled=payload.enabled,
            source_type=payload.source_type,
            source_url=payload.source_url,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return {
        "status": "ok",
        "path": document["path"],
        "enabled": document["enabled"],
        "source_type": document["source_type"],
        "source_url": document["source_url"],
    }


@app.delete(
    "/brain/knowledge/document",
    tags=_TAG_KNOWLEDGE,
    summary="刪除知識文件",
    description="刪除指定路徑的知識文件檔案並觸發背景重整索引。\n\n**所需欄位**：\n- `path` (Query, str): 欲刪除的文件路徑\n- `project_id` (Query, str, 預設 'default'): 專案 ID",
)
async def delete_knowledge_document_route(path: str, project_id: str = "default"):
    try:
        delete_workspace_document(path, project_id)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail="找不到指定文件") from exc
    asyncio.create_task(_background_reindex(project_id))
    return {"status": "ok"}


@app.post(
    "/brain/knowledge/move",
    tags=_TAG_KNOWLEDGE,
    summary="移動/重新命名知識文件",
    description="將知識庫內的特定文件移動至新路徑，並觸發重整索引。\n\n**所需欄位 (JSON)**：\n- `source_path` (Body, str): 原始檔案路徑\n- `target_path` (Body, str): 目的目錄或檔案路徑\n- `project_id` (Body, str, 預設 'default'): 專案 ID",
)
async def move_knowledge_document_route(payload: KnowledgeDocumentMoveRequest):
    try:
        document = move_workspace_document(payload.source_path, payload.target_path, payload.project_id)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    asyncio.create_task(_background_reindex(payload.project_id))
    return {"status": "ok", "document": document}


@app.post(
    "/brain/knowledge/directory",
    tags=_TAG_KNOWLEDGE,
    summary="建立資料夾",
    description="在知識庫內建立一個新的空資料夾。\n\n**所需欄位 (JSON)**：\n- `path` (Body, str): 欲建立的資料夾路徑\n- `project_id` (Body, str, 預設 'default'): 專案 ID",
)
async def create_knowledge_directory_route(payload: KnowledgeDocumentPutRequest):
    try:
        return create_workspace_directory(payload.path, payload.project_id)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.delete(
    "/brain/knowledge/directory",
    tags=_TAG_KNOWLEDGE,
    summary="刪除資料夾",
    description="刪除特定空資料夾 (若內有檔案會報錯退回)。\n\n**所需欄位**：\n- `path` (Query, str): 欲刪除的資料夾路徑\n- `project_id` (Query, str, 預設 'default'): 專案 ID",
)
async def delete_knowledge_directory_route(path: str, project_id: str = "default"):
    try:
        return delete_workspace_directory(path, project_id)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@app.post(
    "/brain/knowledge/upload",
    tags=_TAG_KNOWLEDGE,
    summary="上傳實體檔案至知識庫",
    description="將單個或多個檔案上傳儲存到指定知識庫目錄底下，支援背景重整索引。\n\n**所需欄位 (Form)**：\n- `files` (Form, list[UploadFile]): 要上傳的檔案\n- `target_dir` (Form, str, 預設 ''): 上傳的目標資料夾\n- `project_id` (Form, str, 預設 'default'): 專案 ID",
)
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


@app.post("/brain/knowledge/note", tags=_TAG_KNOWLEDGE)
async def create_knowledge_note_route(payload: KnowledgeNoteCreateRequest):
    try:
        document = save_workspace_note(payload.title, payload.content, payload.project_id)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    asyncio.create_task(_background_reindex(payload.project_id))
    return {"status": "ok", "document": document, "path": document["path"], "size": document["size"]}


@app.post(
    "/brain/knowledge/reindex",
    tags=_TAG_KNOWLEDGE,
    summary="重整全域知識索引",
    description="手動強制觸發指定專案底下知識庫向量索引的全面重建作業。\n\n**所需欄位 (JSON)**：\n- `project_id` (Body, str): 專案 ID",
)
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

@app.post(
    "/brain/memories/maintain",
    tags=_TAG_MEMORY,
    summary="執行記憶維護作業",
    description="記憶整理：自動執行去重、摘要、歸檔過期對話等維護工作。\n\n**所需欄位 (JSON)**：\n- `project_id` (Body, str): 專案 ID",
)
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

@app.post(
    "/brain/protocol/validate",
    tags=_TAG_PROTOCOL,
    summary="驗證傳輸協定格式",
    description="將給定的 Payload 使用系統指定的 Schema 進行合法性格式驗證。\n\n**所需欄位 (JSON)**：\n- `direction` (Body, str): 傳輸方向 (client_to_server / server_to_client)\n- `payload` (Body, dict): 要驗證的內文\n- `version` (Body, str): 測試針對的協定版本號",
)
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
