from __future__ import annotations

import asyncio
from collections import defaultdict
import logging
from pathlib import Path
from typing import Any
from uuid import uuid4

from fastapi import APIRouter, File, HTTPException, UploadFile
from pydantic import BaseModel

import knowledge.indexer
from knowledge.doc_meta import get_document_meta, upsert_document_meta
from knowledge.knowledge_admin import (
    resolve_workspace_artifact,
    resolve_workspace_document,
    save_uploaded_artifact,
    save_workspace_document,
)
from knowledge.qa_csv import (
    extract_image_id,
    parse_qa_markdown,
    qa_markdown_block,
)
from knowledge.qa_nodes import (
    add_qa_entries_to_node,
    cleanup_unused_images,
    create_node,
    delete_node,
    get_node,
    get_node_tree,
    move_node,
    reorder_node,
    update_node,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/brain/knowledge/qa", tags=["Knowledge QA"])


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
    return get_node_tree(project_id)


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
def delete_qa_node_route(id: str, project_id: str = "default") -> dict[str, str]:
    # Nodes own structure only: deleting one drops its references, never the
    # underlying QA documents (those belong to the documents workspace).
    success = delete_node(id, project_id=project_id)
    if not success:
        raise HTTPException(status_code=404, detail="Node not found")
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


@router.post("/nodes/{id}/attach-source")
def attach_source_route(
    id: str,
    payload: SourcePathRequest,
    project_id: str = "default",
) -> dict[str, Any]:
    node = get_node(id, project_id=project_id)
    if node is None:
        raise HTTPException(status_code=404, detail="Node not found")

    if get_document_meta(payload.path, project_id).get("source_type") != "qa":
        raise HTTPException(status_code=400, detail="僅能掛載 QA 來源文件")

    try:
        doc_path = resolve_workspace_document(payload.path, project_id)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    if not doc_path.exists():
        raise HTTPException(status_code=404, detail="找不到指定文件")

    parsed_entries = parse_qa_markdown(doc_path.read_text(encoding="utf-8"))
    existing_questions = {entry["question"] for entry in node.get("qa_entries", [])}
    new_entries: list[dict[str, Any]] = []
    for parsed in parsed_entries:
        question = parsed["q"].strip()
        if not question or question in existing_questions:
            continue
        image_id = extract_image_id(parsed.get("img") or "")
        new_entries.append(
            {
                "question": question,
                "source_path": payload.path,
                "hidden": bool(parsed.get("hidden", False)),
                "image_id": image_id or None,
            }
        )
        existing_questions.add(question)

    if new_entries:
        add_qa_entries_to_node(id, new_entries, project_id=project_id)
    return {"status": "ok", "added": len(new_entries)}


@router.post("/nodes/{id}/detach-source")
def detach_source_route(
    id: str,
    payload: SourcePathRequest,
    project_id: str = "default",
) -> dict[str, Any]:
    node = get_node(id, project_id=project_id)
    if node is None:
        raise HTTPException(status_code=404, detail="Node not found")

    entries = node.get("qa_entries", [])
    remaining = [entry for entry in entries if entry.get("source_path") != payload.path]
    if len(remaining) != len(entries):
        update_node(id, {"qa_entries": remaining}, project_id=project_id)
    return {"status": "ok", "removed": len(entries) - len(remaining)}


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
        try:
            doc_path = resolve_workspace_document(source_path, project_id)
            if doc_path.exists():
                content = doc_path.read_text(encoding="utf-8")
                parsed_qas = parse_qa_markdown_with_metadata(content)
                qa_dict = {item["q"]: item for item in parsed_qas}

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
            else:
                raise FileNotFoundError()
        except Exception:
            for entry in entries:
                merged_items.append(
                    {
                        "q": entry["question"],
                        "a": "",
                        "img": entry.get("image_id") or "",
                        "url": "",
                        "source_file": source_path,
                        "hidden": entry.get("hidden", False),
                    }
                )

    for idx, item in enumerate(merged_items, start=1):
        item["index"] = str(idx)

    return merged_items


@router.put("/nodes/{id}/merged")
def put_merged_qa_route(
    id: str,
    payload: list[MergedQaItem],
    project_id: str = "default",
) -> dict[str, str]:
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
        for item in items:
            q = item.q.strip()
            a = item.a.strip()
            img = item.img.strip() if item.img else ""
            url = item.url.strip() if item.url else ""
            img_val = extract_image_id(img)

            hidden = item.hidden if item.hidden is not None else existing_hidden.get(q, False)
            blocks.append(qa_markdown_block(q, a, img_val, url, hidden))
            new_qa_entries.append(
                {
                    "question": q,
                    "source_path": source_file,
                    "hidden": hidden,
                    "image_id": img_val if img_val else None,
                }
            )

        markdown_content = "\n\n".join(blocks)
        save_workspace_document(source_file, markdown_content, project_id)
        upsert_document_meta(source_file, project_id, source_type="qa")

    update_node(id, {"qa_entries": new_qa_entries}, project_id=project_id)
    knowledge.indexer.rebuild_knowledge_index(project_id)
    return {"status": "ok"}


@router.post("/images")
async def upload_image_route(
    file: UploadFile = File(...),
    project_id: str = "default",
) -> dict[str, str]:
    file_bytes = await file.read()

    ext = Path(file.filename).suffix.lower()
    image_id = f"{uuid4()}{ext}"

    await asyncio.to_thread(
        save_uploaded_artifact,
        filename=image_id,
        content=file_bytes,
        target_dir="knowledge/.qa_images",
        project_id=project_id,
    )

    return {"image_id": image_id}


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
