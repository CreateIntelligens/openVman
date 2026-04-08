"""Unified retrieval and reranking service for brain context."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, timedelta
from typing import Any
import logging

from config import get_settings
from infra.db import parse_record_metadata
from memory.embedder import QueryEmbeddingRoute, encode_query_with_fallback
from memory.retrieval import search_records
from safety.observability import log_event

logger = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class RetrievalBundle:
    """Immutable result bundle from retrieval + reranking."""

    knowledge_results: list[dict[str, Any]]
    memory_results: list[dict[str, Any]]
    diagnostics: dict[str, Any]


def retrieve_context(
    *,
    query: str,
    persona_id: str = "default",
    project_id: str = "default",
) -> RetrievalBundle:
    """Retrieve and rerank context from knowledge and memory tables.

    Returns a RetrievalBundle with separated knowledge/memory results
    and diagnostics for observability.
    """
    cfg = get_settings()
    knowledge_top_k = cfg.rag_knowledge_top_k
    memory_top_k = cfg.rag_memory_top_k
    candidate_multiplier = cfg.rag_rerank_candidate_multiplier
    distance_bonus = cfg.rag_memory_distance_bonus
    decay_rate = cfg.memory_decay_rate_per_day
    importance_weight = cfg.memory_importance_weight

    # Encode query
    embedding_route = encode_query_with_fallback(
        query,
        project_id=project_id,
        table_names=("knowledge", "memories"),
    )
    query_vector = embedding_route.vector

    # Fetch candidates (wider than final top-k for reranking)
    # Pass query text to enable hybrid search (vector + FTS)
    knowledge_candidates = _safe_search(
        "knowledge", query_vector, knowledge_top_k * candidate_multiplier, persona_id,
        query_text=query, project_id=project_id, embedding_version=embedding_route.version,
    )
    memory_candidates = _safe_search(
        "memories", query_vector, memory_top_k * candidate_multiplier, persona_id,
        query_text=query, project_id=project_id, embedding_version=embedding_route.version,
    )

    # Rerank: sort by distance with memory bonus, decay, and importance
    reranked_knowledge = _rerank_by_distance(knowledge_candidates)
    reranked_memory = _rerank_by_distance(
        memory_candidates,
        distance_bonus=distance_bonus,
        decay_rate_per_day=decay_rate,
        importance_weight=importance_weight,
    )

    cutoff = cfg.rag_distance_cutoff

    if logger.isEnabledFor(logging.DEBUG):
        logger.debug(
            "retrieval_distances knowledge=%s memory=%s",
            [round(r["_effective_distance"], 3) for r in reranked_knowledge],
            [round(r["_effective_distance"], 3) for r in reranked_memory],
        )

    # Trim to final top-k with cutoff filtering
    final_knowledge = [r for r in reranked_knowledge if r["_effective_distance"] <= cutoff][:knowledge_top_k]
    final_memory = [r for r in reranked_memory if r["_effective_distance"] <= cutoff][:memory_top_k]

    # Build diagnostics
    diagnostics = _build_diagnostics(
        query=query,
        embedding_route=embedding_route,
        knowledge_candidates=len(knowledge_candidates),
        memory_candidates=len(memory_candidates),
        final_knowledge=final_knowledge,
        final_memory=final_memory,
    )

    log_event("retrieval_completed", **diagnostics)

    return RetrievalBundle(
        knowledge_results=final_knowledge,
        memory_results=final_memory,
        diagnostics=diagnostics,
    )


def _safe_search(
    table_name: str,
    query_vector: list[float],
    top_k: int,
    persona_id: str,
    *,
    query_text: str = "",
    project_id: str = "default",
    embedding_version: str | None = None,
) -> list[dict[str, Any]]:
    """Search with error handling — return empty on failure."""
    try:
        return search_records(
            table_name, query_vector, top_k, persona_id,
            query_text=query_text,
            project_id=project_id,
            embedding_version=embedding_version,
        )
    except Exception:
        return []


def _rerank_by_distance(
    candidates: list[dict[str, Any]],
    *,
    distance_bonus: float = 0.0,
    decay_rate_per_day: float = 0.0,
    importance_weight: float = 0.0,
) -> list[dict[str, Any]]:
    """Sort candidates by effective distance (ascending).

    effective_distance = raw_distance - bonus
                       + (days_old * decay_rate)
                       - (importance * importance_weight)

    A positive bonus (lower distance) makes candidates rank higher.
    Decay penalizes older records; importance rewards higher-scored records.
    """
    today = date.today()
    results = []

    for record in candidates:
        raw_distance = float(record.get("_distance", 999.0))
        effective = raw_distance - distance_bonus

        # Time decay: older records get penalized
        if decay_rate_per_day > 0:
            effective += _days_since(record, today) * decay_rate_per_day

        # Importance bonus: higher importance records rank better
        if importance_weight > 0:
            effective -= _record_importance(record) * importance_weight

        # Include effective distance in a copy to avoid mutating inputs
        enriched = {**record, "_effective_distance": effective}
        results.append(enriched)

    return sorted(results, key=lambda r: r["_effective_distance"])


def _days_since(record: dict[str, Any], today: date) -> float:
    """Return the number of days between the record's date and today."""
    try:
        raw_date = record.get("date")
        if not raw_date:
            return 0.0
        record_date = date.fromisoformat(str(raw_date))
        return float(max((today - record_date).days, 0))
    except (ValueError, TypeError):
        return 0.0


def _record_importance(record: dict[str, Any]) -> float:
    """Extract importance score from record metadata."""
    try:
        meta = parse_record_metadata(record)
        return float(meta.get("importance", 0.0))
    except (ValueError, TypeError):
        return 0.0


def _build_diagnostics(
    *,
    query: str,
    embedding_route: QueryEmbeddingRoute,
    knowledge_candidates: int,
    memory_candidates: int,
    final_knowledge: list[dict[str, Any]],
    final_memory: list[dict[str, Any]],
) -> dict[str, Any]:
    """Build a diagnostics dict for logging and observability."""
    top_hits: list[dict[str, Any]] = []

    for record in final_knowledge[:3]:
        meta = parse_record_metadata(record)
        top_hits.append({
            "source": "knowledge",
            "distance": record.get("_distance"),
            "path": meta.get("path", ""),
        })

    for record in final_memory[:3]:
        top_hits.append({
            "source": "memory",
            "distance": record.get("_distance"),
            "day": record.get("date", ""),
        })

    return {
        "query_preview": query[:60],
        "embedding_version": embedding_route.version,
        "embedding_attempts": embedding_route.attempted_versions,
        "knowledge_candidates": knowledge_candidates,
        "memory_candidates": memory_candidates,
        "final_knowledge": len(final_knowledge),
        "final_memory": len(final_memory),
        "top_hits": top_hits,
    }
