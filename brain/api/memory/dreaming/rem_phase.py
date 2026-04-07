"""REM Phase — theme extraction from recall traces via embedding clustering.

Embeds recall trace queries, runs K-means clustering, generates
theme descriptions, and writes phase-signals.json for the next
Light phase cycle.
"""

from __future__ import annotations

import json
import logging
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import numpy as np

from config import get_settings
from memory.dreaming.paths import dreams_dir
from memory.dreaming.recall_tracker import read_traces
from memory.embedder import get_embedder

logger = logging.getLogger(__name__)

_DEFAULT_K = 5
_MIN_QUERIES_FOR_CLUSTERING = 3


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def run_rem_phase(project_id: str = "default") -> dict[str, Any]:
    """Execute the REM phase — extract themes from recall queries.

    Returns a status dict with theme count and signal path.
    """
    cfg = get_settings()

    # 1. Collect unique queries from traces
    traces = read_traces(project_id, days=cfg.dreaming_lookback_days)
    queries = _extract_unique_queries(traces)
    logger.info("rem phase: %d unique queries from %d traces", len(queries), len(traces))

    if len(queries) < _MIN_QUERIES_FOR_CLUSTERING:
        logger.info("rem phase: too few queries for clustering (%d < %d)", len(queries), _MIN_QUERIES_FOR_CLUSTERING)
        return {"status": "ok", "theme_count": 0, "reason": "insufficient_queries"}

    # 2. Embed queries
    embedder = get_embedder()
    vectors = embedder.encode(queries)

    # 3. Cluster
    k = min(_DEFAULT_K, len(queries))
    labels = _kmeans(np.array(vectors, dtype=np.float32), k)

    # 4. Build themes
    themes = _build_themes(queries, labels, k)
    logger.info("rem phase: extracted %d themes", len(themes))

    # 5. Write phase signals
    signals = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "query_count": len(queries),
        "themes": themes,
    }
    signal_path = _write_phase_signals(project_id, signals)

    return {
        "status": "ok",
        "theme_count": len(themes),
        "query_count": len(queries),
        "signal_path": str(signal_path),
    }


# ---------------------------------------------------------------------------
# Query extraction
# ---------------------------------------------------------------------------

def _extract_unique_queries(traces: list[dict[str, Any]]) -> list[str]:
    """Extract unique, non-empty queries from traces."""
    seen = set()
    return [q for t in traces if (q := str(t.get("query", "")).strip()) and q not in seen and not seen.add(q)]


# ---------------------------------------------------------------------------
# K-means clustering (numpy-only, no sklearn dependency)
# ---------------------------------------------------------------------------

def _kmeans(
    vectors: np.ndarray,
    k: int,
    max_iters: int = 20,
) -> np.ndarray:
    """Simple K-means clustering using numpy.

    Returns an array of cluster labels (0..k-1) for each input vector.
    """
    n = vectors.shape[0]
    if n <= k:
        return np.arange(n)

    # Initialise centroids using k evenly-spaced indices
    indices = np.linspace(0, n - 1, k, dtype=int)
    centroids = vectors[indices].copy()

    labels = np.zeros(n, dtype=int)

    for _ in range(max_iters):
        # Assign each vector to nearest centroid
        distances = np.linalg.norm(vectors[:, np.newaxis] - centroids[np.newaxis, :], axis=2)
        new_labels = np.argmin(distances, axis=1)

        if np.array_equal(labels, new_labels):
            break
        labels = new_labels

        # Update centroids
        for i in range(k):
            mask = labels == i
            if np.any(mask):
                centroids[i] = vectors[mask].mean(axis=0)

    return labels


# ---------------------------------------------------------------------------
# Theme building
# ---------------------------------------------------------------------------

def _build_themes(
    queries: list[str],
    labels: np.ndarray,
    k: int,
) -> list[dict[str, Any]]:
    """Build theme descriptions from clustered queries."""
    clusters: dict[int, list[str]] = defaultdict(list)
    for query, label in zip(queries, labels):
        clusters[int(label)].append(query)

    themes: list[dict[str, Any]] = []
    for cluster_id in sorted(clusters.keys()):
        members = clusters[cluster_id]
        description = _summarise_cluster(members)
        themes.append({
            "cluster_id": cluster_id,
            "query_count": len(members),
            "sample_queries": members[:5],
            "description": description,
        })

    # Sort by cluster size descending
    themes.sort(key=lambda t: t["query_count"], reverse=True)
    return themes


def _summarise_cluster(queries: list[str]) -> str:
    """Generate a simple description from cluster members."""
    if not queries: return ""
    rep = max(queries, key=len)
    return f"主題: {rep}" if len(queries) == 1 else f"主題 ({len(queries)} queries): {rep}"


# ---------------------------------------------------------------------------
# Output
# ---------------------------------------------------------------------------

def _write_phase_signals(
    project_id: str,
    signals: dict[str, Any],
) -> Path:
    path = _dreams_dir(project_id) / "phase-signals.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(signals, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    return path


def _dreams_dir(project_id: str) -> Path:
    return dreams_dir(project_id)
