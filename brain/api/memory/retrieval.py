"""語意檢索與結果整理 — 支援 vector-only 與 hybrid (vector + FTS, RRF 融合) 搜索。"""

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
from memory.dreaming.recall_tracker import record_trace
from memory.embedder import encode_text
from memory.fusion import deduplicate, min_max_normalize, rrf_fuse
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
    distance_cutoff: float | None = None,
    expansion_terms: list[str] | None = None,
) -> list[dict[str, Any]]:
    """Execute search and return persona-filtered results.

    When *query_text* is provided, attempts hybrid search: vector 與 FTS
    各自檢索後以 RRF 融合,並輸出 min-max 正規化的 _score ∈ [0, 1]
    (越高越相關)。FTS 不可用時退回 vector-only。

    *expansion_terms*(語意擴展詞,通常由 memory.query_expansion 產生)
    每個詞會額外跑 vector + FTS 檢索,所有名次表一起進 RRF 融合。

    Results with _distance > distance_cutoff are dropped (FTS-only 命中
    沒有 _distance,不受 cutoff 影響)。候選會先做去重(exact text +
    embedding 餘弦相似度)。top_k is an upper cap.
    """
    from config import get_settings
    cfg = get_settings()
    cutoff = distance_cutoff if distance_cutoff is not None else cfg.rag_distance_cutoff

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
        rrf_k=cfg.rag_rrf_k,
        expansion_terms=expansion_terms or [],
        embedding_version=embedding_version,
    )

    # 先過濾再去重:省去對淘汰紀錄的餘弦比對,也避免被過濾掉的
    # 紀錄壓掉 persona 看得到的近似紀錄
    visible = [
        record
        for record in raw_records
        if record.get("_distance", 0.0) <= cutoff
        and _matches_persona(record, normalized_persona)
        and not (disabled_paths and _matches_disabled_knowledge_path(record, disabled_paths))
    ]
    deduped = deduplicate(
        visible,
        similarity_threshold=cfg.rag_dedup_similarity_threshold,
    )
    filtered = [_strip_vector(record) for record in deduped[:limit]]

    if filtered:
        try:
            record_trace(
                query=query_text or "",
                persona_id=persona_id,
                project_id=project_id,
                table_name=table_name,
                results=filtered,
            )
        except Exception as exc:
            logger.debug("recall trace record failed: %s", exc)

    return filtered


def _safe_search(
    table: Any,
    query_vector: list[float],
    query_text: str = "",
    query_type: str = "vector",
    limit: int = 10,
    rrf_k: int = 60,
    expansion_terms: list[str] | None = None,
    embedding_version: str | None = None,
) -> list[dict[str, Any]]:
    """Execute search with fallback and error handling."""
    try:
        if query_type == "hybrid":
            return _hybrid_search(
                table,
                query_vector,
                query_text,
                limit,
                rrf_k,
                expansion_terms or [],
                embedding_version,
            )
        return _normalize_vector_results(
            _search_to_records(table.search(query_vector).limit(limit))
        )
    except Exception as exc:
        logger.warning("Search failed for %s: %s", table, exc)
        return []


def _hybrid_search(
    table: Any,
    query_vector: list[float],
    query_text: str,
    limit: int,
    rrf_k: int,
    expansion_terms: list[str],
    embedding_version: str | None,
) -> list[dict[str, Any]]:
    """Hybrid search:原文與擴展詞各跑 vector + FTS,所有名次表一次 RRF 融合。

    只剩原文 vector 一路時退回 vector-only(仍輸出正規化 _score)。
    """
    vector_records = _search_to_records(table.search(query_vector).limit(limit))

    ranked_lists: list[list[dict[str, Any]]] = [vector_records]
    if fts_records := _try_fts_search(table, query_text, limit):
        ranked_lists.append(fts_records)

    for term in expansion_terms:
        if term_vector := _try_encode(term, embedding_version):
            if term_records := _search_to_records(table.search(term_vector).limit(limit)):
                ranked_lists.append(term_records)
        if term_fts := _try_fts_search(table, term, limit):
            ranked_lists.append(term_fts)

    if len(ranked_lists) == 1:
        return _normalize_vector_results(vector_records)

    fused = rrf_fuse(ranked_lists, k=rrf_k)
    return min_max_normalize(fused, source_field="_rrf_score", out_field="_score")[:limit]


def _try_fts_search(table: Any, query_text: str, limit: int) -> list[dict[str, Any]]:
    """FTS 檢索;index 不存在或失敗時回空 list。"""
    if not query_text:
        return []
    try:
        # 需要先建立 FTS index(infra.db.ensure_fts_index)
        return _search_to_records(table.search(query_text, query_type="fts").limit(limit))
    except Exception as exc:
        logger.debug("FTS search failed or unavailable for %r: %s", query_text, exc)
        return []


def _try_encode(term: str, embedding_version: str | None) -> list[float] | None:
    """編碼擴展詞;失敗時回 None 並略過該詞。"""
    try:
        return encode_text(term, embedding_version)
    except Exception as exc:
        logger.debug("expansion term encode failed for %r: %s", term, exc)
        return None


def _normalize_vector_results(records: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """vector-only 結果以 _distance 反向 min-max 正規化出 _score。"""
    return min_max_normalize(records, source_field="_distance", out_field="_score", invert=True)


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
    result = {key: value for key, value in record.items() if key != "vector"}
    meta = parse_record_metadata(record)
    if path := str(meta.get("path", "")).strip():
        result["path"] = path
    if title := str(meta.get("title", "")).strip():
        result["title"] = title
    return result


def _matches_disabled_knowledge_path(record: dict[str, Any], disabled_paths: set[str]) -> bool:
    metadata = parse_record_metadata(record)
    relative_path = str(metadata.get("path", "")).strip()
    return relative_path in disabled_paths
