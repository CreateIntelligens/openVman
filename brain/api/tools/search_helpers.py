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


def merge_search_results(
    grouped: list[tuple[str, list[dict[str, Any]]]],
    *,
    limit: int,
) -> list[dict[str, Any]]:
    """Merge per-query result lists, dedupe by chunk identity, keep best rank.

    Hybrid records with ``_score`` sort first (descending), then vector-only
    records fall back to ``_distance`` (ascending). The originating queries
    that surfaced each record are preserved under ``matched_queries``.
    """
    by_key: dict[str, dict[str, Any]] = {}
    for query, records in grouped:
        for record in records:
            key = (
                record.get("chunk_id")
                or record.get("id")
                or f"{record.get('path', '')}::{record.get('text', '')[:80]}"
            )
            existing = by_key.get(key)
            if existing is None or _record_rank(record) < _record_rank(existing):
                merged_record = dict(record)
                if "_distance" in merged_record:
                    merged_record["_distance"] = float(merged_record["_distance"])
                prior = existing.get("matched_queries", []) if existing else []
                merged_record["matched_queries"] = list(dict.fromkeys([*prior, query]))
                by_key[key] = merged_record
            else:
                existing.setdefault("matched_queries", []).append(query)
    ordered = sorted(by_key.values(), key=_record_rank)
    return ordered[:limit]


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
