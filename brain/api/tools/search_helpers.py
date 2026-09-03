"""Standalone helpers shared by text-chat and Gemini Live search tools.

Kept dependency-free so it can be imported from contexts (e.g. live session
tests) that stub out heavier modules like ``memory.embedder``.
"""

from __future__ import annotations

from typing import Any


def _record_rank(record: dict[str, Any]) -> tuple[int, float]:
    score = record.get("_score")
    if isinstance(score, int | float):
        return (0, -float(score))
    distance = record.get("_distance")
    if isinstance(distance, int | float):
        return (1, float(distance))
    return (2, 999.0)


def normalize_query_list(args: dict[str, Any]) -> list[str]:
    """Accept either ``queries: string[]`` (preferred) or legacy ``query: string``."""
    raw = args.get("queries")
    if raw is None:
        single = args.get("query")
        raw = [single] if isinstance(single, str) else []
    if isinstance(raw, str):
        raw = [raw]
    if not isinstance(raw, list):
        return []
    seen: set[str] = set()
    cleaned: list[str] = []
    for item in raw:
        if not isinstance(item, str):
            continue
        text = item.strip()
        if not text or text in seen:
            continue
        seen.add(text)
        cleaned.append(text)
    return cleaned


RRF_K = 60
DEFAULT_MERGE_LIMIT = 5


def fused_limit(top_k: int, settings: Any) -> int:
    """How many fused records to keep: never fewer than one query's top_k.

    ``getattr`` 而非直接取屬性：部分測試用 SimpleNamespace 假設定載入此模組。
    """
    configured = getattr(settings, "knowledge_search_merge_limit", DEFAULT_MERGE_LIMIT)
    return max(int(top_k), int(configured))


def _record_key(record: dict[str, Any]) -> str:
    return (
        record.get("chunk_id")
        or record.get("id")
        or f"{record.get('path', '')}::{record.get('text', '')[:80]}"
    )


def merge_search_results(
    grouped: list[tuple[str, list[dict[str, Any]]]],
    *,
    limit: int,
    rrf_k: int = RRF_K,
) -> list[dict[str, Any]]:
    """Fuse per-query result lists with Reciprocal Rank Fusion.

    Each list is ranked on its own (hybrid ``_score`` descending, then vector
    ``_distance`` ascending) and every record earns ``1 / (rrf_k + rank)``.
    A chunk surfaced by several queries — typically the AI-rewritten query and
    the original user message — accumulates one contribution per list and
    therefore outranks a chunk that only one query found. Raw scores and
    distances are never compared across lists: they come from different query
    vectors and are not commensurable, ranks are. The kept copy is the one with
    the best per-list rank so ``_score``/``_distance`` stay meaningful, the fused
    score is exposed as ``_rrf_score``, and the originating queries are listed
    under ``matched_queries``.
    """
    fused: dict[str, float] = {}
    best: dict[str, dict[str, Any]] = {}
    matched: dict[str, list[str]] = {}
    for query, records in grouped:
        ordered = sorted(records, key=_record_rank)
        for rank, record in enumerate(ordered, start=1):
            key = _record_key(record)
            fused[key] = fused.get(key, 0.0) + 1.0 / (rrf_k + rank)
            matched.setdefault(key, [])
            if query not in matched[key]:
                matched[key].append(query)
            current = best.get(key)
            if current is None or _record_rank(record) < _record_rank(current):
                best[key] = record

    merged: list[dict[str, Any]] = []
    for key, record in best.items():
        merged_record = dict(record)
        if "_distance" in merged_record:
            merged_record["_distance"] = float(merged_record["_distance"])
        merged_record["_rrf_score"] = fused[key]
        merged_record["matched_queries"] = list(matched[key])
        merged.append(merged_record)
    merged.sort(key=lambda item: (-item["_rrf_score"], _record_rank(item)))
    return merged[:limit]


def build_citations(results: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Project merged search records into citation envelopes (jtai-style).

    Each citation carries a stable identifier (``uri``), a human label
    (``title``), the snippet that matched, the originating queries that
    surfaced it, and a numeric distance for client-side ranking.
    """
    citations: list[dict[str, Any]] = []
    for record in results:
        path = record.get("path") or record.get("relative_path") or ""
        title = record.get("title") or path or record.get("chunk_id") or "Resource"
        citation: dict[str, Any] = {
            "uri": path or record.get("chunk_id") or "",
            "title": title,
            "text": record.get("text", ""),
            "distance": float(record.get("_distance", 999.0)),
            "matched_queries": list(record.get("matched_queries", [])),
        }
        for key in (
            "image",
            "image_id",
            "url",
            "source_url",
            "heading_path",
            "row_number",
        ):
            value = record.get(key)
            if value not in (None, "", []):
                citation[key] = value
        citations.append(citation)
    return citations
