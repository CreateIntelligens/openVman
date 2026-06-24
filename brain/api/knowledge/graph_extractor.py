"""LLM-backed semantic extraction with GAN-style validation harness.

Used by :mod:`knowledge.graph` to build knowledge graphs from non-code files
(markdown, txt, etc.) in a project workspace. Code files are handled by
graphify's own AST extractor and do not pass through here.
"""

from __future__ import annotations

import json
import re
import unicodedata
from dataclasses import dataclass
from pathlib import Path
from typing import Any, TypeVar

# Obsidian-style explicit wikilink: [[Target]], [[Target|Alias]],
# [[Target#Heading]] or [[folder/Target]]. We only care about the target file
# reference, so alias (after |) and heading (after #) are stripped.
_WIKILINK_RE = re.compile(r"\[\[([^\[\]|#]+)(?:[|#][^\[\]]*)?\]\]")

from core.llm_client import generate_chat_turn

_T = TypeVar("_T")

ALLOWED_FILE_TYPES = {"code", "document", "image", "paper", "rationale"}
DEFAULT_CHUNK_SIZE = 6
DEFAULT_MAX_ROUNDS = 3
# Per-segment character budget fed to the LLM. Long files are split into
# multiple segments of this size (see ``_build_sources``) instead of being
# truncated, so the whole document is extracted, not just its opening.
SEGMENT_SIZE = 6000
GLOBAL_LINK_BATCH = 120

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
- Be aggressive with INFERRED edges: if two concepts are medically or
  semantically related (shared cause, same body part, one is a complication
  or treatment of the other) connect them even when the text does not say so
  explicitly. Prefer an INFERRED edge over leaving a concept isolated.
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

GLOBAL_LINK_PROMPT = """Below is the full list of concepts extracted from a
knowledge base, each as `id\tlabel`. Concepts came from different files and were
never compared against each other. Find cross-concept relationships that span
DIFFERENT topics — a concept that is a cause, complication, treatment, risk
factor, or close semantic match of another.

Rules:
- Only connect concepts that are genuinely related; do not invent links.
- Use ONLY ids from the list. Never introduce a new id.
- These are inferences, so confidence is INFERRED (0.6-0.9).
- Relation vocabulary: causes, treats, symptom_of, risk_factor_for, related_to,
  prevents, conceptually_related_to, semantically_similar_to.
- Skip pairs already obviously within the same topic; focus on cross-topic links.

Output ONLY valid JSON, no fences, schema:
{"edges":[{"source":"id","target":"id","relation":"...","confidence":"INFERRED","confidence_score":0.75,"weight":1.0}]}

If there is nothing to add, output {"edges": []}.

Concepts:
__NODES__
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


def _load_json_object(text: str) -> dict[str, Any] | None:
    try:
        parsed = json.loads(_strip_fences(text))
    except json.JSONDecodeError:
        return None
    if isinstance(parsed, dict):
        return parsed
    return None


@dataclass(frozen=True)
class _Source:
    """One unit of content fed to extraction: a whole short file, or one
    segment of a long file. ``path`` is always the real file path so node
    ``source_file`` tagging, validation, and origin classification are
    unchanged regardless of how the file was split."""

    path: Path
    text: str
    segment: int = 1  # 1-based segment index
    total_segments: int = 1


def _split_text(text: str, size: int = SEGMENT_SIZE) -> list[str]:
    """Split text into <=size-char segments on paragraph/line boundaries.

    Greedily packs whole paragraphs (then lines, then a hard cut) so concepts
    that span a few lines stay within one segment instead of being severed.
    """
    if len(text) <= size:
        return [text]
    segments: list[str] = []
    buf = ""
    for para in text.split("\n\n"):
        block = para if not buf else f"{buf}\n\n{para}"
        if len(block) <= size:
            buf = block
            continue
        if buf:
            segments.append(buf)
            buf = ""
        # ``para`` alone still too big: fall back to line-then-hard splits.
        while len(para) > size:
            cut = para.rfind("\n", 0, size)
            cut = cut if cut > 0 else size
            segments.append(para[:cut])
            para = para[cut:].lstrip("\n")
        buf = para
    if buf:
        segments.append(buf)
    return segments


def _build_sources(files: list[Path]) -> list[_Source]:
    """Read each file in full and split long ones into ``_Source`` segments."""
    sources: list[_Source] = []
    for path in files:
        try:
            text = path.read_text(encoding="utf-8", errors="replace")
        except OSError as exc:
            sources.append(_Source(path, f"[read error: {exc}]"))
            continue
        parts = _split_text(text)
        total = len(parts)
        for i, part in enumerate(parts, start=1):
            sources.append(_Source(path, part, segment=i, total_segments=total))
    return sources


def _norm_label(label: str) -> str:
    return unicodedata.normalize("NFKC", label).strip().lower()


def _chunk(seq: list[_T], size: int) -> list[list[_T]]:
    return [seq[i : i + size] for i in range(0, len(seq), size)]


def _relative(path: Path, root: Path) -> str:
    try:
        return path.relative_to(root).as_posix()
    except ValueError:
        return path.as_posix()


def _unique_paths(chunk: list[_Source]) -> list[_Source]:
    """One _Source per distinct file (first segment), preserving order."""
    seen: set[Path] = set()
    out: list[_Source] = []
    for s in chunk:
        if s.path in seen:
            continue
        seen.add(s.path)
        out.append(s)
    return out


def _segment_header(src: _Source, workspace_root: Path) -> str:
    rel = _relative(src.path, workspace_root)
    if src.total_segments > 1:
        return f"{rel} (part {src.segment}/{src.total_segments})"
    return rel


def _llm_extract(chunk: list[_Source], workspace_root: Path, feedback: str = "") -> dict[str, Any]:
    file_list = "\n".join(
        f"- {_relative(s.path, workspace_root)}" for s in _unique_paths(chunk)
    )
    contents = "\n\n".join(
        f"=== {_segment_header(s, workspace_root)} ===\n{s.text}" for s in chunk
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
    parsed = _load_json_object(reply.content)
    if parsed is None:
        return {"nodes": [], "edges": [], "hyperedges": []}
    return parsed


def _validate_chunk(frag: dict[str, Any], chunk: list[_Source], workspace_root: Path) -> list[str]:
    issues: list[str] = []
    nodes = frag.get("nodes", [])
    edges = frag.get("edges", [])

    sources = {n.get("source_file", "") for n in nodes}
    for s in _unique_paths(chunk):
        rel = _relative(s.path, workspace_root)
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
    chunk: list[_Source],
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
    parsed = _load_json_object(reply.content)
    if parsed is None:
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


def _link_global(nodes: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Ask the LLM for cross-topic edges over concept batches.

    Per-chunk extraction never sees concepts from other chunks, so cross-file
    relationships are missed and many nodes end up isolated. This pass feeds the
    id/label list back to the model in batches and collects INFERRED edges whose
    endpoints both exist. Returns only valid (non-dangling) new edges.
    """
    if len(nodes) < 2:
        return []

    node_ids = {n["id"] for n in nodes}
    new_edges: list[dict[str, Any]] = []
    for batch in _chunk(nodes, GLOBAL_LINK_BATCH):
        listing = "\n".join(f"{n['id']}\t{n['label']}" for n in batch)
        prompt = GLOBAL_LINK_PROMPT.replace("__NODES__", listing)
        reply = generate_chat_turn(
            [{"role": "user", "content": prompt}],
            privacy_source="graph_extractor",
        )
        frag = _load_json_object(reply.content)
        if frag is None:
            continue

        for edge in frag.get("edges", []):
            source_id = edge.get("source")
            target_id = edge.get("target")
            if (
                source_id not in node_ids
                or target_id not in node_ids
                or source_id == target_id
            ):
                continue

            new_edges.append(
                {
                    "source": source_id,
                    "target": target_id,
                    "relation": edge.get("relation", "related_to"),
                    "confidence": "INFERRED",
                    "confidence_score": edge.get("confidence_score", 0.7),
                    "source_file": "__global_link__",
                    "weight": edge.get("weight", 1.0),
                }
            )
    return new_edges


def _topic_node_by_source(nodes: list[dict[str, Any]]) -> dict[str, str]:
    """Map each source file to its primary (topic) node id.

    Extraction guarantees every file has at least one node, and the first node
    emitted for a file is its main-topic node. Building this map lets explicit
    wikilinks resolve to a real, canonicalized node id. A node may carry
    multiple ``source_files`` after synonym merging, so every listed source is
    indexed — first writer wins, matching emission order.
    """
    mapping: dict[str, str] = {}
    for node in nodes:
        for src in _source_files(node):
            mapping.setdefault(src, node["id"])
    return mapping


def _source_files(node: dict[str, Any]) -> list[str]:
    files = node.get("source_files") or []
    if not files and node.get("source_file"):
        files = [node["source_file"]]
    return files


def _resolve_wikilink_target(raw: str, source_map: dict[str, str]) -> str | None:
    """Resolve a wikilink target string to a topic node id, or None.

    Obsidian links omit the extension and often the folder. Match against known
    source paths by basename (with/without ``.md``) so ``[[Refund Policy]]``
    finds ``knowledge/policies/Refund Policy.md``.
    """
    target = raw.strip()
    if not target:
        return None
    candidates = {target, f"{target}.md"}
    stem = target.rsplit("/", 1)[-1]
    candidates |= {stem, f"{stem}.md"}
    for src, node_id in source_map.items():
        src_name = src.rsplit("/", 1)[-1]
        if src in candidates or src_name in candidates:
            return node_id
    return None


def _link_wikilinks(
    nodes: list[dict[str, Any]],
    files: list[Path],
    workspace_root: Path,
) -> list[dict[str, Any]]:
    """Turn explicit Obsidian ``[[wikilinks]]`` into deterministic edges.

    Unlike LLM extraction, a wikilink is an author-declared relationship, so
    these edges are EXTRACTED (confidence 1.0). Each ``[[B]]`` in file A becomes
    ``A_topic --references--> B_topic`` where both endpoints are the files'
    canonicalized topic nodes. Targets that don't resolve to a known node
    (e.g. links to non-knowledge files) are skipped.
    """
    source_map = _topic_node_by_source(nodes)
    if not source_map:
        return []

    edges: list[dict[str, Any]] = []
    seen: set[tuple[str, str]] = set()
    for path in files:
        rel = _relative(path, workspace_root)
        source_id = source_map.get(rel) or source_map.get(rel.rsplit("/", 1)[-1])
        if source_id is None:
            continue
        try:
            text = path.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        for match in _WIKILINK_RE.finditer(text):
            target_id = _resolve_wikilink_target(match.group(1), source_map)
            if target_id is None or target_id == source_id:
                continue
            key = (source_id, target_id)
            if key in seen:
                continue
            seen.add(key)
            edges.append(
                {
                    "source": source_id,
                    "target": target_id,
                    "relation": "references",
                    "confidence": "EXTRACTED",
                    "confidence_score": 1.0,
                    "source_file": rel,
                    "weight": 1.0,
                }
            )
    return edges


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

    # Read + segment long files first, then chunk over segments. A chunk holds
    # up to ``chunk_size`` segments (each <= SEGMENT_SIZE chars), so a long book
    # is extracted across several calls instead of being truncated to its head.
    sources = _build_sources(files)
    for idx, chunk in enumerate(_chunk(sources, chunk_size), start=1):
        frag, report = _extract_chunk_with_harness(chunk, workspace_root, max_rounds)
        chunks_report.append({"chunk": idx, "rounds": report})
        all_nodes.extend(frag.get("nodes", []))
        all_edges.extend(frag.get("edges", []))

    all_nodes = _clamp_file_types(all_nodes)
    nodes, edges = _canonicalize_by_label(all_nodes, all_edges)
    nodes, edges, groups = _resolve_synonyms(nodes, edges)
    # Global linking pass: connect cross-topic concepts the per-chunk extraction
    # never compared. Runs on canonical ids so endpoints resolve correctly.
    global_edges = _link_global(nodes)
    # Explicit Obsidian wikilinks: author-declared edges (EXTRACTED, 1.0).
    # Placed before LLM/global edges in the dedup input so the deterministic
    # high-confidence edge wins over any LLM-inferred duplicate of the same pair.
    wikilink_edges = _link_wikilinks(nodes, files, workspace_root)
    edges = _dedup_edges(wikilink_edges + edges + global_edges)
    edges, dropped = _drop_dangling(edges, nodes)

    return {
        "nodes": nodes,
        "edges": edges,
        "hyperedges": [],
        "_harness": {
            "chunks": chunks_report,
            "merged_synonym_groups": groups,
            "global_link_edges": len(global_edges),
            "wikilink_edges": len(wikilink_edges),
            "dropped_dangling": dropped,
        },
    }
