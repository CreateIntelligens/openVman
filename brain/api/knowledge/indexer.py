"""Build the knowledge vector index from workspace documents."""

from __future__ import annotations

import csv
import hashlib
import json
import re
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import Any

from config import get_settings
from infra.db import get_db, get_knowledge_table, normalize_vector, parse_record_metadata
from knowledge.workspace import ensure_workspace_scaffold, iter_indexable_documents
from memory.embedder import get_embedder
from personas.personas import extract_persona_id_from_relative_path

_IMAGE_MARKDOWN_RE = re.compile(r"!\[[^\]]*\]\([^)]*\)")
_QUESTION_RE = re.compile(r"^Q\s*\d*\s*[：: ]?\s*(.+)$", re.IGNORECASE)
_ANSWER_RE = re.compile(r"^A\s*[：: ]?\s*(.+)$", re.IGNORECASE)
_HEADING_RE = re.compile(r"^#{1,6}\s*")


@dataclass(slots=True)
class ChunkSpec:
    text: str
    metadata: dict[str, Any]


def rebuild_knowledge_index() -> dict[str, Any]:
    """Incrementally rebuild the knowledge table from indexable workspace documents."""
    workspace_root = ensure_workspace_scaffold()
    documents = iter_indexable_documents()
    current_fingerprints = {
        path.relative_to(workspace_root).as_posix(): _fingerprint_document(path)
        for path in documents
    }
    state = _load_index_state()
    existing_records = _load_existing_knowledge_records()
    reusable_records = _collect_reusable_records(existing_records, current_fingerprints)
    reusable_paths = {
        str(parse_record_metadata(record).get("path", "")).strip()
        for record in reusable_records
    }
    changed_paths = [
        path
        for path in documents
        if (
            state.get("documents", {}).get(path.relative_to(workspace_root).as_posix())
            != current_fingerprints[path.relative_to(workspace_root).as_posix()]
            or path.relative_to(workspace_root).as_posix() not in reusable_paths
        )
    ]
    removed_paths = sorted(set(state.get("documents", {})) - set(current_fingerprints))

    chunk_specs: list[ChunkSpec] = []
    for path in changed_paths:
        if path.suffix.lower() == ".csv":
            chunk_specs.extend(_extract_csv_chunks(path))
            continue
        chunk_specs.extend(_extract_text_chunks(path))

    records = reusable_records + _build_knowledge_records(chunk_specs)
    if not records:
        records = _build_placeholder_records()
    get_db().create_table("knowledge", data=records, mode="overwrite")
    _save_index_state(current_fingerprints)

    return {
        "status": "ok",
        "workspace_root": str(workspace_root),
        "document_count": len(documents),
        "chunk_count": len(records),
        "changed_documents": len(changed_paths),
        "reused_chunks": len(reusable_records),
        "removed_documents": len(removed_paths),
    }


def _extract_text_chunks(path: Path) -> list[ChunkSpec]:
    content = path.read_text(encoding="utf-8-sig")
    normalized = _normalize_text(content)
    title = path.stem
    relative_path = path.relative_to(ensure_workspace_scaffold()).as_posix()
    fingerprint = _fingerprint_document(path)
    persona_id = extract_persona_id_from_relative_path(relative_path)

    qa_chunks = _extract_markdown_qa_chunks(
        normalized,
        title,
        relative_path,
        fingerprint,
        persona_id,
    )
    if qa_chunks:
        return qa_chunks

    return _chunk_freeform_text(normalized, title, relative_path, fingerprint, persona_id)


def _extract_markdown_qa_chunks(
    content: str,
    title: str,
    relative_path: str,
    fingerprint: str,
    persona_id: str,
) -> list[ChunkSpec]:
    chunks: list[ChunkSpec] = []
    question: str | None = None
    answer_lines: list[str] = []
    chunk_index = 0

    def _flush_qa() -> None:
        nonlocal chunk_index
        if question and answer_lines:
            chunks.append(
                ChunkSpec(
                    text=_format_qa_chunk(title, question, answer_lines),
                    metadata={
                        "path": relative_path,
                        "title": title,
                        "kind": "qa_markdown",
                        "question": question,
                        "persona_id": persona_id,
                        "fingerprint": fingerprint,
                        "chunk_id": f"{relative_path}::{chunk_index}",
                    },
                )
            )
            chunk_index += 1

    for raw_line in content.splitlines():
        line = raw_line.strip()
        if not line:
            continue

        question_match = _QUESTION_RE.match(line)
        if question_match:
            _flush_qa()
            question = question_match.group(1).strip()
            answer_lines = []
            continue

        answer_match = _ANSWER_RE.match(line)
        if answer_match:
            answer_lines.append(answer_match.group(1).strip())
            continue

        if question:
            answer_lines.append(line)

    _flush_qa()
    return chunks


def _chunk_freeform_text(
    content: str,
    title: str,
    relative_path: str,
    fingerprint: str,
    persona_id: str,
) -> list[ChunkSpec]:
    segments = [segment.strip() for segment in content.split("\n\n") if segment.strip()]
    if not segments:
        return []

    chunks: list[ChunkSpec] = []
    buffer: list[str] = []
    current_length = 0
    chunk_index = 0

    def _flush_buffer() -> None:
        nonlocal chunk_index
        if buffer:
            chunk_text = "\n\n".join(buffer)
            chunks.append(
                ChunkSpec(
                    text=f"主題：{title}\n內容：{chunk_text}",
                    metadata={
                        "path": relative_path,
                        "title": title,
                        "kind": "freeform_markdown",
                        "persona_id": persona_id,
                        "fingerprint": fingerprint,
                        "chunk_id": f"{relative_path}::{chunk_index}",
                    },
                )
            )
            chunk_index += 1

    for segment in segments:
        additional = len(segment) + (2 if buffer else 0)
        if buffer and current_length + additional > 700:
            _flush_buffer()
            buffer = [segment]
            current_length = len(segment)
            continue

        buffer.append(segment)
        current_length += additional

    _flush_buffer()
    return chunks


def _extract_csv_chunks(path: Path) -> list[ChunkSpec]:
    chunks: list[ChunkSpec] = []
    relative_path = path.relative_to(ensure_workspace_scaffold()).as_posix()
    title = path.stem
    fingerprint = _fingerprint_document(path)
    persona_id = extract_persona_id_from_relative_path(relative_path)

    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle)
        for row_number, row in enumerate(reader, start=2):
            question = _pick_first(row, "q", "question", "Q", "題目")
            answer = _pick_first(row, "a", "answer", "A", "答案")
            if not question and not answer:
                continue

            chunks.append(
                ChunkSpec(
                    text=_format_qa_chunk(title, question or "未命名問題", [answer or ""]),
                    metadata={
                        "path": relative_path,
                        "title": title,
                        "kind": "qa_csv",
                        "question": question,
                        "persona_id": persona_id,
                        "row_number": row_number,
                        "row_index": _pick_first(row, "index", "id"),
                        "image": _pick_first(row, "img", "image"),
                        "fingerprint": fingerprint,
                        "chunk_id": f"{relative_path}::{row_number}",
                    },
                )
            )

    return chunks


def _build_knowledge_records(chunk_specs: list[ChunkSpec]) -> list[dict[str, Any]]:
    if not chunk_specs:
        return []

    texts = [chunk.text for chunk in chunk_specs]
    vectors = get_embedder().encode(texts)
    records: list[dict[str, Any]] = []

    for chunk, vector in zip(chunk_specs, vectors):
        records.append(
            {
                "text": chunk.text,
                "vector": normalize_vector(vector),
                "source": "workspace",
                "date": date.today().isoformat(),
                "metadata": json.dumps(chunk.metadata, ensure_ascii=False),
            }
        )

    return records


def _build_placeholder_records() -> list[dict[str, Any]]:
    return [
        {
            "text": "知識庫目前沒有內容。",
            "vector": normalize_vector(get_embedder().encode(["知識庫目前沒有內容。"])[0]),
            "source": "system",
            "date": date.today().isoformat(),
            "metadata": json.dumps({"placeholder": True}, ensure_ascii=False),
        }
    ]


def _normalize_text(content: str) -> str:
    lines: list[str] = []
    for raw_line in content.splitlines():
        line = _IMAGE_MARKDOWN_RE.sub("", raw_line).strip()
        line = _HEADING_RE.sub("", line)
        lines.append(line)
    return "\n".join(lines).strip()


def _format_qa_chunk(title: str, question: str, answer_lines: list[str]) -> str:
    answer = "\n".join(line.strip() for line in answer_lines if line.strip())
    return f"主題：{title}\n問題：{question.strip()}\n回答：{answer}"


def _pick_first(row: dict[str, Any], *keys: str) -> str:
    for key in keys:
        value = row.get(key)
        if value is not None:
            text = str(value).strip()
            if text:
                return text
    return ""


def _fingerprint_document(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _load_existing_knowledge_records() -> list[dict[str, Any]]:
    db = get_db()
    if "knowledge" not in db.table_names():
        return []
    return get_knowledge_table().to_arrow().to_pylist()


def _collect_reusable_records(
    records: list[dict[str, Any]],
    current_fingerprints: dict[str, str],
) -> list[dict[str, Any]]:
    reusable: list[dict[str, Any]] = []
    for record in records:
        metadata = parse_record_metadata(record)
        if metadata.get("placeholder"):
            continue
        path = str(metadata.get("path", "")).strip()
        fingerprint = str(metadata.get("fingerprint", "")).strip()
        if not path or not fingerprint:
            continue
        if current_fingerprints.get(path) != fingerprint:
            continue
        reusable.append(record)
    return reusable


def _load_index_state() -> dict[str, Any]:
    cfg = get_settings()
    path = Path(cfg.knowledge_index_state_resolved_path)
    if not path.exists():
        return {}
    try:
        parsed = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return {}
    return parsed if isinstance(parsed, dict) else {}


def _save_index_state(documents: dict[str, str]) -> None:
    cfg = get_settings()
    path = Path(cfg.knowledge_index_state_resolved_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(
            {
                "updated_at": date.today().isoformat(),
                "documents": documents,
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )
