"""Unified retrieval and reranking service for brain context."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from config import get_settings
from infra.db import parse_record_metadata
from memory.embedder import get_embedder
from memory.retrieval import search_records
from safety.observability import log_event


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

    # Encode query
    query_vector = get_embedder().encode([query])[0]

    # Fetch candidates (wider than final top-k for reranking)
    knowledge_candidates = _safe_search(
        "knowledge", query_vector, knowledge_top_k * candidate_multiplier, persona_id
    )
    memory_candidates = _safe_search(
        "memories", query_vector, memory_top_k * candidate_multiplier, persona_id
    )

    # Rerank: sort by distance with memory bonus
    reranked_knowledge = _rerank_by_distance(knowledge_candidates)
    reranked_memory = _rerank_by_distance(memory_candidates, distance_bonus=distance_bonus)

    # Trim to final top-k
    final_knowledge = reranked_knowledge[:knowledge_top_k]
    final_memory = reranked_memory[:memory_top_k]

    # Build diagnostics
    diagnostics = _build_diagnostics(
        query=query,
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
) -> list[dict[str, Any]]:
    """Search with error handling — return empty on failure."""
    try:
        return search_records(table_name, query_vector, top_k, persona_id)
    except Exception:
        return []


def _rerank_by_distance(
    candidates: list[dict[str, Any]],
    *,
    distance_bonus: float = 0.0,
) -> list[dict[str, Any]]:
    """Sort candidates by _distance (ascending), applying an optional bonus.

    A negative bonus makes candidates appear closer (lower distance = better).
    """
    def sort_key(record: dict[str, Any]) -> float:
        raw_distance = float(record.get("_distance", 999.0))
        return raw_distance - distance_bonus

    return sorted(candidates, key=sort_key)


def _build_diagnostics(
    *,
    query: str,
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
        "knowledge_candidates": knowledge_candidates,
        "memory_candidates": memory_candidates,
        "final_knowledge": len(final_knowledge),
        "final_memory": len(final_memory),
        "top_hits": top_hits,
    }
