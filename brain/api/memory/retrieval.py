"""語意檢索與結果整理 — 支援 vector-only 與 hybrid (vector + FTS, RRF 融合) 搜索。"""

from __future__ import annotations

import logging
from typing import Any, Callable

from infra.db import (
    get_knowledge_table,
    get_memories_table,
    parse_record_metadata,
    vector_table_exists,
)
from knowledge.doc_meta import (
    list_disabled_document_paths,
    resolve_document_languages,
)
from knowledge.kb_settings import language_routes as project_language_routes
from memory.dreaming.recall_tracker import record_trace
from memory.embedder import encode_text
from memory.fusion import deduplicate, min_max_normalize, rrf_fuse
from memory.language_detect import DEFAULT_LANGUAGE
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
    language: str | None = None,
) -> list[dict[str, Any]]:
    """Execute search and return persona-filtered results.

    *language*（只對 knowledge 有效、且知識庫勾了兩條以上分流）：每份文件都
    查得到，語言只決定誰先進 top_k——使用者語言的文件優先，不夠再用主要語言
    （分流排第一的）補，最後才是其他語言。鶴記這種準備了中英西版本的專案因此
    用同語言的原文回答；只有別的語言寫到的內容也不會漏掉。只有一條分流不排序。

    When *query_text* is provided, attempts hybrid search: vector 與 FTS
    各自檢索後以 RRF 融合,並輸出 min-max 正規化的 _score ∈ [0, 1]
    (越高越相關)。FTS 不可用時退回 vector-only。

    *expansion_terms*(語意擴展詞,通常由 memory.query_expansion 產生)
    每個詞會額外跑 vector + FTS 檢索,所有名次表一起進 RRF 融合。

    Results with _distance > distance_cutoff are dropped, unless they
    were also matched by FTS. 候選會先做去重(exact text + embedding
    餘弦相似度)。top_k is an upper cap.
    """
    from config import get_settings

    cfg = get_settings()
    cutoff = distance_cutoff if distance_cutoff is not None else cfg.rag_distance_cutoff

    normalized_persona = normalize_persona_id(persona_id)
    limit = max(top_k, 1)
    if not vector_table_exists(table_name, project_id, embedding_version):
        return []
    table = get_search_table(table_name, project_id, embedding_version)
    disabled_paths = (
        list_disabled_document_paths(project_id) if table_name == "knowledge" else set()
    )
    routes = project_language_routes(project_id) if table_name == "knowledge" else []
    # 只有一條分流就不排語言，行為與分流功能出現前相同。
    prefer = language if language and len(routes) > 1 else None
    # 有勾的語言才往後擴查：其他語言的版本可能佔滿候選窗，把同語言的原文擠出去。
    # 沒勾的語言（例如只勾英西時的中文提問）不值得為它掃完整個知識庫。
    expand = prefer in routes
    search_limit = limit * (4 if disabled_paths or prefer else 2)
    record_count = table.count_rows() if expand else 0
    expansion_vectors: dict[str, list[float] | None] = {}

    while True:
        raw_records = _safe_search(
            table,
            query_vector,
            query_text=query_text or "",
            query_type=query_type,
            limit=search_limit,
            rrf_k=cfg.rag_rrf_k,
            expansion_terms=expansion_terms or [],
            embedding_version=embedding_version,
            expansion_vectors=expansion_vectors,
        )
        visible = [
            record
            for record in raw_records
            if _passes_relevance_cutoff(record, cutoff)
            and _matches_persona(record, normalized_persona)
            and not (
                disabled_paths
                and _matches_disabled_knowledge_path(record, disabled_paths)
            )
        ]
        # RRF 會合併重複候選，輸出少於 limit 不代表底層已搜完。
        exhausted = search_limit >= record_count
        rank = (
            _language_rank(visible, prefer, routes[0], project_id) if prefer else None
        )
        if rank is not None:
            # sorted 是穩定排序：同一語言內仍照相關度。去重留排前面的，所以
            # 同一段內容的其他語言版本會讓給使用者語言的原文。
            visible = sorted(visible, key=rank)
        deduped = deduplicate(
            visible,
            similarity_threshold=cfg.rag_dedup_similarity_threshold,
        )
        enough = rank is not None and sum(rank(r) == 0 for r in deduped) >= limit
        if not expand or exhausted or enough:
            break
        search_limit = min(search_limit * 2, record_count)
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
    expansion_vectors: dict[str, list[float] | None] | None = None,
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
                expansion_vectors,
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
    expansion_vectors: dict[str, list[float] | None] | None = None,
) -> list[dict[str, Any]]:
    """Hybrid search:原文與擴展詞各跑 vector + FTS,所有名次表一次 RRF 融合。

    只剩原文 vector 一路時退回 vector-only(仍輸出正規化 _score)。
    """
    vector_records = _search_to_records(table.search(query_vector).limit(limit))

    ranked_lists: list[list[dict[str, Any]]] = [vector_records]
    if fts_records := _try_fts_search(table, query_text, limit):
        ranked_lists.append(fts_records)

    if expansion_vectors is None:
        expansion_vectors = {}
    for term in expansion_terms:
        # 擴大候選窗只重查排名，不重送同一個語意擴展詞去編碼。
        if term not in expansion_vectors:
            expansion_vectors[term] = _try_encode(term, embedding_version)
        if term_vector := expansion_vectors[term]:
            if term_records := _search_to_records(
                table.search(term_vector).limit(limit)
            ):
                ranked_lists.append(term_records)
        if term_fts := _try_fts_search(table, term, limit):
            ranked_lists.append(term_fts)

    if len(ranked_lists) == 1:
        return _normalize_vector_results(vector_records)

    fused = rrf_fuse(ranked_lists, k=rrf_k)
    return min_max_normalize(fused, source_field="_rrf_score", out_field="_score")[
        :limit
    ]


def _try_fts_search(table: Any, query_text: str, limit: int) -> list[dict[str, Any]]:
    """FTS 檢索;index 不存在或失敗時回空 list。"""
    if not query_text:
        return []
    try:
        # 需要先建立 FTS index(infra.db.ensure_fts_index)
        return [
            {**record, "_fts_match": True}
            for record in _search_to_records(
                table.search(query_text, query_type="fts").limit(limit)
            )
        ]
    except Exception as exc:
        logger.debug("FTS search failed or unavailable for %r: %s", query_text, exc)
        return []


def _try_encode(term: str, embedding_version: str | None) -> list[float] | None:
    """編碼擴展詞;失敗時回 None 並略過該詞。"""
    try:
        return encode_text(term, embedding_version=embedding_version)
    except Exception as exc:
        logger.debug("expansion term encode failed for %r: %s", term, exc)
        return None


def _normalize_vector_results(records: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """vector-only 結果以 _distance 反向 min-max 正規化出 _score。"""
    return min_max_normalize(
        records, source_field="_distance", out_field="_score", invert=True
    )


def _passes_relevance_cutoff(record: dict[str, Any], cutoff: float) -> bool:
    if record.get("_fts_match") is True:
        return True
    return record.get("_distance", 0.0) <= cutoff


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
    result = {
        key: value
        for key, value in record.items()
        if key not in {"_fts_match", "vector"}
    }
    meta = parse_record_metadata(record)
    if path := str(meta.get("path", "")).strip():
        result["path"] = path
    if title := str(meta.get("title", "")).strip():
        result["title"] = title
    if image_id := str(meta.get("image_id") or meta.get("image") or "").strip():
        result["image_id"] = image_id
    if url := str(meta.get("url") or meta.get("source_url") or "").strip():
        result["url"] = url
    return result


def _language_rank(
    records: list[dict[str, Any]], language: str, primary: str, project_id: str,
) -> Callable[[dict[str, Any]], int]:
    """Rank a record 0 in the user's language, 1 in the primary language, else 2."""
    def path_of(record: dict[str, Any]) -> str:
        return str(parse_record_metadata(record).get("path", "")).strip()

    languages = resolve_document_languages(
        (path_of(record) for record in records), project_id,
    )
    order = {primary: 1, language: 0}

    def rank(record: dict[str, Any]) -> int:
        return order.get(languages.get(path_of(record), DEFAULT_LANGUAGE), 2)

    return rank


def _matches_disabled_knowledge_path(
    record: dict[str, Any], disabled_paths: set[str]
) -> bool:
    metadata = parse_record_metadata(record)
    relative_path = str(metadata.get("path", "")).strip()
    return relative_path in disabled_paths
