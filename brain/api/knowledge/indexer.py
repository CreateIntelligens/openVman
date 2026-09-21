"""Build the knowledge vector index from workspace documents."""

from __future__ import annotations

import asyncio
import csv
from dataclasses import dataclass
from datetime import date
import hashlib
import json
import math
from pathlib import Path
import re
from typing import Any

from config import get_settings
from infra.db import (
    ensure_fts_index,
    get_db,
    get_knowledge_table,
    normalize_vector,
    parse_record_metadata,
    resolve_vector_table_name,
)
from infra.pipeline import CheckpointStore, PipelineConfig, run_pipeline
from infra.project_context import resolve_embedding_index_state_path
from knowledge.chunking import (
    ChunkSpec,
    _extract_csv_chunks,
    _extract_markdown_qa_chunks,
    _extract_text_chunks,
    _format_qa_embed_text,
)
from knowledge.qa_csv import extract_image_id
from knowledge.workspace import (
    ALLOWED_CODE_SUFFIXES,
    ensure_workspace_scaffold,
    iter_indexable_documents,
)
from memory.embedder import get_embedder
from personas.personas import extract_persona_id_from_relative_path

# 索引欄位或切塊規格改變時升版，讓內容未變的既有文件也會重建一次。
_KNOWLEDGE_INDEX_FORMAT_VERSION = "2"





def load_index_state(project_id: str = "default") -> dict[str, str]:
    """回傳 { relative_path: fingerprint } 映射。"""
    state = _load_index_state(project_id)
    return state.get("documents", {})


def fingerprint_document(path: Path) -> str:
    """回傳文件的 SHA-256 fingerprint。"""
    return _fingerprint_document(path)


def has_stale_documents(project_id: str = "default") -> bool:
    """Return True if the vector index is out of date with the workspace.

    Compares the current indexable documents' fingerprints against the saved
    index state. Any added, changed, or removed document makes the index stale.
    Used to decide whether a graph rebuild must first reindex so the graph is
    never built on top of an embedding index that lags the files.
    """
    workspace_root = ensure_workspace_scaffold(project_id)
    current = {
        path.relative_to(workspace_root).as_posix(): _fingerprint_document(path)
        for path in iter_indexable_documents(project_id)
    }
    previous = _load_index_state(project_id).get("documents", {})
    return current != previous


def rebuild_knowledge_index(project_id: str = "default") -> dict[str, Any]:
    """Incrementally rebuild the knowledge table from indexable workspace documents."""
    workspace_root = ensure_workspace_scaffold(project_id)
    store = CheckpointStore(resolve_embedding_index_state_path(project_id))
    live_fingerprints = _current_document_fingerprints(project_id, workspace_root)
    table_exists = _knowledge_table_exists(project_id)
    if table_exists:
        _ensure_knowledge_table_schema(project_id)

    stats = asyncio.run(
        run_pipeline(
            _IndexItemSource(project_id, workspace_root, store, force_all=not table_exists),
            _IndexWorker(workspace_root),
            _IndexSink(project_id, workspace_root, store),
            PipelineConfig(batch_size=100, concurrency=2),
        )
    )
    removed_paths = _prune_removed_documents(project_id, store, set(live_fingerprints))
    if live_fingerprints:
        _delete_placeholder_record(project_id)
    elif _safe_knowledge_chunk_count(project_id) == 0:
        _replace_knowledge_table(project_id, _build_placeholder_records())

    ensure_fts_index("knowledge", project_id)
    chunk_count = _safe_knowledge_chunk_count(project_id)
    if chunk_count is None or (chunk_count == 0 and stats.results > 0):
        chunk_count = max(stats.results, len(live_fingerprints))

    return {
        "status": "ok",
        "workspace_root": str(workspace_root),
        "document_count": len(live_fingerprints),
        "chunk_count": chunk_count,
        "changed_documents": stats.items,
        "reused_chunks": max(chunk_count - stats.results, 0),
        "removed_documents": len(removed_paths),
    }


def _current_document_fingerprints(project_id: str, workspace_root: Path) -> dict[str, str]:
    return {
        path.relative_to(workspace_root).as_posix(): _fingerprint_document(path)
        for path in iter_indexable_documents(project_id)
    }


class _IndexItemSource:
    def __init__(
        self,
        project_id: str,
        workspace_root: Path,
        store: CheckpointStore,
        *,
        force_all: bool = False,
    ) -> None:
        self._project_id = project_id
        self._workspace_root = workspace_root
        self._store = store
        self._force_all = force_all

    def pending(self):
        done = {} if self._force_all else self._store.load()
        for path in iter_indexable_documents(self._project_id):
            relative_path = path.relative_to(self._workspace_root).as_posix()
            try:
                fingerprint = _fingerprint_document(path)
            except FileNotFoundError:
                continue
            if self._force_all or done.get(relative_path) != fingerprint:
                yield path


class _IndexWorker:
    def __init__(self, workspace_root: Path) -> None:
        self._workspace_root = workspace_root

    async def process_batch(self, paths: list[Path]) -> list[dict[str, Any]]:
        def _work() -> list[dict[str, Any]]:
            chunk_specs: list[ChunkSpec] = []
            for path in paths:
                try:
                    if path.suffix.lower() == ".csv":
                        chunk_specs.extend(_extract_csv_chunks(path, self._workspace_root))
                    else:
                        chunk_specs.extend(_extract_text_chunks(path, self._workspace_root))
                except FileNotFoundError:
                    continue
            return _build_knowledge_records(chunk_specs)

        return _work()


class _IndexSink:
    def __init__(
        self,
        project_id: str,
        workspace_root: Path,
        store: CheckpointStore,
    ) -> None:
        self._project_id = project_id
        self._workspace_root = workspace_root
        self._store = store

    def flush(self, records: list[dict[str, Any]]) -> None:
        if not records:
            return
        table, created = _ensure_knowledge_table(self._project_id, records)
        if created:
            return
        table.merge_insert("chunk_id").when_matched_update_all().when_not_matched_insert_all().execute(records)

    def commit_checkpoint(self, paths: list[Path]) -> None:
        updates = {}
        for path in paths:
            try:
                updates[path.relative_to(self._workspace_root).as_posix()] = _fingerprint_document(path)
            except FileNotFoundError:
                pass
        self._store.commit(updates)


def _write_identity() -> str:
    return get_settings().resolved_embedding_write_identity


def _knowledge_table_name(identity: str | None = None) -> str:
    return resolve_vector_table_name("knowledge", identity or _write_identity())


def _knowledge_table_exists(project_id: str) -> bool:
    return _knowledge_table_name() in set(get_db(project_id).table_names())


def _open_knowledge_table(project_id: str):
    return get_db(project_id).open_table(_knowledge_table_name())


def _replace_knowledge_table(project_id: str, records: list[dict[str, Any]]):
    return get_db(project_id).create_table(
        _knowledge_table_name(),
        data=records,
        mode="overwrite",
    )


def _ensure_knowledge_table(
    project_id: str,
    initial_records: list[dict[str, Any]],
):
    if not _knowledge_table_exists(project_id):
        table = _replace_knowledge_table(project_id, initial_records)
        if table is None and _knowledge_table_exists(project_id):
            table = _open_knowledge_table(project_id)
        return table, True
    _ensure_knowledge_table_schema(project_id)
    table = _open_knowledge_table(project_id)
    return table, False


def _ensure_knowledge_table_schema(project_id: str) -> None:
    table = _open_knowledge_table(project_id)
    schema = getattr(table, "schema", None)
    names = set(getattr(schema, "names", []) or [])
    if names and {"path", "chunk_id"}.issubset(names):
        return

    records = []
    for record in table.to_arrow().to_pylist():
        metadata = parse_record_metadata(record)
        records.append(
            {
                **record,
                "path": str(record.get("path") or metadata.get("path", "")),
                "chunk_id": str(record.get("chunk_id") or metadata.get("chunk_id", "")),
            }
        )
    _replace_knowledge_table(project_id, records or _build_placeholder_records())


def _safe_knowledge_chunk_count(project_id: str) -> int | None:
    if not _knowledge_table_exists(project_id):
        return 0
    try:
        count = _open_knowledge_table(project_id).count_rows()
    except Exception:
        return None
    return count if isinstance(count, int) else None


def _lance_string(value: str) -> str:
    return "'" + value.replace("'", "''") + "'"


def _delete_records_where(project_id: str, field: str, value: str) -> None:
    if not _knowledge_table_exists(project_id):
        return
    _open_knowledge_table(project_id).delete(f"{field} = {_lance_string(value)}")


def _delete_placeholder_record(project_id: str) -> None:
    _delete_records_where(project_id, "chunk_id", "__placeholder__")


def _prune_removed_documents(
    project_id: str,
    store: CheckpointStore,
    live_keys: set[str],
) -> list[str]:
    removed_paths = store.prune(live_keys)
    if not removed_paths:
        return []
    for relative_path in removed_paths:
        _delete_records_where(project_id, "path", relative_path)
    remaining = {key: value for key, value in store.load().items() if key in live_keys}
    _save_index_state(remaining, project_id)
    return removed_paths


def _build_knowledge_records(chunk_specs: list[ChunkSpec]) -> list[dict[str, Any]]:
    if not chunk_specs:
        return []

    texts = [chunk.embed_text or chunk.text for chunk in chunk_specs]
    embedder = get_embedder()
    expected_identity = _write_identity()
    if hasattr(embedder, "encode_with_metadata"):
        vectors, spec, _ = embedder.encode_with_metadata(
            texts,
            input_type="document",
            forced_identity=expected_identity,
        )
        if spec.get("identity") != expected_identity:
            raise RuntimeError("Gateway returned an identity outside the write lease")
    else:
        vectors = embedder.encode(texts)
        spec = {}

    if len(vectors) != len(chunk_specs):
        raise RuntimeError(
            f"Gateway returned {len(vectors)} vectors for {len(chunk_specs)} chunks"
        )

    records: list[dict[str, Any]] = []

    for chunk, vector in zip(chunk_specs, vectors):
        metadata = dict(chunk.metadata)
        if spec and spec.get("identity"):
            metadata["embedding_identity"] = spec["identity"]
        records.append(
            {
                "text": chunk.text,
                "vector": normalize_vector(vector),
                "source": "workspace",
                "date": date.today().isoformat(),
                "path": str(chunk.metadata.get("path", "")),
                "chunk_id": str(chunk.metadata.get("chunk_id", "")),
                "metadata": json.dumps(metadata, ensure_ascii=False),
            }
        )

    return records


def _build_placeholder_records() -> list[dict[str, Any]]:
    return [
        {
            "text": "知識庫目前沒有內容。",
            "vector": normalize_vector(
                get_embedder().encode(
                    ["知識庫目前沒有內容。"],
                    forced_identity=_write_identity(),
                )[0]
            ),
            "source": "system",
            "date": date.today().isoformat(),
            "path": "",
            "chunk_id": "__placeholder__",
            "metadata": json.dumps({"placeholder": True}, ensure_ascii=False),
        }
    ]


def _fingerprint_document(path: Path) -> str:
    digest = hashlib.sha256()
    # 索引欄位或切塊規格改變時升版，讓內容未變的既有文件也會重建一次。
    digest.update(f"openvman-knowledge-v{_KNOWLEDGE_INDEX_FORMAT_VERSION}\0".encode())
    digest.update(path.read_bytes())
    return digest.hexdigest()


def _load_existing_knowledge_records(project_id: str = "default") -> list[dict[str, Any]]:
    db = get_db(project_id)
    table_name = resolve_vector_table_name("knowledge")
    if table_name not in db.table_names():
        return []
    return get_knowledge_table(project_id).to_arrow().to_pylist()


def _collect_reusable_records(
    records: list[dict[str, Any]],
    current_fingerprints: dict[str, str],
) -> list[dict[str, Any]]:
    reusable: list[dict[str, Any]] = []
    expected_identity = _write_identity()
    for record in records:
        metadata = parse_record_metadata(record)
        if metadata.get("placeholder"):
            continue
        identity = str(metadata.get("embedding_identity", "")).strip()
        if identity and identity != expected_identity:
            continue
        path = str(metadata.get("path", "")).strip()
        fingerprint = str(metadata.get("fingerprint", "")).strip()
        if not path or not fingerprint:
            continue
        if current_fingerprints.get(path) != fingerprint:
            continue
        reusable.append(record)
    return reusable


def _load_index_state(project_id: str = "default") -> dict[str, Any]:
    path = resolve_embedding_index_state_path(project_id)
    if not path.exists():
        return {}
    try:
        parsed = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return {}
    return parsed if isinstance(parsed, dict) else {}


def _save_index_state(documents: dict[str, str], project_id: str = "default") -> None:
    path = resolve_embedding_index_state_path(project_id)
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


def rename_document_records(old_path: str, new_path: str, project_id: str = "default") -> None:
    """Update LanceDB records and index state when a document is moved.

    Rewrites metadata.path and metadata.chunk_id from old_path to new_path in
    all matching chunks, then rebuilds the table in-place. No re-embedding is
    needed because content is unchanged.
    """
    records = _load_existing_knowledge_records(project_id)
    updated = []
    for record in records:
        metadata = parse_record_metadata(record)
        if str(metadata.get("path", "")).strip() == old_path:
            metadata["path"] = new_path
            old_chunk_id = str(metadata.get("chunk_id", ""))
            if old_chunk_id.startswith(old_path + "::"):
                metadata["chunk_id"] = new_path + "::" + old_chunk_id[len(old_path) + 2:]
            updated.append(
                {
                    **record,
                    "path": new_path,
                    "chunk_id": str(metadata.get("chunk_id", "")),
                    "metadata": json.dumps(metadata, ensure_ascii=False),
                }
            )
        else:
            updated.append(record)

    if not records:
        updated = _build_placeholder_records()
    get_db(project_id).create_table(
        resolve_vector_table_name("knowledge"),
        data=updated,
        mode="overwrite",
    )
    ensure_fts_index("knowledge", project_id)

    state = _load_index_state(project_id)
    docs = state.get("documents", {})
    if old_path in docs:
        docs = {(new_path if k == old_path else k): v for k, v in docs.items()}
        _save_index_state(docs, project_id)
