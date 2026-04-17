from __future__ import annotations

import asyncio

from fastapi import APIRouter, File, Form, HTTPException, UploadFile
from fastapi.responses import FileResponse

from core.chat_service import record_generation_failure
from knowledge.graph import (
    GRAPH_SUBDIR,
    EmptyGraphError,
    load_project_graph,
    load_project_status,
    load_project_summary,
    rebuild_project_graph,
)
from knowledge.workspace import get_workspace_root
from knowledge.indexer import rebuild_knowledge_index, rename_document_records
from knowledge.knowledge_admin import (
    create_workspace_directory,
    delete_workspace_directory,
    delete_workspace_document,
    list_knowledge_base_directories,
    list_knowledge_base_documents,
    list_workspace_documents,
    move_workspace_document,
    read_workspace_document,
    save_uploaded_artifact,
    save_uploaded_document,
    save_workspace_document,
    save_workspace_note,
    update_workspace_document_meta,
)
from protocol.schemas import (
    AdminActionRequest,
    KnowledgeDocumentMetaPatchRequest,
    KnowledgeDocumentMoveRequest,
    KnowledgeDocumentPutRequest,
    KnowledgeNoteCreateRequest,
)
from safety.observability import log_event, log_exception

router = APIRouter(prefix="/brain", tags=["Knowledge"])


async def _background_reindex(project_id: str) -> None:
    try:
        result = await asyncio.to_thread(rebuild_knowledge_index, project_id)
    except Exception as exc:
        log_exception("knowledge_reindex_auto_error", exc, project_id=project_id)
        return
    log_event("knowledge_reindex_auto", project_id=project_id, **result)


async def _background_rename_document(source_path: str, target_path: str, project_id: str) -> None:
    try:
        await asyncio.to_thread(rename_document_records, source_path, target_path, project_id)
    except Exception as exc:
        log_exception("knowledge_rename_auto_error", exc, project_id=project_id)
        return
    log_event(
        "knowledge_rename_auto",
        project_id=project_id,
        source_path=source_path,
        target_path=target_path,
    )


@router.get("/knowledge/documents", summary="取得工作區所有文件")
async def list_knowledge_documents_route(project_id: str = "default"):
    documents = list_workspace_documents(project_id)
    return {"documents": documents, "document_count": len(documents)}


@router.get("/knowledge/base/documents", summary="取得知識庫樹狀結構")
async def list_knowledge_base_documents_route(project_id: str = "default"):
    documents = list_knowledge_base_documents(project_id)
    directories = list_knowledge_base_directories(project_id)
    return {
        "documents": documents,
        "document_count": len(documents),
        "directories": directories,
    }


@router.get("/knowledge/document", summary="讀取單一知識文件")
async def get_knowledge_document_route(path: str, project_id: str = "default"):
    try:
        return read_workspace_document(path, project_id)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail="找不到指定文件") from exc


@router.put("/knowledge/document", summary="儲存知識文件")
async def save_knowledge_document_route(payload: KnowledgeDocumentPutRequest):
    try:
        document = save_workspace_document(payload.path, payload.content, payload.project_id)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    asyncio.create_task(_background_reindex(payload.project_id))
    return {"status": "ok", "document": document}


@router.patch("/knowledge/document/meta", summary="更新文件中繼屬性")
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


@router.delete("/knowledge/document", summary="刪除知識文件")
async def delete_knowledge_document_route(path: str, project_id: str = "default"):
    try:
        delete_workspace_document(path, project_id)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail="找不到指定文件") from exc
    asyncio.create_task(_background_reindex(project_id))
    return {"status": "ok"}


@router.post("/knowledge/move", summary="移動/重新命名知識文件")
async def move_knowledge_document_route(payload: KnowledgeDocumentMoveRequest):
    try:
        document = move_workspace_document(payload.source_path, payload.target_path, payload.project_id)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    asyncio.create_task(
        _background_rename_document(payload.source_path, payload.target_path, payload.project_id)
    )
    return {"status": "ok", "document": document}


@router.post("/knowledge/directory", summary="建立資料夾")
async def create_knowledge_directory_route(payload: KnowledgeDocumentPutRequest):
    try:
        return create_workspace_directory(payload.path, payload.project_id)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.delete("/knowledge/directory", summary="刪除資料夾")
async def delete_knowledge_directory_route(path: str, project_id: str = "default"):
    try:
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
):
    uploaded: list[dict[str, object]] = []
    try:
        for upload in files:
            uploaded.append(
                save_uploaded_artifact(upload.filename or "", await upload.read(), target_dir, project_id)
            )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return {"status": "ok", "files": uploaded}


@router.post("/knowledge/upload", summary="上傳實體檔案至知識庫")
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


@router.post("/knowledge/note", summary="建立知識筆記")
async def create_knowledge_note_route(payload: KnowledgeNoteCreateRequest):
    try:
        document = save_workspace_note(payload.title, payload.content, payload.project_id)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    asyncio.create_task(_background_reindex(payload.project_id))
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


_graph_inflight: dict[str, asyncio.Task] = {}


async def _run_graph_rebuild(project_id: str) -> None:
    from datetime import datetime, timezone

    from knowledge.graph import _write_status  # re-export internal helper

    started_at = datetime.now(timezone.utc).isoformat()
    _write_status(project_id, {"state": "building", "project_id": project_id, "started_at": started_at})
    try:
        summary = await asyncio.to_thread(rebuild_project_graph, project_id)
    except FileNotFoundError as exc:
        _write_status(project_id, {"state": "failed", "project_id": project_id, "error": str(exc), "started_at": started_at})
        log_exception("knowledge_graph_rebuild_error", exc, project_id=project_id)
        return
    except EmptyGraphError as exc:
        _write_status(project_id, {"state": "failed", "project_id": project_id, "error": str(exc), "started_at": started_at})
        log_exception("knowledge_graph_rebuild_empty", exc, project_id=project_id)
        return
    except Exception as exc:  # pragma: no cover
        _write_status(project_id, {"state": "failed", "project_id": project_id, "error": repr(exc), "started_at": started_at})
        log_exception("knowledge_graph_rebuild_error", exc, project_id=project_id)
        return
    _write_status(
        project_id,
        {
            "state": "ready",
            "project_id": project_id,
            "started_at": started_at,
            "finished_at": summary.get("built_at"),
            "nodes": summary["nodes"],
            "edges": summary["edges"],
            "communities": summary["communities"],
        },
    )
    log_event(
        "knowledge_graph_rebuild",
        project_id=project_id,
        nodes=summary["nodes"],
        edges=summary["edges"],
        communities=summary["communities"],
    )


@router.post("/knowledge/graph/rebuild", summary="在背景重建專案知識圖譜", status_code=202)
async def rebuild_knowledge_graph_route(payload: AdminActionRequest):
    pid = payload.project_id
    existing = _graph_inflight.get(pid)
    if existing and not existing.done():
        return {"status": "already_building", "project_id": pid}
    task = asyncio.create_task(_run_graph_rebuild(pid))
    _graph_inflight[pid] = task
    return {"status": "building", "project_id": pid}


@router.get("/knowledge/graph/status", summary="查詢圖譜建置狀態")
async def graph_status_route(project_id: str = "default"):
    return load_project_status(project_id)


@router.get("/knowledge/graph/summary", summary="取得專案圖譜摘要")
async def graph_summary_route(project_id: str = "default"):
    try:
        return load_project_summary(project_id)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.get("/knowledge/graph", summary="取得專案圖譜原始 JSON")
async def graph_json_route(project_id: str = "default"):
    try:
        return load_project_graph(project_id)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.get("/knowledge/graph/html", summary="取得專案圖譜 HTML 視覺化頁面")
async def graph_html_route(project_id: str = "default"):
    path = get_workspace_root(project_id) / GRAPH_SUBDIR / "graph.html"
    if not path.exists():
        raise HTTPException(status_code=404, detail="graph 尚未建立，請先呼叫 rebuild")
    return FileResponse(path, media_type="text/html")

