"""語意檢索與結果整理 — 支援 vector-only 與 hybrid (vector + FTS) 搜索。"""

from __future__ import annotations

import logging
from typing import Any

from infra.db import (
    get_knowledge_table,
    get_memories_table,
    parse_record_metadata,
    vector_table_exists,
)
from knowledge.doc_meta import list_disabled_document_paths
from personas.personas import normalize_persona_id

logger = logging.getLogger(__name__)


def get_search_table(
    table_name: str,
    project_id: str = "default",
    embedding_version: str | None = None,
):
    """根據請求表名回傳對應資料表，維持既有預設行為。"""
    if table_name == "memories":
        return get_memories_table(project_id, embedding_version)
    return get_knowledge_table(project_id, embedding_version)


def search_records(
    table_name: str,
    query_vector: list[float],
    top_k: int = 5,
    query_text: str | None = None,
    query_type: str = "vector",
    persona_id: str = "default",
    project_id: str = "default",
    embedding_version: str | None = None,
) -> list[dict[str, Any]]:
    """Execute search and return persona-filtered results.

    When *query_text* is provided, attempts hybrid search (vector + FTS).
    Falls back to vector-only search if hybrid is not available.
    """
    normalized_persona = normalize_persona_id(persona_id)
    limit = max(top_k, 1)
    if not vector_table_exists(table_name, project_id, embedding_version):
        return []
    table = get_search_table(table_name, project_id, embedding_version)
    disabled_paths = list_disabled_document_paths(project_id) if table_name == "knowledge" else set()
    search_limit = top_k * 4 if disabled_paths else top_k * 2

    raw_records = _safe_search(
        table,
        query_vector,
        query_text=query_text or "",
        query_type=query_type,
        limit=search_limit,
    )

    filtered: list[dict[str, Any]] = []
    for record in raw_records:
        if not _matches_persona(record, normalized_persona):
            continue
        if disabled_paths and _matches_disabled_knowledge_path(record, disabled_paths):
            continue
        filtered.append(_strip_vector(record))
        if len(filtered) >= limit:
            break

    return filtered


def _safe_search(
    table: Any,
    query_vector: list[float],
    query_text: str = "",
    query_type: str = "vector",
    limit: int = 10,
) -> list[dict[str, Any]]:
    """Execute search with fallback and error handling."""
    try:
        if query_type == "hybrid":
            return _hybrid_search(table, query_vector, query_text, limit)
        return _search_to_records(table.search(query_vector).limit(limit))
    except Exception as exc:
        logger.warning("Search failed for %s: %s", table, exc)
        return []


def _hybrid_search(
    table: Any,
    query_vector: list[float],
    query_text: str,
    limit: int,
) -> list[dict[str, Any]]:
    """Try hybrid search (vector + FTS), fall back to vector-only."""
    if query_text:
        try:
            # LanceDB hybrid search: combines vector and FTS
            # Make sure FTS index exists before calling this
            result = (
                table.search(query_vector, query_type="hybrid")
                .text(query_text)
                .limit(limit)
            )
            records = _search_to_records(result)
            if records:
                return records
        except Exception as exc:
            logger.debug("hybrid search failed or unavailable, falling back to vector: %s", exc)

    # Vector-only fallback
    return _search_to_records(table.search(query_vector).limit(limit))


def _search_to_records(search_result: Any) -> list[dict[str, Any]]:
    if hasattr(search_result, "to_list"):
        return list(search_result.to_list())
    if hasattr(search_result, "to_arrow"):
        return list(search_result.to_arrow().to_pylist())
    return []


def _matches_persona(record: dict[str, Any], persona_id: str) -> bool:
    metadata = parse_record_metadata(record)
    record_persona = str(metadata.get("persona_id", "")).strip()
    if not record_persona or record_persona == "global":
        return True
    return normalize_persona_id(record_persona) == persona_id


def _strip_vector(record: dict[str, Any]) -> dict[str, Any]:
    return {key: value for key, value in record.items() if key != "vector"}


def _matches_disabled_knowledge_path(record: dict[str, Any], disabled_paths: set[str]) -> bool:
    metadata = parse_record_metadata(record)
    relative_path = str(metadata.get("path", "")).strip()
    return relative_path in disabled_paths
