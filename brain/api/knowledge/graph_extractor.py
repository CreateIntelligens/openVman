"""LLM-backed semantic extraction with GAN-style validation harness.

Used by :mod:`knowledge.graph` to build knowledge graphs from non-code files
(markdown, txt, etc.) in a project workspace. Code files are handled by
graphify's own AST extractor and do not pass through here.
"""

from __future__ import annotations

import json
import unicodedata
from pathlib import Path
from typing import Any

from core.llm_client import generate_chat_turn

ALLOWED_FILE_TYPES = {"code", "document", "image", "paper", "rationale"}
DEFAULT_CHUNK_SIZE = 6
DEFAULT_MAX_ROUNDS = 3
FILE_CONTENT_LIMIT = 6000

EXTRACT_PROMPT = """Extract a knowledge graph fragment from the files below.
Output ONLY valid JSON. No markdown fences. No explanation.

REQUIREMENTS:
- Every file MUST have at least ONE node whose label matches the file's main topic.
- Use the canonical name as label (prefer the form that appears in the source text).
- Node id: snake_case ASCII, derived from the canonical concept.
- Extract named concepts, symptoms, treatments, risk factors, entities, relations.
- Relation vocabulary: causes, treats, symptom_of, risk_factor_for, related_to,
  prevents, references, conceptually_related_to, semantically_similar_to.
- Confidence: EXTRACTED (explicit in text) -> confidence_score 1.0;
  INFERRED 0.6-0.9; AMBIGUOUS 0.1-0.3.
- file_type must be one of: document, paper, image, rationale.

Schema (exactly these keys):
{"nodes":[{"id":"snake_case","label":"Canonical Name","file_type":"document","source_file":"relative/path","source_location":null}],"edges":[{"source":"node_id","target":"node_id","relation":"...","confidence":"EXTRACTED|INFERRED|AMBIGUOUS","confidence_score":1.0,"source_file":"relative/path","weight":1.0}],"hyperedges":[]}

__FEEDBACK__

Files in this chunk:
__FILE_LIST__

File contents:
__CONTENTS__
"""

SYNONYM_PROMPT = """Given the list of labels below, identify which labels refer to
the SAME concept (same entity expressed differently - language, abbreviation,
spelling). Do NOT group merely related concepts.

Output ONLY valid JSON, no fences, schema:
{"groups": [["label_a", "label_b"], ["label_c", "label_d"]]}

If nothing to merge, output {"groups": []}.

Labels:
__LABELS__
"""


def _strip_fences(text: str) -> str:
    text = text.strip()
    if text.startswith("```"):
        parts = text.split("\n", 1)
        if len(parts) == 2:
            text = parts[1]
        if text.rstrip().endswith("```"):
            text = text.rstrip()[: -3]
    return text.strip()


def _read_file(path: Path, limit: int = FILE_CONTENT_LIMIT) -> str:
    try:
        return path.read_text(encoding="utf-8", errors="replace")[:limit]
    except OSError as exc:
        return f"[read error: {exc}]"


def _norm_label(label: str) -> str:
    return unicodedata.normalize("NFKC", label).strip().lower()


def _chunk(seq: list[Path], size: int) -> list[list[Path]]:
    return [seq[i : i + size] for i in range(0, len(seq), size)]


def _relative(path: Path, root: Path) -> str:
    try:
        return path.relative_to(root).as_posix()
    except ValueError:
        return path.as_posix()


def _llm_extract(chunk: list[Path], workspace_root: Path, feedback: str = "") -> dict[str, Any]:
    file_list = "\n".join(f"- {_relative(f, workspace_root)}" for f in chunk)
    contents = "\n\n".join(
        f"=== {_relative(f, workspace_root)} ===\n{_read_file(f)}" for f in chunk
    )
    feedback_block = (
        f"PREVIOUS ATTEMPT HAD ISSUES (fix all of these):\n{feedback}\n"
        if feedback
        else ""
    )
    prompt = (
        EXTRACT_PROMPT
        .replace("__FEEDBACK__", feedback_block)
        .replace("__FILE_LIST__", file_list)
        .replace("__CONTENTS__", contents)
    )
    reply = generate_chat_turn(
        [{"role": "user", "content": prompt}],
        privacy_source="graph_extractor",
    )
    try:
        return json.loads(_strip_fences(reply.content))
    except json.JSONDecodeError:
        return {"nodes": [], "edges": [], "hyperedges": []}


def _validate_chunk(frag: dict[str, Any], chunk: list[Path], workspace_root: Path) -> list[str]:
    issues: list[str] = []
    nodes = frag.get("nodes", [])
    edges = frag.get("edges", [])

    sources = {n.get("source_file", "") for n in nodes}
    for f in chunk:
        rel = _relative(f, workspace_root)
        if rel not in sources:
            issues.append(
                f"MISSING_TOPIC_NODE: '{rel}' has no node. "
                "Add at least one node for this file's main topic."
            )

    node_ids = {n.get("id") for n in nodes}
    for e in edges:
        if e.get("source") not in node_ids:
            issues.append(
                f"DANGLING_EDGE: source id '{e.get('source')}' has no matching node."
            )
        if e.get("target") not in node_ids:
            issues.append(
                f"DANGLING_EDGE: target id '{e.get('target')}' has no matching node."
            )

    by_id: dict[str, str] = {}
    for n in nodes:
        nid, lbl = n.get("id"), n.get("label")
        if nid in by_id and by_id[nid] != lbl:
            issues.append(
                f"ID_COLLISION: id '{nid}' used for both '{by_id[nid]}' and '{lbl}'."
            )
        by_id[nid] = lbl
    return issues


def _clamp_file_types(nodes: list[dict[str, Any]]) -> list[dict[str, Any]]:
    cleaned = []
    for n in nodes:
        ft = n.get("file_type")
        if ft not in ALLOWED_FILE_TYPES:
            n = {**n, "file_type": "document"}
        cleaned.append(n)
    return cleaned


def _extract_chunk_with_harness(
    chunk: list[Path],
    workspace_root: Path,
    max_rounds: int,
) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    feedback = ""
    frag: dict[str, Any] = {"nodes": [], "edges": [], "hyperedges": []}
    report: list[dict[str, Any]] = []
    for round_i in range(max_rounds):
        frag = _llm_extract(chunk, workspace_root, feedback)
        issues = _validate_chunk(frag, chunk, workspace_root)
        report.append(
            {
                "round": round_i + 1,
                "nodes": len(frag.get("nodes", [])),
                "edges": len(frag.get("edges", [])),
                "issues": issues,
            }
        )
        if not issues:
            return frag, report
        feedback = "\n".join(f"- {i}" for i in issues)
    return frag, report


def _canonicalize_by_label(
    nodes: list[dict[str, Any]], edges: list[dict[str, Any]]
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    by_norm: dict[str, dict[str, Any]] = {}
    id_map: dict[str, str] = {}
    for n in nodes:
        key = _norm_label(n.get("label", ""))
        if not key:
            continue
        if key in by_norm:
            canonical = by_norm[key]
            id_map[n["id"]] = canonical["id"]
            sources = canonical.setdefault("source_files", [canonical["source_file"]])
            if n["source_file"] not in sources:
                sources.append(n["source_file"])
        else:
            by_norm[key] = dict(n)
            id_map[n["id"]] = n["id"]

    remapped_edges = []
    for e in edges:
        s = id_map.get(e["source"], e["source"])
        t = id_map.get(e["target"], e["target"])
        if s == t:
            continue
        remapped_edges.append({**e, "source": s, "target": t})
    return list(by_norm.values()), remapped_edges


def _resolve_synonyms(
    nodes: list[dict[str, Any]], edges: list[dict[str, Any]]
) -> tuple[list[dict[str, Any]], list[dict[str, Any]], list[list[str]]]:
    labels = sorted({n["label"] for n in nodes})
    if len(labels) < 3:
        return nodes, edges, []

    prompt = SYNONYM_PROMPT.replace("__LABELS__", "\n".join(f"- {l}" for l in labels))
    reply = generate_chat_turn(
        [{"role": "user", "content": prompt}],
        privacy_source="graph_extractor",
    )
    try:
        parsed = json.loads(_strip_fences(reply.content))
    except json.JSONDecodeError:
        return nodes, edges, []

    groups = parsed.get("groups") or []
    if not groups:
        return nodes, edges, []

    label_to_node = {n["label"]: n for n in nodes}
    id_map: dict[str, str] = {}
    merged_labels: set[str] = set()
    for group in groups:
        group_nodes = [label_to_node[l] for l in group if l in label_to_node]
        if len(group_nodes) < 2:
            continue
        canonical = group_nodes[0]
        for node in group_nodes[1:]:
            id_map[node["id"]] = canonical["id"]
            sources = canonical.setdefault("source_files", [canonical["source_file"]])
            if node["source_file"] not in sources:
                sources.append(node["source_file"])
            merged_labels.add(node["label"])

    new_nodes = [n for n in nodes if n["label"] not in merged_labels]
    new_edges = []
    for e in edges:
        s = id_map.get(e["source"], e["source"])
        t = id_map.get(e["target"], e["target"])
        if s == t:
            continue
        new_edges.append({**e, "source": s, "target": t})
    return new_nodes, new_edges, groups


def _dedup_edges(edges: list[dict[str, Any]]) -> list[dict[str, Any]]:
    seen = set()
    out = []
    for e in edges:
        key = (e["source"], e["target"], e.get("relation"))
        if key in seen:
            continue
        seen.add(key)
        out.append(e)
    return out


def _drop_dangling(
    edges: list[dict[str, Any]], nodes: list[dict[str, Any]]
) -> tuple[list[dict[str, Any]], int]:
    node_ids = {n["id"] for n in nodes}
    kept = [e for e in edges if e["source"] in node_ids and e["target"] in node_ids]
    return kept, len(edges) - len(kept)


def extract_semantic(
    files: list[Path],
    workspace_root: Path,
    chunk_size: int = DEFAULT_CHUNK_SIZE,
    max_rounds: int = DEFAULT_MAX_ROUNDS,
) -> dict[str, Any]:
    """Run harnessed semantic extraction over non-code files.

    Returns a graph fragment with keys ``nodes``, ``edges``, ``hyperedges`` plus
    a ``_harness`` report listing per-chunk round-by-round issues, synonym merge
    groups, and dangling-edge drop counts.
    """
    if not files:
        return {
            "nodes": [],
            "edges": [],
            "hyperedges": [],
            "_harness": {"chunks": [], "merged_synonym_groups": [], "dropped_dangling": 0},
        }

    chunks_report: list[dict[str, Any]] = []
    all_nodes: list[dict[str, Any]] = []
    all_edges: list[dict[str, Any]] = []

    for idx, chunk in enumerate(_chunk(files, chunk_size), start=1):
        frag, report = _extract_chunk_with_harness(chunk, workspace_root, max_rounds)
        chunks_report.append({"chunk": idx, "rounds": report})
        all_nodes.extend(frag.get("nodes", []))
        all_edges.extend(frag.get("edges", []))

    all_nodes = _clamp_file_types(all_nodes)
    nodes, edges = _canonicalize_by_label(all_nodes, all_edges)
    nodes, edges, groups = _resolve_synonyms(nodes, edges)
    edges = _dedup_edges(edges)
    edges, dropped = _drop_dangling(edges, nodes)

    return {
        "nodes": nodes,
        "edges": edges,
        "hyperedges": [],
        "_harness": {
            "chunks": chunks_report,
            "merged_synonym_groups": groups,
            "dropped_dangling": dropped,
        },
    }
