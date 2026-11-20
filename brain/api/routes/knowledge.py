from __future__ import annotations

import asyncio
from datetime import UTC, datetime
from typing import Annotated, Any


from fastapi import (
    APIRouter,
    Depends,
    File,
    Form,
    Header,
    HTTPException,
    Response,
    UploadFile,
)

from core.chat_service import record_generation_failure
from infra.project_context import resolve_project_context
from knowledge.graph import rename_graph_sources
from knowledge.indexer import rebuild_knowledge_index, rename_document_records
from knowledge.knowledge_admin import (
    apply_workspace_document_normalization,
    create_workspace_directory,
    delete_workspace_directory,
    delete_workspace_document,
    list_knowledge_base_directories,
    list_knowledge_base_documents,
    list_qa_entries,
    list_workspace_documents,
    move_workspace_document,
    qa_document_lock,
    preview_workspace_document_normalization,
    read_workspace_document,
    renormalize_workspace_document,
    save_uploaded_artifact,
    save_uploaded_document,
    save_workspace_document,
    save_workspace_note,
    update_workspace_document_meta,
)
from knowledge import commit_jobs
from knowledge.raw_import import (
    commit_raw_documents,
    delete_raw_file,
    list_pending_raw_files,
    list_raw_files,
    normalize_raw_paths,
)
from knowledge.upload_limits import (
    read_upload_limited,
    require_raw_suffix,
    require_target_under,
)
from knowledge.workspace import get_workspace_root
from protocol.schemas import (
    AdminActionRequest,
    KnowledgeDocumentActionRequest,
    KnowledgeDocumentMetaPatchRequest,
    KnowledgeDocumentMoveRequest,
    KnowledgeDocumentPutRequest,
    KnowledgeNoteCreateRequest,
    KnowledgeRawCommitRequest,
    KnowledgeRawPreviewRequest,
    KnowledgeSettingsPutRequest,
    ProjectFeaturesPatchRequest,
)
from routes.knowledge_graph import schedule_graph_rebuild
from safety.internal_auth import require_internal_token
from safety.observability import log_event, log_exception
from safety.vendor_access import VendorRequest, vendor_workspace_path, visible_workspace_path

router = APIRouter(
    prefix="/brain",
    tags=["Knowledge"],
    dependencies=[Depends(require_internal_token)],
)


_REINDEX_DEBOUNCE_SECONDS = 2.0
_reindex_state: dict[str, dict[str, Any]] = {}


def _short_error(exc: Exception) -> str:
    detail = " ".join(str(exc).split())
    if not detail:
        return type(exc).__name__
    return f"{type(exc).__name__}: {detail}"[:200]


def reindex_status(project_id: str) -> dict[str, Any]:
    """Return the in-memory reindex state for ``project_id``."""
    state = _reindex_state.get(project_id)
    if not state:
        return {"pending": False, "running": False, "last_error": None}
    task = state.get("task")
    pending = bool(state.get("dirty")) or (task is not None and not task.done())
    return {
        "pending": pending,
        "running": bool(state.get("running")),
        "last_error": state.get("last_error"),
    }


def schedule_reindex(project_id: str) -> None:
    """Coalesce reindex requests: debounce rapid edits, never run two at once."""
    state = _reindex_state.setdefault(
        project_id,
        {
            "task": None,
            "dirty": False,
            "running": False,
            "last_error": None,
            "finished_at": None,
        },
    )
    state["dirty"] = True
    task = state["task"]
    if task is not None and not task.done():
        return
    state["task"] = asyncio.create_task(_reindex_worker(project_id, state))


async def _reindex_worker(project_id: str, state: dict[str, Any]) -> None:
    from knowledge.kb_settings import load_kb_settings

    while state["dirty"]:
        await asyncio.sleep(_REINDEX_DEBOUNCE_SECONDS)
        state["dirty"] = False
        state["running"] = True
        try:
            result = await asyncio.to_thread(rebuild_knowledge_index, project_id)
        except Exception as exc:
            state["last_error"] = _short_error(exc)
            log_exception("knowledge_reindex_auto_error", exc, project_id=project_id)
            continue
        else:
            state["last_error"] = None
        finally:
            state["running"] = False
            state["finished_at"] = datetime.now(UTC).isoformat()
        log_event("knowledge_reindex_auto", project_id=project_id, **result)
    # 關掉圖譜的專案不在每次存檔後自動重建；要重建仍可手動呼叫 /knowledge/graph/rebuild。
    if load_kb_settings(project_id)["graph_enabled"]:
        schedule_graph_rebuild(project_id)



async def _background_rename_document(source_path: str, target_path: str, project_id: str) -> None:
    try:
        await asyncio.to_thread(rename_document_records, source_path, target_path, project_id)
        # 圖譜快取跟著換路徑，下一次重建才不會把搬過的文件重新交給 LLM 抽取。
        await asyncio.to_thread(rename_graph_sources, {source_path: target_path}, project_id)
    except Exception as exc:
        log_exception("knowledge_rename_auto_error", exc, project_id=project_id)
        return
    log_event(
        "knowledge_rename_auto",
        project_id=project_id,
        source_path=source_path,
        target_path=target_path,
    )


chat_router = APIRouter(
    prefix="/brain",
    tags=["Knowledge"],
    dependencies=[Depends(require_internal_token)],
)


@router.get("/knowledge/documents", summary="取得工作區所有文件")
async def list_knowledge_documents_route(project_id: str = "default"):
    documents = list_workspace_documents(project_id)
    return {"documents": documents, "document_count": len(documents)}


@router.get("/knowledge/base/documents", summary="取得知識庫樹狀結構")
async def list_knowledge_base_documents_route(
    project_id: str = "default", vendor: VendorRequest = False,
):
    if vendor:
        visible = lambda path: visible_workspace_path(project_id, path, "knowledge")
        documents = list_knowledge_base_documents(project_id, visible=visible)
        directories = [path for path in list_knowledge_base_directories(project_id) if visible(path)]
    else:
        documents = list_knowledge_base_documents(project_id)
        directories = list_knowledge_base_directories(project_id)
    return {
        "documents": documents,
        "document_count": len(documents),
        "directories": directories,
    }


def _assert_not_qa_document(path: str, project_id: str) -> None:
    """Block LLM-renormalization on QA files to prevent corrupting their structure.

    路徑先統一寫法，./x 這類別名才擋得住；掛在問答樹上的文件就算沒標類型也是 QA 文件。
    """
    from knowledge.qa_nodes import is_qa_document

    if is_qa_document(_document_path(path, project_id), project_id):
        raise HTTPException(status_code=400, detail="QA 知識文件不支援重新整理，以免破壞問答格式結構")



@router.get("/knowledge/qa", summary="取得所有已啟用 QA 來源的問答清單")
async def list_knowledge_qa_route(
    project_id: str = "default", vendor: VendorRequest = False,
):
    if vendor:
        entries = list_qa_entries(
            project_id, visible=lambda path: visible_workspace_path(project_id, path, "knowledge"),
        )
    else:
        entries = list_qa_entries(project_id)
    return {"entries": entries, "count": len(entries)}


def _document_path(path: str, project_id: str) -> str:
    """The one spelling of a workspace document, so ./x and x//y match the tree's paths."""
    from knowledge.workspace import ensure_workspace_scaffold, resolve_workspace_document

    try:
        resolved = resolve_workspace_document(path, project_id)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return resolved.relative_to(ensure_workspace_scaffold(project_id).resolve()).as_posix()


ProjectWrites = Annotated[
    str, Header(alias="X-OpenVMan-Project-Writes", include_in_schema=False)
]
_PERSONA_DOCUMENTS = frozenset({"SOUL.md", "IDENTITY.md", "AGENTS.md", "TOOLS.md"})


def _require_workspace_write(granted: str, *paths: str) -> None:
    # 沒有能力標頭的舊 Backend／內部呼叫仍由既有 internal token 管理。
    if not granted:
        return
    permissions = granted.split(",")
    for path in paths:
        parts = path.split("/")
        knowledge = (
            parts[0] in {"knowledge", "raw"}
            or (len(parts) == 1 and parts[0] in _PERSONA_DOCUMENTS)
            or (
                parts[0] == "personas"
                and (len(parts) <= 2 or (len(parts) == 3 and parts[-1] in _PERSONA_DOCUMENTS))
            )
        )
        required = "edit_knowledge" if knowledge else "edit_settings"
        if required not in permissions:
            raise HTTPException(status_code=403, detail="沒有修改此工作區路徑的權限")


def _require_directory_write(granted: str, path: str, project_id: str) -> None:
    if granted:
        root = get_workspace_root(project_id).resolve()
        target = (root / path.strip()).resolve()
        _require_workspace_write(granted, target.relative_to(root).as_posix())


def _check_workspace_document_write(
    granted: str, path: str, project_id: str, content: str | None = None,
) -> str:
    relative = _document_path(path, project_id)
    _require_workspace_write(granted, relative)
    _check_guardrails_write(path, relative, project_id, content)
    return relative


def _check_guardrails_write(
    requested: str, relative: str, project_id: str, content: str | None,
) -> None:
    """Refuse guardrails that are links or too long to go into the prompt whole."""
    from posixpath import normpath

    from knowledge.workspace import (
        GUARDRAILS_FILENAME,
        GUARDRAILS_MAX_CHARS,
        guardrails_link_problem,
    )

    if normpath(requested.strip()) == GUARDRAILS_FILENAME and guardrails_link_problem(project_id):
        # 連結會把內容寫到連結目標；提示詞也不採用連結，請專人先換成一般檔案。
        raise HTTPException(
            status_code=409,
            detail="保護規則檔案是連結，AI 不會採用，也不能從這裡修改；請技術人員先換成一般檔案。",
        )
    if relative == GUARDRAILS_FILENAME and content is not None and len(content) > GUARDRAILS_MAX_CHARS:
        raise HTTPException(
            status_code=400,
            detail=f"保護規則最多 {GUARDRAILS_MAX_CHARS} 字，現在有 {len(content)} 字，請精簡後再存。",
        )


def _content_hash(text: str) -> str:
    from knowledge.workspace import content_hash

    return content_hash(text)


@router.get("/knowledge/document", summary="讀取單一知識文件")
async def get_knowledge_document_route(
    path: str, project_id: str = "default", vendor: VendorRequest = False,
):
    if vendor:
        vendor_workspace_path(project_id, path, "knowledge")
    try:
        document = read_workspace_document(path, project_id)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail="找不到指定文件") from exc
    return {**document, "content_hash": _content_hash(document.get("content", ""))}


@router.put("/knowledge/document", summary="儲存知識文件")
async def save_knowledge_document_route(
    payload: KnowledgeDocumentPutRequest, project_writes: ProjectWrites = "",
    vendor: VendorRequest = False,
):
    # 問答存檔會改同一份檔案，兩邊都進同一把鎖；帶了 base_hash 時，載入後被改過就拒絕，
    # 否則開著的舊全文會蓋掉別處剛存的內容。
    def _save() -> dict[str, Any]:
        from knowledge.qa_nodes import is_qa_document, sync_entries_for_source

        with qa_document_lock:
            if vendor:
                vendor_workspace_path(payload.project_id, payload.path, "knowledge")
            path = _check_workspace_document_write(
                project_writes, payload.path, payload.project_id, payload.content,
            )
            if payload.base_hash:
                try:
                    current = read_workspace_document(path, payload.project_id).get("content", "")
                except FileNotFoundError:
                    current = None
                if current is not None and _content_hash(current) != payload.base_hash:
                    raise HTTPException(
                        status_code=409, detail="這份文件在你編輯時被改過了，請重新載入後再存檔",
                    )
            try:
                document = save_workspace_document(path, payload.content, payload.project_id)
            except ValueError as exc:
                raise HTTPException(status_code=400, detail=str(exc)) from exc
            # QA 文件允許在文件頁編輯：儲存後把掛載中節點的條目同步成檔案現況。
            if is_qa_document(path, payload.project_id):
                sync_entries_for_source(path, payload.project_id)
            return document

    document = await asyncio.to_thread(_save)
    schedule_reindex(payload.project_id)
    return {"status": "ok", "document": document}


def _with_speech_rates(settings: dict) -> dict:
    # 後台用同一組語速即時換算「幾秒＝幾個字」，不在前端另寫一份。
    from core.prompt_templates import speech_rates

    return {**settings, "speech_rates": speech_rates()}


@router.get("/knowledge/settings", summary="取得知識庫設定（語言分流、回答長度）")
@chat_router.get("/knowledge/settings", summary="取得知識庫設定（語言分流、回答長度）")
async def get_knowledge_settings_route(project_id: str = "default"):
    from knowledge.kb_settings import load_kb_settings

    return _with_speech_rates(load_kb_settings(project_id))


@router.put("/knowledge/settings", summary="更新知識庫設定（語言分流、回答長度）")
async def put_knowledge_settings_route(payload: KnowledgeSettingsPutRequest):
    from knowledge.kb_settings import save_kb_settings

    return _with_speech_rates(save_kb_settings(
        payload.project_id,
        language_routes=payload.language_routes,
        reply_seconds=payload.reply_seconds,
    ))


@router.patch("/knowledge/features", summary="更新專案回答功能")
async def patch_project_features_route(
    payload: ProjectFeaturesPatchRequest, project_writes: ProjectWrites = "",
):
    from knowledge.kb_settings import save_project_features

    if "edit_settings" not in project_writes.split(","):
        raise HTTPException(status_code=403, detail="沒有修改其他專案設定的權限")
    try:
        project = resolve_project_context(payload.project_id)
        if project.project_id in {".", ".."}:
            raise ValueError("project_id 格式不合法")
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    if not project.project_root.is_dir():
        raise HTTPException(status_code=404, detail="專案不存在")
    return _with_speech_rates(save_project_features(
        project.project_id,
        memory_enabled=payload.memory_enabled,
        graph_enabled=payload.graph_enabled,
    ))


@router.patch("/knowledge/document/meta", summary="更新文件中繼屬性")
async def patch_knowledge_document_meta_route(
    payload: KnowledgeDocumentMetaPatchRequest, project_writes: ProjectWrites = "",
    vendor: VendorRequest = False,
):
    if vendor:
        vendor_workspace_path(payload.project_id, payload.path, "knowledge")
    try:
        path = _check_workspace_document_write(
            project_writes, payload.path, payload.project_id,
        )
        document = update_workspace_document_meta(
            path,
            payload.project_id,
            enabled=payload.enabled,
            source_type=payload.source_type,
            source_url=payload.source_url,
            language=payload.language,
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
        "language": document["language"],
        "language_source": document["language_source"],
    }


@router.delete("/knowledge/document", summary="刪除知識文件")
async def delete_knowledge_document_route(
    path: str, project_id: str = "default", project_writes: ProjectWrites = "",
    vendor: VendorRequest = False,
):
    def _delete() -> None:
        from knowledge.qa_nodes import is_qa_document, remove_entries_for_source

        with qa_document_lock:
            if vendor:
                vendor_workspace_path(project_id, path, "knowledge")
            relative = _check_workspace_document_write(project_writes, path, project_id)
            if is_qa_document(relative, project_id):
                remove_entries_for_source(relative, project_id)
            try:
                delete_workspace_document(relative, project_id)
            except ValueError as exc:
                raise HTTPException(status_code=400, detail=str(exc)) from exc
            except FileNotFoundError as exc:
                raise HTTPException(status_code=404, detail="找不到指定文件") from exc

    await asyncio.to_thread(_delete)
    schedule_reindex(project_id)
    return {"status": "ok"}


@router.post("/knowledge/move", summary="移動/重新命名知識文件")
async def move_knowledge_document_route(
    payload: KnowledgeDocumentMoveRequest, project_writes: ProjectWrites = "",
    vendor: VendorRequest = False,
):
    def _move() -> tuple[str, str, dict[str, Any]]:
        from knowledge.qa_nodes import is_qa_document, rename_source_path_in_nodes

        with qa_document_lock:
            if vendor:
                vendor_workspace_path(payload.project_id, payload.source_path, "knowledge")
                vendor_workspace_path(payload.project_id, payload.target_path, "knowledge")
            source = _document_path(payload.source_path, payload.project_id)
            target = _document_path(payload.target_path, payload.project_id)
            _require_workspace_write(project_writes, source, target)
            if target == "GUARDRAILS.md" or payload.target_path.strip() == "GUARDRAILS.md":
                moved = read_workspace_document(source, payload.project_id).get("content", "")
                _check_guardrails_write(payload.target_path, target, payload.project_id, moved)
            is_qa = is_qa_document(source, payload.project_id)
            try:
                document = move_workspace_document(source, target, payload.project_id)
            except ValueError as exc:
                raise HTTPException(status_code=400, detail=str(exc)) from exc
            except FileNotFoundError as exc:
                raise HTTPException(status_code=404, detail=str(exc)) from exc
            if is_qa:
                rename_source_path_in_nodes(source, target, payload.project_id)
            return source, target, document

    source, target, document = await asyncio.to_thread(_move)
    asyncio.create_task(_background_rename_document(source, target, payload.project_id))
    return {"status": "ok", "document": document}


@router.post("/knowledge/directory", summary="建立資料夾")
async def create_knowledge_directory_route(
    payload: KnowledgeDocumentPutRequest, project_writes: ProjectWrites = "",
    vendor: VendorRequest = False,
):
    if vendor:
        vendor_workspace_path(payload.project_id, payload.path, "knowledge")
    try:
        _require_directory_write(project_writes, payload.path, payload.project_id)
        return create_workspace_directory(payload.path, payload.project_id)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.delete("/knowledge/directory", summary="刪除資料夾")
async def delete_knowledge_directory_route(
    path: str, project_id: str = "default", project_writes: ProjectWrites = "",
    vendor: VendorRequest = False,
):
    if vendor:
        vendor_workspace_path(project_id, path, "knowledge")
    try:
        _require_directory_write(project_writes, path, project_id)
        return delete_workspace_directory(path, project_id)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.post("/knowledge/raw/upload", summary="上傳原始檔案至 raw 區")
async def upload_knowledge_raw_documents_route(
    files: list[UploadFile] = File(...),
    target_dir: str = Form("raw"),
    project_id: str = Form("default"),
    relative_paths: list[str] = Form(default_factory=list),
    vendor: VendorRequest = False,
):
    from config import get_settings

    max_bytes = get_settings().knowledge_upload_max_bytes
    # raw 是暫存區：只能寫進 raw/，不能借這個端點改 personas/、memory/ 或核心文件。
    target_dir = require_target_under(target_dir, "raw")
    uploaded: list[dict[str, object]] = []
    try:
        for index, upload in enumerate(files):
            relative_path = (
                relative_paths[index] if index < len(relative_paths) else ""
            )
            require_raw_suffix(upload.filename or "", relative_path)
            uploaded.append(
                save_uploaded_artifact(
                    upload.filename or "",
                    await read_upload_limited(upload, max_bytes),
                    target_dir,
                    project_id,
                    relative_path=relative_path,
                    vendor=vendor,
                )
            )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return {"status": "ok", "files": uploaded}


@router.post("/knowledge/renormalize/preview", summary="預覽既有知識文件整理結果")
async def preview_renormalize_knowledge_document_route(
    payload: KnowledgeDocumentActionRequest, project_writes: ProjectWrites = "",
):
    pid = payload.project_id
    _assert_not_qa_document(payload.path, pid)
    try:
        path = _check_workspace_document_write(project_writes, payload.path, pid)
        document = await asyncio.to_thread(
            preview_workspace_document_normalization, path, pid
        )
    except HTTPException:
        raise
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:  # pragma: no cover
        log_exception("knowledge_renormalize_preview_error", exc, project_id=pid)
        raise HTTPException(status_code=500, detail="整理預覽失敗") from exc
    return {"status": "ok", "project_id": pid, **document}


@router.post("/knowledge/renormalize/apply", summary="套用預覽整理結果並重建索引與圖譜")
async def apply_renormalize_knowledge_document_route(
    payload: KnowledgeDocumentPutRequest, project_writes: ProjectWrites = "",
    vendor: VendorRequest = False,
):
    pid = payload.project_id
    _assert_not_qa_document(payload.path, pid)
    try:
        path = _check_workspace_document_write(project_writes, payload.path, pid, payload.content)
        document = await asyncio.to_thread(
            apply_workspace_document_normalization, path, payload.content, pid
        )
    except HTTPException:
        raise
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:  # pragma: no cover
        log_exception("knowledge_renormalize_apply_error", exc, project_id=pid)
        raise HTTPException(status_code=500, detail="套用整理失敗") from exc

    log_event("knowledge_renormalize_apply", project_id=pid, path=payload.path)
    schedule_reindex(pid)

    return {
        "status": "ok",
        "project_id": pid,
        "document": document,
        "indexed": "background",
        "graph": "building",
    }


@router.post("/knowledge/renormalize", summary="重新整理既有知識文件並重建索引與圖譜")
async def renormalize_knowledge_document_route(
    payload: KnowledgeDocumentActionRequest, project_writes: ProjectWrites = "",
):
    """Re-run LLM normalization over an existing knowledge/ document (in place),
    then reindex and rebuild the graph so the cleaned content re-enters RAG.
    """
    pid = payload.project_id
    _assert_not_qa_document(payload.path, pid)
    try:
        path = _check_workspace_document_write(project_writes, payload.path, pid)
        document = await asyncio.to_thread(
            renormalize_workspace_document, path, pid
        )
    except HTTPException:
        raise
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:  # pragma: no cover
        log_exception("knowledge_renormalize_error", exc, project_id=pid)
        raise HTTPException(status_code=500, detail="整理失敗") from exc

    log_event("knowledge_renormalize", project_id=pid, path=payload.path)
    schedule_reindex(pid)

    return {
        "status": "ok",
        "project_id": pid,
        "document": document,
        "indexed": "background",
        "graph": "building",
    }


@router.post("/knowledge/raw/preview", summary="匯入前預覽 raw 區問答表（不寫檔、不改節點）")
async def preview_knowledge_raw_route(
    payload: KnowledgeRawPreviewRequest, vendor: VendorRequest = False,
):
    from knowledge.qa_import_preview import preview_raw_documents

    try:
        return await asyncio.to_thread(
            preview_raw_documents,
            payload.project_id,
            paths=payload.paths,
            vendor=bool(vendor),
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.post("/knowledge/raw/commit", summary="匯入 raw 區檔案進知識庫（背景執行，逐檔進度可查詢）", status_code=202)
async def commit_knowledge_raw_route(
    payload: KnowledgeRawCommitRequest, response: Response, vendor: VendorRequest = False,
):
    """The 'commit' step: promote staged raw/ files into knowledge/ in the
    background (per-file LLM normalization is slow), then rebuild the vector
    index and concept graph. Progress is polled via /knowledge/raw/commit/status.

    ``paths`` limits the job to those files, so older uploads still waiting in raw/
    are not swept along; ``normalize=false`` skips the LLM step.
    """
    pid = payload.project_id
    try:
        requested = (
            None
            if payload.paths is None
            else await asyncio.to_thread(normalize_raw_paths, payload.paths, pid)
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    pending = await asyncio.to_thread(list_raw_files, pid)
    files = pending if requested is None else requested
    if vendor:
        for path in requested or []:
            vendor_workspace_path(pid, f"raw/{path}", "raw")
        files = [path for path in files if visible_workspace_path(pid, f"raw/{path}", "raw")]
    if not set(files) & set(pending):
        response.status_code = 200
        return {"status": "nothing_to_commit", "project_id": pid, "committed": [], "skipped": []}
    if not commit_jobs.start_job(pid, files):
        response.status_code = 200
        return {"status": "already_running", "project_id": pid, "job": commit_jobs.job_snapshot(pid)}
    decisions = (
        {key: item.model_dump() for key, item in payload.decisions.items()}
        if payload.decisions
        else None
    )
    # 一律帶明確清單：開工後才傳上來的檔案不算這一批。
    asyncio.create_task(
        _run_commit_job(
            pid,
            files,
            payload.normalize,
            **({"vendor": True} if vendor else {}),
            **({"decisions": decisions} if decisions else {}),
        )
    )
    response.status_code = 202
    return {"status": "started", "project_id": pid, "job": commit_jobs.job_snapshot(pid)}


async def _run_commit_job(
    project_id: str,
    files: list[str],
    normalize: bool = True,
    *,
    vendor: bool = False,
    decisions: dict[str, Any] | None = None,
) -> None:
    def _on_progress(path: str, state: str) -> None:
        commit_jobs.update_file(project_id, path, state)

    def _on_result(path: str, result: dict[str, Any]) -> None:
        commit_jobs.record_result(project_id, path, result)

    def _on_skip(path: str, reason: str) -> None:
        commit_jobs.record_skip(project_id, path, reason)

    try:
        result = await asyncio.to_thread(
            commit_raw_documents,
            project_id,
            _on_progress,
            paths=files,
            normalize=normalize,
            on_result=_on_result,
            on_skip=_on_skip,
            **({"vendor": True} if vendor else {}),
            **({"decisions": decisions} if decisions else {}),
        )
    except Exception as exc:
        commit_jobs.fail_job(project_id, "匯入中斷，還沒處理的檔案都留著，可以再試一次")
        log_exception("knowledge_commit_error", exc, project_id=project_id)
        return
    commit_jobs.finish_job(project_id, result["committed"], result["skipped"])
    log_event(
        "knowledge_commit",
        project_id=project_id,
        committed=len(result["committed"]),
        skipped=len(result["skipped"]),
    )
    if result["committed"]:
        schedule_reindex(project_id)


@router.get("/knowledge/raw/commit/status", summary="查詢匯入進度")
async def commit_status_route(project_id: str = "default"):
    return commit_jobs.job_snapshot(project_id)


@router.get("/knowledge/raw/pending", summary="列出等待匯入的檔案")
async def list_raw_pending_route(project_id: str = "default", vendor: VendorRequest = False):
    # 正在匯入的不算等待中。沒匯入成功的還在 raw/，要列出來才看得到、才移得掉。
    active = commit_jobs.active_files(project_id)
    files = await asyncio.to_thread(list_pending_raw_files, project_id)
    return {"files": [
        item for item in files
        if item["path"] not in active and (
            not vendor or visible_workspace_path(project_id, f"raw/{item['path']}", "raw")
        )
    ]}


@router.delete("/knowledge/raw/pending", summary="移除一個等待匯入的檔案")
async def delete_raw_pending_route(
    path: str, project_id: str = "default", vendor: VendorRequest = False,
):
    try:
        relative = (await asyncio.to_thread(normalize_raw_paths, [path], project_id))[0]
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    if vendor:
        vendor_workspace_path(project_id, f"raw/{relative}", "raw")
    if relative in commit_jobs.active_files(project_id):
        raise HTTPException(status_code=409, detail="這個檔案正在匯入，等匯入結束再移除")
    try:
        await asyncio.to_thread(delete_raw_file, relative, project_id)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return {"status": "ok"}


@router.post("/knowledge/upload", summary="上傳實體檔案至知識庫")
async def upload_knowledge_documents_route(
    files: list[UploadFile] = File(...),
    target_dir: str = Form(""),
    project_id: str = Form("default"),
    relative_paths: list[str] = Form(default_factory=list),
    vendor: VendorRequest = False,
):
    from config import get_settings

    max_bytes = get_settings().knowledge_upload_max_bytes
    target_dir = require_target_under(target_dir, "knowledge")
    contents = [await read_upload_limited(upload, max_bytes) for upload in files]

    def _save_all() -> list[dict[str, object]]:
        # 覆蓋上傳可能蓋到問答存檔正在改的檔案，同一把鎖。
        with qa_document_lock:
            return [
                save_uploaded_document(
                    upload.filename or "",
                    content,
                    target_dir,
                    project_id,
                    relative_path=relative_paths[index] if index < len(relative_paths) else "",
                    vendor=vendor,
                )
                for index, (upload, content) in enumerate(zip(files, contents))
            ]

    try:
        uploaded = await asyncio.to_thread(_save_all)
    except UnicodeDecodeError as exc:
        raise HTTPException(status_code=400, detail="檔案需為 UTF-8 編碼") from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    schedule_reindex(project_id)
    return {"status": "ok", "files": uploaded}


@router.post("/knowledge/note", summary="建立知識筆記")
async def create_knowledge_note_route(payload: KnowledgeNoteCreateRequest, vendor: VendorRequest = False):
    def _create() -> dict[str, Any]:
        # 問答筆記會建節點，和問答存檔用同一把鎖。
        with qa_document_lock:
            return save_workspace_note(
                payload.title,
                payload.content,
                payload.project_id,
                payload.target_dir,
                note_format=payload.note_format,
                **({"vendor": True} if vendor else {}),
            )

    try:
        document = await asyncio.to_thread(_create)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    schedule_reindex(payload.project_id)
    return {"status": "ok", "document": document, "path": document["path"], "size": document["size"]}


@router.post("/knowledge/reindex", summary="重整全域知識索引")
async def reindex_knowledge_route(payload: AdminActionRequest):
    try:
        result = await asyncio.to_thread(rebuild_knowledge_index, payload.project_id)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:  # pragma: no cover
        log_exception("knowledge_reindex_error", exc)
        record_generation_failure("reindex", "index_failure", str(exc))
        raise HTTPException(status_code=500, detail="知識重建失敗") from exc
    log_event("knowledge_reindex", project_id=payload.project_id, **result)
    return result
