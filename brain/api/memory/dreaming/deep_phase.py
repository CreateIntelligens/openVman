"""Deep Phase — score candidates, promote to LanceDB memories table.

Reads candidates.json from the Light phase, applies weighted scoring
thresholds, deduplicates against existing memories, and writes promoted
records to LanceDB with source="dreaming".
"""

from __future__ import annotations

import json
import logging
from datetime import date, datetime
from pathlib import Path
from typing import Any

from config import get_settings
from infra.db import get_memories_table, normalize_vector
from memory.dreaming.paths import SOURCE_DREAMING, dreams_dir
from memory.dreaming.scoring import passes_threshold
from memory.embedder import get_embedder

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def run_deep_phase(project_id: str = "default") -> dict[str, Any]:
    """Execute the Deep phase — promote high-score candidates to memories.

    Returns a status dict with promoted_count and report path.
    """
    cfg = get_settings()

    # 1. Load candidates
    candidates = _load_candidates(project_id)
    if not candidates:
        logger.info("deep phase: no candidates to process")
        return {"status": "ok", "promoted_count": 0, "skipped": "no_candidates"}

    # 2. Filter by threshold
    qualified = [
        c for c in candidates
        if passes_threshold(
            c,
            min_score=cfg.dreaming_min_score,
            min_recall_count=cfg.dreaming_min_recall_count,
            min_unique_queries=1,
        )
    ]
    logger.info(
        "deep phase: %d/%d candidates pass threshold (min_score=%.2f)",
        len(qualified), len(candidates), cfg.dreaming_min_score,
    )

    if not qualified:
        return {"status": "ok", "promoted_count": 0, "total_candidates": len(candidates)}

    # 3. Semantic dedup against existing memories
    promotable = _dedup_against_memories(qualified, project_id, cfg.dreaming_similarity_threshold)
    logger.info("deep phase: %d candidates remain after semantic dedup", len(promotable))

    # 4. Promote to memories table
    promoted = _promote_to_memories(promotable, project_id)

    # 5. Write report
    report_path = _write_report(promoted, project_id, len(candidates), len(qualified))

    return {
        "status": "ok",
        "promoted_count": len(promoted),
        "total_candidates": len(candidates),
        "qualified_count": len(qualified),
        "report_path": str(report_path),
    }


# ---------------------------------------------------------------------------
# Internals
# ---------------------------------------------------------------------------

def _load_candidates(project_id: str) -> list[dict[str, Any]]:
    path = _dreams_dir(project_id) / "candidates.json"
    if not path.exists():
        return []
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        return data if isinstance(data, list) else []
    except (json.JSONDecodeError, OSError):
        return []


def _dedup_against_memories(
    candidates: list[dict[str, Any]],
    project_id: str,
    threshold: float,
) -> list[dict[str, Any]]:
    """Remove candidates semantically similar to existing memories via LanceDB search."""
    try:
        table = get_memories_table(project_id)
    except Exception:
        logger.debug("deep phase: could not open memories table, skipping dedup")
        return candidates

    embedder = get_embedder()
    candidate_vectors = embedder.encode([c["text"] for c in candidates])

    # Convert similarity threshold to distance threshold.
    # LanceDB uses L2 distance by default; cosine similarity ≈ 1 - (dist²/2).
    # For a conservative check, we search for the nearest neighbour and compare.
    result = []
    for c, vec in zip(candidates, candidate_vectors):
        c["_vector"] = vec
        try:
            hits = table.search(vec).limit(1).to_list()
            if hits and (1.0 - hits[0].get("_distance", 1.0)) >= threshold:
                continue
        except Exception:
            pass  # table may be empty or incompatible; keep the candidate
        result.append(c)

    return result


def _promote_to_memories(candidates: list[dict[str, Any]], project_id: str) -> list[dict[str, Any]]:
    """Add promoted candidates to the memories table."""
    if not candidates: return []

    embedder, records = get_embedder(), []
    today = date.today().isoformat()

    for c in candidates:
        vec = c.get("_vector") or embedder.encode([c["text"]])[0]
        signals = c.get("signals", {})
        records.append({
            "text": c["text"],
            "vector": normalize_vector(vec),
            "source": SOURCE_DREAMING,
            "date": today,
            "metadata": json.dumps({
                "kind": "dreaming_promoted",
                "persona_id": c.get("persona_id", "default"),
                "source_day": c.get("day", ""),
                "dreaming_score": c.get("score", 0.0),
                "importance": signals.get("importance", 0.0),
            }, ensure_ascii=False),
        })

    if records:
        try:
            get_memories_table(project_id).add(records)
            logger.info("deep phase: promoted %d records", len(records))
        except Exception as exc:
            logger.error("deep phase: promotion failed: %s", exc)
            return []
    return records


def _write_report(
    promoted: list[dict[str, Any]],
    project_id: str,
    total: int,
    qualified: int,
) -> Path:
    """Write a markdown report of the Deep phase results."""
    ws = get_workspace_root(project_id)
    report_path = ws / "dreaming" / "deep" / f"{date.today().isoformat()}.md"
    report_path.parent.mkdir(parents=True, exist_ok=True)

    lines = [
        f"# Deep Phase Report — {date.today().isoformat()}", "",
        f"- Total candidates: {total}",
        f"- Qualified: {qualified}",
        f"- Promoted: {len(promoted)}", "",
    ]
    if promoted:
        lines += ["## Promoted Memories", ""] + [f"{i}. {r['text'][:100]}" for i, r in enumerate(promoted, 1)] + [""]

    report_path.write_text("\n".join(lines), encoding="utf-8")
    return report_path


def _dreams_dir(project_id: str) -> Path:
    return dreams_dir(project_id)
