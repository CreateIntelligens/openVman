from __future__ import annotations

import asyncio

from fastapi import APIRouter, File, Form, HTTPException, UploadFile

from core.chat_service import record_generation_failure
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

