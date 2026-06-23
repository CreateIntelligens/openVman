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
from typing import Any

from infra.db import get_db
from knowledge.graph import NOTE_GRAPH_TABLE

logger = logging.getLogger("brain.knowledge.graph_rag")

FetchChunks = Callable[[str, int], list[dict[str, Any]]]


def _quote_sql_string(value: str) -> str:
    return "'" + value.replace("'", "''") + "'"


def _neighbour_files(hit_files: set[str], project_id: str) -> dict[str, list[str]]:
    """Return {neighbour_file: relations} for the given hit files, one hop out."""
    try:
        table = get_db(project_id).open_table(NOTE_GRAPH_TABLE)
    except Exception as exc:
        logger.debug("note_graph unavailable: %s", exc)
        return {}

    # Filter to just the hit files' rows in LanceDB instead of scanning the
    # whole table on every search (hot path).
    quoted = ", ".join(_quote_sql_string(file_path) for file_path in hit_files)
    try:
        rows = table.search().where(f"source_file IN ({quoted})").to_list()
    except Exception as exc:
        logger.debug("note_graph filter failed: %s", exc)
        return {}

    neighbours: dict[str, list[str]] = {}
    for row in rows:
        relations = row.get("relations", []) or []
        for file_path in row.get("related_files", []) or []:
            if file_path in hit_files:
                continue  # already retrieved directly
            neighbours.setdefault(file_path, list(relations))
    return neighbours


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
    for nf, rels in neighbours.items():
        if len(related) >= max_related:
            break
        try:
            chunks = fetch_chunks(nf, per_file)
        except Exception as exc:
            logger.debug("graph-related fetch failed for %s: %s", nf, exc)
            continue
        for c in chunks:
            related.append({**c, "_graph_related": True, "_via": rels})
    return related[:max_related]
