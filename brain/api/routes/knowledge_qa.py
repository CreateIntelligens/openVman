from __future__ import annotations

import asyncio
from collections import defaultdict
import json
import logging
from pathlib import Path
from typing import Any
from uuid import uuid4

from fastapi import APIRouter, File, HTTPException, UploadFile
from pydantic import BaseModel

import knowledge.indexer
from knowledge.doc_meta import upsert_document_meta
from knowledge.knowledge_admin import (
    resolve_workspace_artifact,
    resolve_workspace_document,
    save_uploaded_artifact,
    save_uploaded_document,
    save_workspace_document,
)
from knowledge.qa_csv import (
    _parse_csv_rows,
    extract_hidden_from_csv,
    normalize_qa_csv_rows,
    parse_qa_markdown,
    split_qa_csv_by_image,
    validate_supported_qa_csv,
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


class ManualQaItem(BaseModel):
    q: str
    a: str
    img: str | None = ""
    url: str | None = ""


class MergedQaItem(BaseModel):
    index: str | None = ""
    q: str
    a: str
    img: str | None = ""
    url: str | None = ""
    source_file: str
    hidden: bool | None = False


def _extract_image_id(raw: str) -> str:
    value = (raw or "").strip()
    if "=" in value:
        value = value.split("=")[-1].strip()
    if "/" in value:
        value = value.split("/")[-1].strip()
    return value


def _qa_markdown_block(question: str, answer: str, img: str = "", url: str = "") -> str:
    metadata = {"img": _extract_image_id(img), "url": url}
    metadata_str = json.dumps(metadata, ensure_ascii=False)
    return f"## {question}\n\n{answer}\n<!-- qa_metadata: {metadata_str} -->"


def parse_qa_markdown_with_metadata(content: str) -> list[dict[str, Any]]:
    """Parse qa markdown file into a list of dict containing q, a, img, url."""
    return parse_qa_markdown(content)


def convert_csv_to_qa_markdown(csv_bytes: bytes) -> str:
    """Convert normalized QA CSV bytes to markdown with HTML comment metadata."""
    parsed = _parse_csv_rows(csv_bytes)
    if not parsed:
        return ""
    _, rows = parsed
    blocks = []
    for row in rows:
        q = (row.get("q") or "").strip()
        a = (row.get("a") or "").strip()
        img = (row.get("img") or "").strip()
        url = (row.get("url") or "").strip()
        if not q and not a:
            continue
        blocks.append(_qa_markdown_block(q or "未命名問題", a, img, url))
    return "\n\n".join(blocks)


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


@router.post("/nodes/{id}/upload-csv")
async def upload_csv_route(
    id: str,
    file: UploadFile = File(...),
    project_id: str = "default",
) -> dict[str, str]:
    node = await asyncio.to_thread(get_node, id, project_id=project_id)
    if not node:
        raise HTTPException(status_code=404, detail="Node not found")

    file_bytes = await file.read()

    try:
        await asyncio.to_thread(validate_supported_qa_csv, file_bytes)
    except Exception as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    normalized_bytes = await asyncio.to_thread(normalize_qa_csv_rows, file_bytes)
    if normalized_bytes is None:
        raise HTTPException(status_code=400, detail="Failed to normalize CSV rows")

    splits = await asyncio.to_thread(split_qa_csv_by_image, normalized_bytes, file.filename)
    if not splits:
        splits = [(file.filename, normalized_bytes)]

    hidden_questions = set(await asyncio.to_thread(extract_hidden_from_csv, file_bytes))

    for fn, csv_content in splits:
        fn_md = Path(fn).with_suffix(".md").name
        relative_doc_path = f"knowledge/{fn_md}"

        # Reload so this split sees entries added by prior splits in the same
        # upload; `existing_questions` is then seeded from the post-cleanup
        # entries directly, avoiding a second full-file read of the node store.
        node = await asyncio.to_thread(get_node, id, project_id=project_id)
        existing_questions: set[str] = set()
        if node:
            clean_entries = [
                entry
                for entry in node.get("qa_entries", [])
                if entry.get("source_path") != relative_doc_path
            ]
            await asyncio.to_thread(
                update_node,
                id,
                {"qa_entries": clean_entries},
                project_id=project_id,
            )
            existing_questions = {e["question"] for e in clean_entries}

        markdown_text = convert_csv_to_qa_markdown(csv_content)
        await asyncio.to_thread(
            save_uploaded_document,
            filename=fn_md,
            content=markdown_text.encode("utf-8"),
            target_dir="knowledge",
            project_id=project_id,
        )
        await asyncio.to_thread(upsert_document_meta, relative_doc_path, project_id, source_type="qa")

        parsed = await asyncio.to_thread(_parse_csv_rows, csv_content)
        if parsed:
            _, rows = parsed
            new_entries_to_add: list[dict[str, Any]] = []

            for row in rows:
                q = (row.get("q") or "").strip()
                if not q:
                    continue
                if q in existing_questions:
                    continue

                img_val = _extract_image_id(row.get("img") or "")
                is_hidden = q in hidden_questions

                qa_entry = {
                    "question": q,
                    "source_path": relative_doc_path,
                    "hidden": is_hidden,
                    "image_id": img_val if img_val else None,
                }
                new_entries_to_add.append(qa_entry)
                existing_questions.add(q)

            if new_entries_to_add:
                await asyncio.to_thread(add_qa_entries_to_node, id, new_entries_to_add, project_id=project_id)

    await asyncio.to_thread(knowledge.indexer.rebuild_knowledge_index, project_id)
    return {"status": "ok"}


@router.post("/nodes/{id}/manual")
def manual_qa_route(
    id: str,
    payload: ManualQaItem | list[ManualQaItem],
    project_id: str = "default",
) -> dict[str, str]:
    node = get_node(id, project_id=project_id)
    if not node:
        raise HTTPException(status_code=404, detail="Node not found")

    items = [payload] if not isinstance(payload, list) else payload

    manual_filename = f"manual_{id}.md"
    relative_doc_path = f"knowledge/{manual_filename}"

    existing_items: list[dict[str, Any]] = []
    try:
        doc_path = resolve_workspace_document(relative_doc_path, project_id)
        if doc_path.exists():
            content = doc_path.read_text(encoding="utf-8")
            existing_items = parse_qa_markdown_with_metadata(content)
    except Exception:
        pass

    existing_questions_in_node = {e["question"] for e in node.get("qa_entries", [])}
    existing_questions_in_doc = {item["q"] for item in existing_items}

    new_added = False
    new_entries_to_add: list[dict[str, Any]] = []

    for item in items:
        q = item.q.strip()
        a = item.a.strip()
        img = item.img.strip() if item.img else ""
        url = item.url.strip() if item.url else ""
        if not q:
            continue

        if q in existing_questions_in_node:
            continue

        img_val = _extract_image_id(img)
        if q not in existing_questions_in_doc:
            existing_items.append({"q": q, "a": a, "img": img_val, "url": url})
            existing_questions_in_doc.add(q)

        qa_entry = {
            "question": q,
            "source_path": relative_doc_path,
            "hidden": False,
            "image_id": img_val if img_val else None,
        }
        new_entries_to_add.append(qa_entry)
        existing_questions_in_node.add(q)
        new_added = True

    if new_added:
        add_qa_entries_to_node(id, new_entries_to_add, project_id=project_id)

    if new_added or not existing_items:
        blocks = [
            _qa_markdown_block(item["q"], item["a"], item["img"], item["url"])
            for item in existing_items
        ]
        markdown_content = "\n\n".join(blocks)

        save_uploaded_document(
            filename=manual_filename,
            content=markdown_content.encode("utf-8"),
            target_dir="knowledge",
            project_id=project_id,
        )
        upsert_document_meta(relative_doc_path, project_id, source_type="qa")

    knowledge.indexer.rebuild_knowledge_index(project_id)
    return {"status": "ok"}


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
            img_val = _extract_image_id(img)

            blocks.append(_qa_markdown_block(q, a, img_val, url))
            new_qa_entries.append(
                {
                    "question": q,
                    "source_path": source_file,
                    "hidden": item.hidden if item.hidden is not None else existing_hidden.get(q, False),
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
