#!/usr/bin/env python3
from __future__ import annotations

import shutil
import subprocess
from pathlib import Path


def _resolve_graphify_python() -> Path:
    graphify_bin = shutil.which("graphify")
    if not graphify_bin:
        raise RuntimeError("`graphify` executable not found in PATH")

    first_line = Path(graphify_bin).read_text(encoding="utf-8").splitlines()[0].strip()
    if not first_line.startswith("#!"):
        raise RuntimeError(f"Unable to resolve graphify python from {graphify_bin}")

    python_path = Path(first_line[2:])
    if not python_path.exists():
        raise RuntimeError(f"Graphify python not found: {python_path}")
    return python_path


def main() -> int:
    repo_root = Path(__file__).resolve().parent.parent
    graphify_python = _resolve_graphify_python()

    inline = r"""
import json
import re
from collections import Counter
from pathlib import Path

from graphify.analyze import god_nodes, surprising_connections, suggest_questions
from graphify.build import build_from_json
from graphify.cluster import cluster, score_all
from graphify.export import to_html, to_json
from graphify.report import generate

ROOT = Path("docs")
OUT = ROOT / "graphify-out"
OUT.mkdir(exist_ok=True)

STOP_WORDS = {
    "the", "and", "for", "with", "from", "that", "this", "into", "over", "under", "after", "before",
    "about", "using", "used", "when", "your", "their", "there", "then", "than", "have", "has", "had",
    "will", "would", "should", "could", "onto", "across", "task", "plan", "spec", "docs", "doc",
    "guide", "notes", "note", "design", "system", "core", "backend", "frontend", "brain", "gateway",
    "protocol", "live", "pipeline", "support", "service", "services", "route", "routing", "manager",
    "index", "admin", "api", "http", "sse", "websocket", "audio", "voice", "project", "projects",
    "document", "documents", "knowledge", "memory",
}

KEY_TERMS_PATTERN = re.compile(
    r"\b(?:tts|lancedb|docling|markitdown|gemini|websocket|notebooklm|indextts2|vibevoice|"
    r"openapi|fastapi|polly|google|aws|gcp|wav2lip|dinet|dh_live|live2d|spine|nerf|ktx2)\b"
)


def make_id(*parts: str) -> str:
    text = "_".join(p for p in parts if p)
    text = re.sub(r"[^a-zA-Z0-9]+", "_", text).strip("_").lower()
    return text or "node"


def normalize_concept(text: str) -> str:
    text = text.strip().strip("`").strip()
    text = re.sub(r"\s+", " ", text)
    return text[:80]


files = sorted(p for p in ROOT.rglob("*.md") if "graphify-out" not in p.parts)
if not files:
    raise SystemExit("No markdown files found in docs")

nodes = []
edges = []
seen_nodes = set()
doc_concepts = {}


def add_node(node_id: str, **attrs) -> None:
    if node_id in seen_nodes:
        return
    seen_nodes.add(node_id)
    nodes.append({"id": node_id, **attrs})


def add_edge(source: str, target: str, relation: str, source_file: str, confidence: str = "EXTRACTED", weight: float = 1.0) -> None:
    edges.append(
        {
            "source": source,
            "target": target,
            "relation": relation,
            "confidence": confidence,
            "source_file": source_file,
            "weight": weight,
        }
    )


for path in files:
    rel = path.as_posix()
    text = path.read_text(encoding="utf-8")
    lines = text.splitlines()
    title = next((line.lstrip("#").strip() for line in lines if line.startswith("#")), path.stem)
    doc_id = make_id("doc", rel)
    add_node(doc_id, label=title, source_file=rel, file_type="document")

    concepts = Counter()
    for line in lines:
        if not line.startswith("#"):
            continue
        heading = line.lstrip("#").strip()
        if not heading:
            continue
        heading_id = make_id("heading", rel, heading)
        add_node(heading_id, label=heading, source_file=rel, file_type="document")
        add_edge(doc_id, heading_id, "contains", rel)

        for token in re.findall(r"`([^`]+)`", heading):
            concepts[normalize_concept(token)] += 2
        for token in re.findall(r"\b[A-Z]{2,}(?:_[A-Z0-9]+)*\b", heading):
            concepts[normalize_concept(token)] += 2
        for word in re.findall(r"\b[a-zA-Z][a-zA-Z0-9-]{3,}\b", heading.lower()):
            if word not in STOP_WORDS:
                concepts[word] += 1

    for token in re.findall(r"`([^`]{2,80})`", text):
        concepts[normalize_concept(token)] += 1
    for token in re.findall(r"\b[A-Z]{2,}(?:_[A-Z0-9]+)*\b", text):
        concepts[normalize_concept(token)] += 1
    for phrase in KEY_TERMS_PATTERN.findall(text.lower()):
        concepts[phrase] += 1

    concept_set = set()
    for concept, score in concepts.items():
        if not concept or len(concept) < 3:
            continue
        concept_id = make_id("concept", concept)
        add_node(concept_id, label=concept, source_file=rel, file_type="document")
        add_edge(doc_id, concept_id, "mentions", rel, confidence="INFERRED", weight=min(3.0, float(score)))
        concept_set.add(concept_id)

    doc_concepts[doc_id] = concept_set

for index, left in enumerate(files):
    left_id = make_id("doc", left.as_posix())
    for right in files[index + 1:]:
        right_id = make_id("doc", right.as_posix())
        shared = doc_concepts[left_id] & doc_concepts[right_id]
        if len(shared) >= 4:
            add_edge(
                left_id,
                right_id,
                "semantically_similar_to",
                left.as_posix(),
                confidence="INFERRED",
                weight=min(5.0, len(shared) / 2),
            )

extraction = {
    "nodes": nodes,
    "edges": edges,
    "hyperedges": [],
    "input_tokens": 0,
    "output_tokens": 0,
}

(OUT / ".graphify_extract.json").write_text(json.dumps(extraction, indent=2), encoding="utf-8")

G = build_from_json(extraction)
communities = cluster(G)
cohesion = score_all(G, communities)
gods = god_nodes(G)
surprises = surprising_connections(G, communities)
labels = {cid: f"Community {cid}" for cid in communities}
questions = suggest_questions(G, communities, labels)

detection = {
    "files": {
        "code": [],
        "document": [p.as_posix() for p in files],
        "paper": [],
        "image": [],
    },
    "total_files": len(files),
    "total_words": sum(len(p.read_text(encoding="utf-8").split()) for p in files),
}

report = generate(
    G,
    communities,
    cohesion,
    labels,
    gods,
    surprises,
    detection,
    {"input": 0, "output": 0},
    str(ROOT),
    suggested_questions=questions,
)
(OUT / "GRAPH_REPORT.md").write_text(report, encoding="utf-8")
to_json(G, communities, str(OUT / "graph.json"))
to_html(G, communities, str(OUT / "graph.html"), community_labels=labels)

print(
    f"[graphify docs] Rebuilt: {G.number_of_nodes()} nodes, "
    f"{G.number_of_edges()} edges, {len(communities)} communities"
)
print("[graphify docs] Updated docs/graphify-out/GRAPH_REPORT.md, graph.json, graph.html")
"""

    result = subprocess.run(
        [str(graphify_python), "-c", inline],
        cwd=repo_root,
        text=True,
    )
    return result.returncode


if __name__ == "__main__":
    raise SystemExit(main())
