from __future__ import annotations

import asyncio
from collections import defaultdict
import logging
import re
from pathlib import Path
from typing import Any
from uuid import uuid4

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile
from fastapi.responses import FileResponse
from pydantic import BaseModel

from config import get_settings
from knowledge.doc_meta import upsert_document_meta
from knowledge.knowledge_admin import (
    delete_workspace_document,
    qa_document_lock,
    resolve_workspace_artifact,
    resolve_workspace_document,
    save_uploaded_artifact,
    save_workspace_document,
)
from knowledge.upload_limits import read_upload_limited, validate_qa_image
from knowledge.qa_csv import (
    append_qa_csv_rows,
    extract_image_id,
    is_qa_csv,
    parse_qa_csv,
    parse_qa_markdown,
    qa_entry_values,
    qa_markdown_block,
    serialize_qa_csv,
)
from knowledge.qa_images import (
    ALLOWED_QA_IMAGE_SUFFIXES,
    QA_IMAGE_MEDIA_TYPES,
    qa_image_kind,
    resolve_qa_image_path,
)
from knowledge.qa_merged import (
    MergedSaveError,
    canonical_knowledge_path,
    conflict_detail,
    ingest_loss,
    merged_rows,
    normalized_qa_source,
    read_question,
    save_merged_rows,
)
from knowledge.qa_nodes import (
    add_qa_entry_to_node,
    cleanup_unused_images,
    create_node,
    create_node_for_source,
    delete_node,
    get_node,
    get_node_tree,
    is_source_referenced,
    list_nodes,
    move_node,
    remove_qa_entry_from_node,
    reorder_node,
    sync_entries_for_source,
    update_node,
)

from routes.knowledge import schedule_reindex
from safety.internal_auth import require_internal_token

logger = logging.getLogger(__name__)

# 這些訊息會直接顯示在後台，工作人員看到的是「分類」。
_CATEGORY_NOT_FOUND = "找不到這個分類，可能已經被刪除，請重新整理頁面"
_MOVE_REFUSED = "不能移到這裡，目標分類可能已經被刪除，或者就在這個分類底下"

router = APIRouter(
    prefix="/brain/knowledge/qa",
    tags=["Knowledge QA"],
    dependencies=[Depends(require_internal_token)],
)



class CreateNodeRequest(BaseModel):
    node_id: str
    label: str
    parent_ids: list[str] | None = None
    child_ids: list[str] | None = None
    order: float | None = None
    hidden: bool | None = False


class UpdateNodeRequest(BaseModel):
    label: str | None = None
    hidden: bool | None = None


class MoveNodeRequest(BaseModel):
    new_parent_ids: list[str]


class ReorderNodeRequest(BaseModel):
    sibling_ids_ordered: list[str]


class SourcePathRequest(BaseModel):
    path: str
    parent_id: str | None = None


class MergedQaItem(BaseModel):
    index: str | None = ""
    q: str
    a: str
    img: str | None = ""
    url: str | None = ""
    # 空字串是選單專用題目，不寫進任何文件。維持必填：漏帶不能被當成選單專用題目。
    source_file: str
    hidden: bool | None = False
    # 載入時的題目，用來認出改名；新列不帶。
    original_q: str | None = None
    # 載入時的版本，內容已被改過就拒絕存檔；新列不帶。
    base_version: str | None = None


class AddEntryRequest(BaseModel):
    question: str
    source_path: str = ""
    hidden: bool = False


def parse_qa_markdown_with_metadata(content: str) -> list[dict[str, Any]]:
    """Parse qa markdown file into a list of dict containing q, a, img, url."""
    return parse_qa_markdown(content)


def _parse_qa_bytes(suffix: str, content: bytes) -> list[dict[str, Any]] | None:
    """Parse a QA document by format: ``[]`` when blank, ``None`` when not valid UTF-8 QA.

    不猜編碼：猜錯的亂碼一旦併進 UTF-8 檔就救不回來，索引也只讀 UTF-8。
    """
    if not content.strip():
        return []
    try:
        text = content.decode("utf-8-sig")
    except UnicodeDecodeError:
        return None
    if suffix.lower() == ".csv":
        return parse_qa_csv(content) if is_qa_csv(content) else None
    return parse_qa_markdown(text) or None


def _conflicting_questions(
    items: list[dict[str, Any]], against: list[dict[str, Any]],
) -> list[str]:
    """Questions in ``items`` whose answer differs from another answer in ``against``."""
    answers: defaultdict[str, set[str]] = defaultdict(set)
    for item in against:
        answers[item["q"].strip()].add(item["a"].strip())
    return list(dict.fromkeys(
        item["q"].strip()
        for item in items
        if answers[item["q"].strip()] - {item["a"].strip()}
    ))


def _merged_target_content(target_file: Path, new_items: list[dict[str, Any]]) -> str:
    """Target content with ``new_items`` added after everything it already has."""
    existing = target_file.read_bytes() if target_file.exists() else b""
    if target_file.suffix.lower() == ".csv":
        if existing.strip():
            return append_qa_csv_rows(existing, new_items)
        return serialize_qa_csv(new_items)
    blocks = [
        qa_markdown_block(
            item["q"],
            item["a"],
            item.get("img") or "",
            item.get("url") or "",
            bool(item.get("hidden", False)),
        )
        for item in new_items
    ]
    existing_text = existing.decode("utf-8-sig").rstrip()
    return "\n\n".join([existing_text, *blocks] if existing_text else blocks)


@router.get("/nodes")
def list_qa_nodes_route(project_id: str = "default") -> list[dict[str, Any]]:
    return get_node_tree(project_id)


@router.post("/nodes/adopt-source")
async def adopt_source_route(
    payload: SourcePathRequest,
    project_id: str = "default",
) -> dict[str, Any]:
    def _adopt() -> dict[str, Any]:
        path = payload.path.strip()
        if not path:
            raise HTTPException(status_code=400, detail="path 不可為空")

        try:
            path = canonical_knowledge_path(path, project_id)
        except MergedSaveError as exc:
            raise HTTPException(status_code=exc.status, detail=exc.detail) from exc

        if is_source_referenced(path, project_id):
            raise HTTPException(status_code=400, detail="這份文件已經在快速問答裡了")

        doc_path = resolve_workspace_document(path, project_id)

        if not doc_path.exists():
            raise HTTPException(status_code=404, detail="找不到指定文件")

        if not _parse_qa_bytes(doc_path.suffix, doc_path.read_bytes()):
            raise HTTPException(status_code=400, detail="無效的 QA 文件格式")

        parent_ids = None
        if payload.parent_id is not None:
            parent_node = get_node(payload.parent_id, project_id=project_id)
            if not parent_node:
                raise HTTPException(status_code=400, detail="找不到指定的上層分類，可能已經被刪除")
            parent_ids = [payload.parent_id]

        label = doc_path.stem
        try:
            node = create_node_for_source(path, label, project_id=project_id, parent_ids=parent_ids)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

        upsert_document_meta(path, project_id, source_type="qa")
        return {"node_id": node["node_id"]}

    result = await asyncio.to_thread(_adopt)
    schedule_reindex(project_id)
    return result


@router.post("/nodes/{id}/ingest-source")
async def ingest_source_route(
    id: str,
    payload: SourcePathRequest,
    project_id: str = "default",
) -> dict[str, Any]:
    def _ingest() -> dict[str, Any]:
        path = payload.path.strip()
        if not path:
            raise HTTPException(status_code=400, detail="path 不可為空")

        node = get_node(id, project_id=project_id)
        if not node:
            raise HTTPException(status_code=404, detail=_CATEGORY_NOT_FOUND)

        try:
            path = canonical_knowledge_path(path, project_id)
        except MergedSaveError as exc:
            raise HTTPException(status_code=exc.status, detail=exc.detail) from exc
        dragged_path = resolve_workspace_document(path, project_id)

        if not dragged_path.exists():
            raise HTTPException(status_code=404, detail="找不到指定文件")

        # 文件自己的那個節點併入別處是正常的搬移；還分給其他節點時，刪來源會連帶清空它們。
        mounted_on = [
            other_id
            for other_id, other in list_nodes(project_id).items()
            if other_id != id
            and any(entry.get("source_path") == path for entry in other.get("qa_entries", []))
        ]
        if len(mounted_on) > 1:
            raise HTTPException(
                status_code=400,
                detail="這份文件還分給其他分類，併入後那些分類的題目會消失，未做任何變更",
            )

        dragged_items = _parse_qa_bytes(dragged_path.suffix, dragged_path.read_bytes())
        if not dragged_items:
            raise HTTPException(status_code=400, detail="無效的 QA 文件格式")

        if conflicts := _conflicting_questions(dragged_items, dragged_items):
            raise HTTPException(
                status_code=400,
                detail=conflict_detail("來源文件的同一題有不同答案", conflicts),
            )

        qa_entries = node.get("qa_entries", [])
        target_path = next((entry["source_path"] for entry in qa_entries if entry.get("source_path")), "")

        if not target_path:
            target_path = f"knowledge/qa/{id}.md"

        try:
            target_file = resolve_workspace_document(target_path, project_id)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

        if target_file == dragged_path:
            raise HTTPException(status_code=400, detail="這份文件已經在這個分類裡了")

        # 讀不懂的目標不能當成空的：寫回去就把原內容整份蓋掉了。
        target_items: list[dict[str, Any]] = []
        if target_file.exists():
            parsed_target = _parse_qa_bytes(target_file.suffix, target_file.read_bytes())
            if parsed_target is None:
                raise HTTPException(status_code=400, detail="目標 QA 文件格式無法解析，未做任何變更")
            target_items = parsed_target

        # 題目相同答案不同時要有人決定留哪個，不能跳過後把來源刪掉，那份答案就不見了。
        if conflicts := _conflicting_questions(dragged_items, target_items):
            raise HTTPException(
                status_code=400,
                detail=conflict_detail("來源和目標的同一題答案不同", conflicts),
            )
        if loss := ingest_loss(path, target_items, dragged_items, project_id):
            raise HTTPException(status_code=400, detail=f"{loss}，未做任何變更")
        # 同一個分類不能有文字相同的題目；別的來源的同名題併不進來。
        other_sources = {
            entry["question"] for entry in qa_entries if (entry.get("source_path") or "") != target_path
        }
        if clashes := sorted(other_sources & {item["q"].strip() for item in dragged_items}):
            raise HTTPException(
                status_code=400,
                detail=conflict_detail("這個分類已經有同名的題目", clashes),
            )

        in_target = {item["q"].strip(): item for item in target_items}
        node_questions = {
            entry["question"] for entry in qa_entries if entry.get("source_path") == target_path
        }
        new_items: list[dict[str, Any]] = []
        new_qa_entries = list(qa_entries)

        # 節點對照「還沒列入的題」而不是「這次新增的題」：上次寫完目標、更新節點失敗時，
        # 重試才補得回節點。檔案已有的題以檔案的隱藏與圖片為準。
        for item in dragged_items:
            q = item["q"].strip()
            if q not in in_target:
                in_target[q] = item
                new_items.append(item)
            if q not in node_questions:
                node_questions.add(q)
                kept = in_target[q]
                new_qa_entries.append({
                    "question": q,
                    "source_path": target_path,
                    "hidden": bool(kept.get("hidden", False)),
                    "image_id": extract_image_id(kept.get("img") or "") or None,
                })

        if new_items:
            content = _merged_target_content(target_file, new_items)
            # 寫入前先讀回比對：來源的 ## 行、多行題目、列長度不齊等，都可能讓內容讀出來
            # 不一樣；這種情況不寫也不刪來源，才不會默默丟資料。
            reread = _parse_qa_bytes(target_file.suffix, content.encode("utf-8"))
            if qa_entry_values(reread or []) != qa_entry_values([*target_items, *new_items]):
                raise HTTPException(
                    status_code=400,
                    detail="這份內容無法完整併入目標 QA 文件的格式，未做任何變更",
                )
            save_workspace_document(target_path, content, project_id)
            upsert_document_meta(target_path, project_id, source_type="qa")

        if new_qa_entries != qa_entries:
            update_node(id, {"qa_entries": new_qa_entries}, project_id=project_id)

        delete_workspace_document(path, project_id)
        # 被吸收的文件若原屬其他節點，清掉那些節點的懸空 entries
        sync_entries_for_source(path, project_id)
        return {"added": len(new_items)}

    def _ingest_exclusively() -> dict[str, Any]:
        # 從讀目標到刪來源要一起完成，否則同時兩次拖曳會有一邊的題目被蓋掉、來源卻已刪。
        with qa_document_lock:
            return _ingest()

    result = await asyncio.to_thread(_ingest_exclusively)
    schedule_reindex(project_id)
    return result


@router.post("/nodes")
def create_qa_node_route(
    payload: CreateNodeRequest,
    project_id: str = "default",
) -> dict[str, Any]:
    try:
        node = create_node(
            node_id=payload.node_id,
            label=payload.label,
            parent_ids=payload.parent_ids,
            child_ids=payload.child_ids,
            order=payload.order,
            hidden=payload.hidden,
            project_id=project_id,
        )
        return node
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.patch("/nodes/{id}")
def patch_qa_node_route(
    id: str,
    payload: UpdateNodeRequest,
    project_id: str = "default",
) -> dict[str, Any]:
    updates: dict[str, Any] = {}
    if payload.label is not None:
        updates["label"] = payload.label
    if payload.hidden is not None:
        updates["hidden"] = payload.hidden

    try:
        node = update_node(id, updates, project_id=project_id)
        if node is None:
            raise HTTPException(status_code=404, detail=_CATEGORY_NOT_FOUND)
        return node
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.delete("/nodes/{id}")
def delete_qa_node_route(id: str, project_id: str = "default") -> dict[str, str]:
    # 只拿掉分類與掛載；文件要刪到文件樹刪，刪分類不該把知識一起刪掉。
    if not delete_node(id, project_id=project_id):
        raise HTTPException(status_code=404, detail=_CATEGORY_NOT_FOUND)
    return {"status": "ok"}


@router.post("/nodes/{id}/move")
def move_qa_node_route(
    id: str,
    payload: MoveNodeRequest,
    project_id: str = "default",
) -> dict[str, Any]:
    try:
        node = move_node(id, payload.new_parent_ids, project_id=project_id)
        if node is None:
            raise HTTPException(status_code=404, detail=_CATEGORY_NOT_FOUND)
        return node
    except ValueError as exc:
        # move_node 的訊息帶內部編號，這句會直接顯示在「移到…」對話框。
        raise HTTPException(status_code=400, detail=_MOVE_REFUSED) from exc


@router.post("/nodes/{id}/reorder")
def reorder_qa_node_route(
    id: str,
    payload: ReorderNodeRequest,
    project_id: str = "default",
) -> dict[str, Any]:
    try:
        node = reorder_node(id, payload.sibling_ids_ordered, project_id=project_id)
        if node is None:
            raise HTTPException(status_code=404, detail=_CATEGORY_NOT_FOUND)
        return node
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.get("/nodes/{id}/merged")
def get_merged_qa_route(
    id: str,
    project_id: str = "default",
) -> list[dict[str, Any]]:
    node = get_node(id, project_id=project_id)
    if not node:
        raise HTTPException(status_code=404, detail=_CATEGORY_NOT_FOUND)
    return merged_rows(id, node, project_id)


@router.put("/nodes/{id}/merged")
async def put_merged_qa_route(
    id: str,
    payload: list[MergedQaItem],
    project_id: str = "default",
    base_version: str | None = None,
) -> dict[str, str]:
    def _save() -> None:
        with qa_document_lock:
            try:
                save_merged_rows(
                    id, [item.model_dump() for item in payload], project_id, base_version,
                )
            except MergedSaveError as exc:
                raise HTTPException(status_code=exc.status, detail=exc.detail) from exc

    await asyncio.to_thread(_save)
    schedule_reindex(project_id)
    return {"status": "ok"}


@router.post("/nodes/{id}/entries")
def add_qa_entry_route(
    id: str,
    payload: AddEntryRequest,
    project_id: str = "default",
) -> dict[str, Any]:
    """Mount a document's question on this node, or add a menu-only question."""
    question = payload.question.strip()
    if not question:
        raise HTTPException(status_code=400, detail="題目不可空白")

    source_path = payload.source_path.strip()
    with qa_document_lock:
        node = get_node(id, project_id=project_id)
        if not node:
            raise HTTPException(status_code=404, detail="Node not found")
        # 前後台都用「節點 + 題目文字」定位條目，同節點同文字會分不清。
        if any(entry["question"] == question for entry in node.get("qa_entries", [])):
            raise HTTPException(status_code=400, detail="這個分類已經有相同的題目")

        hidden = payload.hidden
        image_id = None
        if source_path:
            try:
                source_path = normalized_qa_source(source_path, project_id)
                found = read_question(source_path, question, project_id)
            except MergedSaveError as exc:
                raise HTTPException(status_code=exc.status, detail=exc.detail) from exc
            hidden = bool(found.get("hidden", False))
            image_id = extract_image_id(found.get("img") or "") or None

        updated = add_qa_entry_to_node(
            id,
            {
                "question": question,
                "source_path": source_path,
                "hidden": hidden,
                "image_id": image_id,
            },
            project_id=project_id,
        )
    return updated or {}


@router.delete("/nodes/{id}/entries")
def remove_qa_entry_route(
    id: str,
    question: str,
    source_path: str = "",
    project_id: str = "default",
) -> dict[str, Any]:
    """Take a question off this node; the document keeps it and search still finds it."""
    with qa_document_lock:
        if not get_node(id, project_id=project_id):
            raise HTTPException(status_code=404, detail="Node not found")
        node = get_node(id, project_id=project_id)
        if not any(
            entry["question"] == question and (entry.get("source_path") or "") == source_path
            for entry in node.get("qa_entries", [])
        ):
            raise HTTPException(status_code=404, detail="這個分類沒有這個題目")
        updated = remove_qa_entry_from_node(
            id, question, project_id=project_id, source_path=source_path
        )
    return updated or {}


@router.post("/images")
async def upload_image_route(
    file: UploadFile = File(...),
    project_id: str = "default",
) -> dict[str, str]:
    settings = get_settings()
    ext = Path(file.filename or "").suffix.lower()
    if ext not in ALLOWED_QA_IMAGE_SUFFIXES:
        raise HTTPException(status_code=415, detail="不支援的圖片格式")
    file_bytes = await read_upload_limited(file, settings.qa_image_max_bytes)
    validate_qa_image(file_bytes, ext, settings.qa_image_max_side_px)
    image_id = f"{uuid4()}{ext}"

    await asyncio.to_thread(
        save_uploaded_artifact,
        filename=image_id,
        content=file_bytes,
        target_dir="knowledge/.qa_images",
        project_id=project_id,
    )
    # 上傳時就判斷好，回答用到這張圖時只要查表。
    image_kind = await asyncio.to_thread(qa_image_kind, image_id, project_id)

    # 判斷不了不影響上傳；欄位不出現，呼叫端當一般圖片處理。
    return {"image_id": image_id, **({"image_kind": image_kind} if image_kind else {})}


def _resolve_qa_image(id: str, project_id: str) -> Path:
    if not Path(id).name or Path(id).name != id:
        raise HTTPException(status_code=400, detail="Invalid image ID")
    path = resolve_qa_image_path(id, project_id)
    if path is None:
        raise HTTPException(status_code=404, detail="Image not found")
    return path


@router.get("/images/{id}")
def get_image_route(id: str, project_id: str = "default") -> FileResponse:
    path = _resolve_qa_image(id, project_id)
    media_type = QA_IMAGE_MEDIA_TYPES[path.suffix.lower()]
    return FileResponse(path, media_type=media_type)


@router.delete("/images/{id}")
def delete_image_route(id: str, project_id: str = "default") -> dict[str, str]:
    safe_id = Path(id).name
    path = resolve_workspace_artifact(f"knowledge/.qa_images/{safe_id}", project_id)
    if path.exists() and path.is_file():
        path.unlink()
        return {"status": "ok"}
    raise HTTPException(status_code=404, detail="Image not found")


@router.post("/images/cleanup-unused")
def cleanup_images_route(project_id: str = "default") -> dict[str, list[str]]:
    deleted_files = cleanup_unused_images(project_id)
    return {"deleted_files": deleted_files}
