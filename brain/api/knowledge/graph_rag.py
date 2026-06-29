"""File-level Graph RAG expansion over the LanceDB ``note_graph`` table.

Standard vector retrieval returns chunks scored purely by semantic distance and
never follows the concept graph. This module adds one hop: given the files a
vector search hit, it looks up their neighbours in ``note_graph`` (built by
:mod:`knowledge.graph`) and fetches those neighbours' chunks, so related
concepts that the query didn't lexically match still reach the LLM.

Kept deliberately simple: one hop, file granularity, no vectors. Returns plain
chunk records shaped like the vector-search results so callers can merge them.
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from infra.db import get_db
from knowledge.graph import NOTE_GRAPH_TABLE

logger = logging.getLogger("brain.knowledge.graph_rag")

FetchChunks = Callable[[str, int], list[dict[str, Any]]]

# Neighbours connected to more than this many files are treated as hubs and
# skipped during expansion — they pull in broad, low-signal noise.
GOD_NODE_DEGREE = 20


def _quote_sql_string(value: str) -> str:
    return "'" + value.replace("'", "''") + "'"


@dataclass(frozen=True)
class _Neighbour:
    file: str
    relations: list[str]
    confidence: float

    @property
    def rank_key(self) -> tuple[int, float]:
        # references (user-written wikilinks) first, then by confidence desc.
        is_reference = 1 if "references" in self.relations else 0
        return (is_reference, self.confidence)


def _neighbour_files(hit_files: set[str], project_id: str) -> list[_Neighbour]:
    """Return neighbours one hop out, ranked references-first then by confidence."""
    try:
        table = get_db(project_id).open_table(NOTE_GRAPH_TABLE)
    except Exception as exc:
        logger.debug("note_graph unavailable: %s", exc)
        return []

    # Filter to just the hit files' rows in LanceDB instead of scanning the
    # whole table on every search (hot path).
    quoted = ", ".join(_quote_sql_string(file_path) for file_path in hit_files)
    try:
        rows = table.search().where(f"source_file IN ({quoted})").to_list()
    except Exception as exc:
        logger.debug("note_graph filter failed: %s", exc)
        return []

    # Degree of every file mentioned in the fetched rows, to skip "god nodes"
    # (hubs like 首頁.md / 常見問題.md) that would inject broad, low-signal noise.
    degree = {
        row.get("source_file"): len(row.get("related_files", []) or [])
        for row in rows
    }

    best: dict[str, _Neighbour] = {}
    for row in rows:
        if row.get("source_file") not in hit_files:
            continue  # only expand neighbours of the actual hits
        related = list(row.get("related_files", []) or [])
        # Weight arrays are aligned to related_files by index; older tables built
        # before optimisation #3 lack them, so fall back to flat relations / 0.0.
        per_rel = list(row.get("neighbour_relations", []) or [])
        per_conf = list(row.get("neighbour_confidence", []) or [])
        flat_rel = list(row.get("relations", []) or [])
        for i, file_path in enumerate(related):
            if file_path in hit_files:
                continue  # already retrieved directly
            if degree.get(file_path, 0) > GOD_NODE_DEGREE:
                continue  # god node — too broadly connected to be useful
            relations = [per_rel[i]] if i < len(per_rel) else flat_rel
            confidence = float(per_conf[i]) if i < len(per_conf) else 0.0
            candidate = _Neighbour(file_path, relations, confidence)
            current = best.get(file_path)
            if current is None or candidate.rank_key > current.rank_key:
                best[file_path] = candidate

    return sorted(best.values(), key=lambda n: n.rank_key, reverse=True)


def expand_with_graph(
    hits: list[dict[str, Any]],
    project_id: str,
    fetch_chunks: FetchChunks,
    per_file: int = 1,
    max_related: int = 5,
) -> list[dict[str, Any]]:
    """Return related chunks one hop away from the vector hits.

    *hits* are vector-search records (each with a top-level ``path``).
    *fetch_chunks(file_path, limit)* returns chunk records for a file. The
    returned records are tagged ``_graph_related=True`` and carry ``_via`` (the
    relations that linked them) so the caller and the LLM can tell them apart
    from direct hits.
    """
    hit_files: set[str] = {h["path"] for h in hits if h.get("path")}
    if not hit_files:
        return []

    neighbours = _neighbour_files(hit_files, project_id)
    related: list[dict[str, Any]] = []
    for neighbour in neighbours:
        if len(related) >= max_related:
            break
        try:
            chunks = fetch_chunks(neighbour.file, per_file)
        except Exception as exc:
            logger.debug("graph-related fetch failed for %s: %s", neighbour.file, exc)
            continue
        for c in chunks:
            related.append({**c, "_graph_related": True, "_via": neighbour.relations})
    return related[:max_related]
