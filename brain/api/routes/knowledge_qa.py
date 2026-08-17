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

from knowledge.doc_meta import upsert_document_meta
from knowledge.knowledge_admin import (
    delete_workspace_document,
    resolve_workspace_artifact,
    resolve_workspace_document,
    save_uploaded_artifact,
    save_workspace_document,
)
from knowledge.qa_csv import (
    extract_image_id,
    parse_qa_csv,
    parse_qa_markdown,
    qa_markdown_block,
    serialize_qa_csv,
)
from knowledge.qa_nodes import (
    adopt_orphan_qa_sources,
    cleanup_unused_images,
    create_node,
    create_node_for_source,
    delete_node,
    get_node,
    get_node_tree,
    is_source_referenced,
    move_node,
    reorder_node,
    sync_entries_for_source,
    update_node,
)

from routes.knowledge import schedule_reindex
from safety.internal_auth import require_internal_token

logger = logging.getLogger(__name__)

router = APIRouter(
    prefix="/brain/knowledge/qa",
    tags=["Knowledge QA"],
    dependencies=[Depends(require_internal_token)],
)

_QA_IMAGE_MEDIA_TYPES = {
    ".avif": "image/avif",
    ".bmp": "image/bmp",
    ".gif": "image/gif",
    ".ico": "image/vnd.microsoft.icon",
    ".jpeg": "image/jpeg",
    ".jpg": "image/jpeg",
    ".png": "image/png",
    ".webp": "image/webp",
}
_ALLOWED_QA_IMAGE_SUFFIXES = frozenset(_QA_IMAGE_MEDIA_TYPES)


class CreateNodeRequest(BaseModel):
    node_id: str
    label: str
    parent_ids: list[str] | None = None
    child_ids: list[str] | None = None
    order: float | None = 1.0
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
    source_file: str
    hidden: bool | None = False


def parse_qa_markdown_with_metadata(content: str) -> list[dict[str, Any]]:
    """Parse qa markdown file into a list of dict containing q, a, img, url."""
    return parse_qa_markdown(content)


@router.get("/nodes")
def list_qa_nodes_route(project_id: str = "default") -> list[dict[str, Any]]:
    # 無掛載模型的自癒遷移：未被任何節點引用的 QA 文件在讀取時補建節點。
    adopted = adopt_orphan_qa_sources(project_id)
    if adopted:
        logger.info("adopted orphan qa sources into tree: %s", adopted)
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

        if is_source_referenced(path, project_id):
            raise HTTPException(status_code=400, detail="此 QA 文件已在問答樹中")

        try:
            doc_path = resolve_workspace_document(path, project_id)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

        if not doc_path.exists():
            raise HTTPException(status_code=404, detail="找不到指定文件")

        content = doc_path.read_text(encoding="utf-8")
        parsed = parse_qa_markdown(content)
        if not parsed:
            raise HTTPException(status_code=400, detail="無效的 QA 文件格式")

        parent_ids = None
        if payload.parent_id is not None:
            parent_node = get_node(payload.parent_id, project_id=project_id)
            if not parent_node:
                raise HTTPException(status_code=400, detail="指定之父節點不存在")
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
            raise HTTPException(status_code=404, detail="找不到指定節點")

        try:
            dragged_path = resolve_workspace_document(path, project_id)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

        if not dragged_path.exists():
            raise HTTPException(status_code=404, detail="找不到指定文件")

        dragged_content = dragged_path.read_text(encoding="utf-8")
        dragged_items = parse_qa_markdown(dragged_content)
        if not dragged_items:
            raise HTTPException(status_code=400, detail="無效的 QA 文件格式")

        qa_entries = node.get("qa_entries", [])
        target_path = next((entry["source_path"] for entry in qa_entries if entry.get("source_path")), "")

        if not target_path:
            target_path = f"knowledge/qa/{id}.md"

        if path == target_path:
            raise HTTPException(status_code=400, detail="此文件已是該節點的內容")

        try:
            target_file = resolve_workspace_document(target_path, project_id)
            if target_file.exists():
                target_content = target_file.read_text(encoding="utf-8")
                target_items = parse_qa_markdown(target_content)
            else:
                target_items = []
        except Exception:
            target_items = []

        target_qa_dict = {item["q"].strip(): item for item in target_items}

        added_count = 0
        new_qa_entries = list(qa_entries)

        for item in dragged_items:
            q = item["q"].strip()
            if q in target_qa_dict:
                continue

            target_items.append(item)
            target_qa_dict[q] = item
            added_count += 1

            image_id = extract_image_id(item.get("img") or "")
            new_qa_entries.append({
                "question": q,
                "source_path": target_path,
                "hidden": bool(item.get("hidden", False)),
                "image_id": image_id or None,
            })

        if added_count > 0:
            blocks = []
            for item in target_items:
                blocks.append(
                    qa_markdown_block(
                        item["q"],
                        item["a"],
                        item.get("img") or "",
                        item.get("url") or "",
                        bool(item.get("hidden", False)),
                    )
                )
            new_content = "\n\n".join(blocks)
            save_workspace_document(target_path, new_content, project_id)
            upsert_document_meta(target_path, project_id, source_type="qa")

            update_node(id, {"qa_entries": new_qa_entries}, project_id=project_id)

        delete_workspace_document(path, project_id)
        # 被吸收的文件若原屬其他節點，清掉那些節點的懸空 entries
        sync_entries_for_source(path, project_id)
        return {"added": added_count}

    result = await asyncio.to_thread(_ingest)
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
            raise HTTPException(status_code=404, detail="Node not found")
        return node
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.delete("/nodes/{id}")
async def delete_qa_node_route(id: str, project_id: str = "default") -> dict[str, Any]:
    # 1 節點 = 1 來源：刪除節點時，其專屬 QA 文件一併刪除；
    # 仍被其他節點引用（舊資料的多對多殘留）者保留。
    def _delete() -> list[str]:
        node = get_node(id, project_id=project_id)
        if node is None:
            raise HTTPException(status_code=404, detail="Node not found")
        source_paths = {
            entry["source_path"]
            for entry in node.get("qa_entries", [])
            if entry.get("source_path")
        }

        if not delete_node(id, project_id=project_id):
            raise HTTPException(status_code=404, detail="Node not found")

        removed: list[str] = []
        for path in sorted(source_paths):
            if is_source_referenced(path, project_id):
                continue
            try:
                delete_workspace_document(path, project_id)
                removed.append(path)
            except FileNotFoundError:
                pass
        return removed

    removed_docs = await asyncio.to_thread(_delete)
    if removed_docs:
        schedule_reindex(project_id)
    return {"status": "ok", "removed_docs": removed_docs}


@router.post("/nodes/{id}/move")
def move_qa_node_route(
    id: str,
    payload: MoveNodeRequest,
    project_id: str = "default",
) -> dict[str, Any]:
    try:
        node = move_node(id, payload.new_parent_ids, project_id=project_id)
        if node is None:
            raise HTTPException(status_code=404, detail="Node not found")
        return node
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.post("/nodes/{id}/reorder")
def reorder_qa_node_route(
    id: str,
    payload: ReorderNodeRequest,
    project_id: str = "default",
) -> dict[str, Any]:
    try:
        node = reorder_node(id, payload.sibling_ids_ordered, project_id=project_id)
        if node is None:
            raise HTTPException(status_code=404, detail="Node not found")
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
        raise HTTPException(status_code=404, detail="Node not found")

    qa_entries = node.get("qa_entries", [])

    by_path: defaultdict[str, list[dict[str, Any]]] = defaultdict(list)
    for entry in qa_entries:
        by_path[entry["source_path"]].append(entry)

    merged_items: list[dict[str, Any]] = []

    for source_path, entries in by_path.items():
        qa_dict = {}
        try:
            doc_path = resolve_workspace_document(source_path, project_id)
            if doc_path.exists():
                if doc_path.suffix.lower() == ".csv":
                    parsed_qas = parse_qa_csv(doc_path.read_bytes())
                else:
                    content = doc_path.read_text(encoding="utf-8")
                    parsed_qas = parse_qa_markdown_with_metadata(content)
                qa_dict = {item["q"]: item for item in parsed_qas}
        except Exception:
            pass

        for entry in entries:
            q = entry["question"]
            item_detail = qa_dict.get(q, {})
            merged_items.append(
                {
                    "q": q,
                    "a": item_detail.get("a", ""),
                    "img": entry.get("image_id") or item_detail.get("img") or "",
                    "url": item_detail.get("url") or "",
                    "source_file": source_path,
                    "hidden": entry.get("hidden", False),
                }
            )

    for idx, item in enumerate(merged_items, start=1):
        item["index"] = str(idx)

    return merged_items


@router.put("/nodes/{id}/merged")
async def put_merged_qa_route(
    id: str,
    payload: list[MergedQaItem],
    project_id: str = "default",
) -> dict[str, str]:
    def _save() -> None:
        node = get_node(id, project_id=project_id)
        if not node:
            raise HTTPException(status_code=404, detail="Node not found")

        by_file: defaultdict[str, list[MergedQaItem]] = defaultdict(list)
        for item in payload:
            by_file[item.source_file].append(item)

        new_qa_entries: list[dict[str, Any]] = []
        existing_hidden = {e["question"]: e.get("hidden", False) for e in node.get("qa_entries", [])}

        for source_file, items in by_file.items():
            blocks: list[str] = []
            csv_entries: list[dict[str, Any]] = []
            for item in items:
                q = item.q.strip()
                a = item.a.strip()
                img = item.img.strip() if item.img else ""
                url = item.url.strip() if item.url else ""
                img_val = extract_image_id(img)

                hidden = item.hidden if item.hidden is not None else existing_hidden.get(q, False)
                blocks.append(qa_markdown_block(q, a, img_val, url, hidden))
                csv_entries.append(
                    {
                        "index": item.index,
                        "q": q,
                        "a": a,
                        "img": img_val,
                        "url": url,
                        "hidden": hidden,
                    }
                )
                new_qa_entries.append(
                    {
                        "question": q,
                        "source_path": source_file,
                        "hidden": hidden,
                        "image_id": img_val if img_val else None,
                    }
                )

            if Path(source_file).suffix.lower() == ".csv":
                content = serialize_qa_csv(csv_entries)
            else:
                content = "\n\n".join(blocks)
            save_workspace_document(source_file, content, project_id)
            upsert_document_meta(source_file, project_id, source_type="qa")

        update_node(id, {"qa_entries": new_qa_entries}, project_id=project_id)

    await asyncio.to_thread(_save)
    schedule_reindex(project_id)
    return {"status": "ok"}


@router.post("/images")
async def upload_image_route(
    file: UploadFile = File(...),
    project_id: str = "default",
) -> dict[str, str]:
    file_bytes = await file.read()

    ext = Path(file.filename).suffix.lower()
    if ext not in _ALLOWED_QA_IMAGE_SUFFIXES:
        raise HTTPException(status_code=400, detail="Unsupported image type")
    image_id = f"{uuid4()}{ext}"

    await asyncio.to_thread(
        save_uploaded_artifact,
        filename=image_id,
        content=file_bytes,
        target_dir="knowledge/.qa_images",
        project_id=project_id,
    )

    return {"image_id": image_id}


def _resolve_qa_image(id: str, project_id: str) -> Path:
    safe_id = Path(id).name
    if not safe_id or safe_id != id:
        raise HTTPException(status_code=400, detail="Invalid image ID")

    images_dir = resolve_workspace_artifact("knowledge/.qa_images", project_id)
    exact_path = resolve_workspace_artifact(
        f"knowledge/.qa_images/{safe_id}", project_id
    )
    if (
        exact_path.is_file()
        and exact_path.suffix.lower() in _ALLOWED_QA_IMAGE_SUFFIXES
    ):
        return exact_path

    if Path(safe_id).suffix:
        raise HTTPException(status_code=404, detail="Image not found")

    # 匯入來源的圖片名稱可能在括號前含空白（例如 PRP (1).jpg），
    # 但 CSV 的圖片 ID 是 PRP(1)。比對時忽略空白，避免同一資產因命名格式而 404。
    normalized_id = re.sub(r"\s+", "", safe_id).casefold()
    candidates = sorted(images_dir.iterdir()) if images_dir.is_dir() else []
    for candidate in candidates:
        if (
            candidate.is_file()
            and re.sub(r"\s+", "", candidate.stem).casefold() == normalized_id
            and candidate.suffix.lower() in _ALLOWED_QA_IMAGE_SUFFIXES
        ):
            return candidate
    raise HTTPException(status_code=404, detail="Image not found")


@router.get("/images/{id}")
def get_image_route(id: str, project_id: str = "default") -> FileResponse:
    path = _resolve_qa_image(id, project_id)
    media_type = _QA_IMAGE_MEDIA_TYPES[path.suffix.lower()]
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
