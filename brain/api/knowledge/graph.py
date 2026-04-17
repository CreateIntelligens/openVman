"""Project-scoped knowledge graph orchestration.

Ties together :mod:`knowledge.graph_extractor` (LLM semantic extraction),
graphify's AST extractor, clustering, and HTML/JSON export. Each project's
graph artefacts live under ``<workspace>/graphify-out/``.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from graphify.analyze import god_nodes, surprising_connections
from graphify.build import build_from_json
from graphify.cluster import cluster, score_all
from graphify.detect import detect
from graphify.export import to_html, to_json
from graphify.extract import collect_files, extract as ast_extract
from knowledge.graph_extractor import extract_semantic
from knowledge.workspace import ensure_workspace_scaffold, get_workspace_root

GRAPH_SUBDIR = "graphify-out"
MAX_HTML_NODES = 5000
STATUS_FILENAME = "status.json"


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _status_path(project_id: str) -> Path:
    return _graph_dir(project_id) / STATUS_FILENAME


def _write_status(project_id: str, payload: dict[str, Any]) -> None:
    path = _status_path(project_id)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def load_project_status(project_id: str = "default") -> dict[str, Any]:
    path = _status_path(project_id)
    if not path.exists():
        return {"state": "absent", "project_id": project_id}
    return json.loads(path.read_text(encoding="utf-8"))


class EmptyGraphError(RuntimeError):
    """Raised when extraction yielded no nodes."""


def _graph_dir(project_id: str) -> Path:
    ensure_workspace_scaffold(project_id)
    out = get_workspace_root(project_id) / GRAPH_SUBDIR
    out.mkdir(parents=True, exist_ok=True)
    return out


def _run_ast_extraction(code_paths: list[Path]) -> dict[str, Any]:
    files: list[Path] = []
    for p in code_paths:
        files.extend(collect_files(p) if p.is_dir() else [p])
    if not files:
        return {"nodes": [], "edges": [], "input_tokens": 0, "output_tokens": 0}
    return ast_extract(files)


def rebuild_project_graph(project_id: str = "default") -> dict[str, Any]:
    """Rebuild the knowledge graph for a project.

    Reads the project's workspace ``knowledge/`` directory, runs AST extraction
    on code files and harnessed LLM semantic extraction on docs/papers, merges
    them, clusters, and writes ``graph.json`` + ``graph.html`` to
    ``<workspace>/graphify-out/``.
    """
    workspace_root = get_workspace_root(project_id)
    knowledge_dir = workspace_root / "knowledge"
    if not knowledge_dir.exists():
        raise FileNotFoundError(f"workspace knowledge/ 不存在: {knowledge_dir}")

    detection = detect(knowledge_dir)
    code_paths = [Path(f) for f in detection.get("files", {}).get("code", [])]
    doc_paths = [
        Path(f)
        for kind in ("document", "paper")
        for f in detection.get("files", {}).get(kind, [])
    ]

    ast_fragment = _run_ast_extraction(code_paths)
    semantic_fragment = extract_semantic(doc_paths, workspace_root)

    seen_ids = {n["id"] for n in ast_fragment.get("nodes", [])}
    merged_nodes = list(ast_fragment.get("nodes", []))
    for node in semantic_fragment.get("nodes", []):
        if node.get("id") in seen_ids:
            continue
        merged_nodes.append(node)
        seen_ids.add(node["id"])
    merged = {
        "nodes": merged_nodes,
        "edges": ast_fragment.get("edges", []) + semantic_fragment.get("edges", []),
        "hyperedges": semantic_fragment.get("hyperedges", []),
    }

    out_dir = _graph_dir(project_id)
    (out_dir / "extract.json").write_text(
        json.dumps(merged, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    (out_dir / "harness_report.json").write_text(
        json.dumps(semantic_fragment.get("_harness", {}), ensure_ascii=False, indent=2),
        encoding="utf-8",
    )

    graph = build_from_json(merged)
    if graph.number_of_nodes() == 0:
        raise EmptyGraphError("extraction produced no nodes")

    communities = cluster(graph)
    cohesion = score_all(graph, communities)
    gods = god_nodes(graph)
    surprises = surprising_connections(graph, communities)

    community_labels = {cid: f"Community {cid}" for cid in communities}
    to_json(graph, communities, str(out_dir / "graph.json"))
    if graph.number_of_nodes() <= MAX_HTML_NODES:
        to_html(
            graph,
            communities,
            str(out_dir / "graph.html"),
            community_labels=community_labels,
        )

    summary = {
        "project_id": project_id,
        "built_at": _now_iso(),
        "nodes": graph.number_of_nodes(),
        "edges": graph.number_of_edges(),
        "communities": len(communities),
        "god_nodes": [g.get("label") for g in gods[:10]],
        "surprising_bridges": len(surprises),
        "ast_nodes": len(ast_fragment.get("nodes", [])),
        "semantic_nodes": len(semantic_fragment.get("nodes", [])),
        "cohesion": {str(k): v for k, v in cohesion.items()},
        "harness": semantic_fragment.get("_harness", {}),
        "output_dir": str(out_dir),
    }
    (out_dir / "summary.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    return summary


def load_project_graph(project_id: str = "default") -> dict[str, Any]:
    """Return the raw ``graph.json`` for a project, or raise if missing."""
    path = _graph_dir(project_id) / "graph.json"
    if not path.exists():
        raise FileNotFoundError("graph 尚未建立，請先呼叫 rebuild")
    return json.loads(path.read_text(encoding="utf-8"))


def load_project_summary(project_id: str = "default") -> dict[str, Any]:
    path = _graph_dir(project_id) / "summary.json"
    if not path.exists():
        raise FileNotFoundError("graph 尚未建立，請先呼叫 rebuild")
    return json.loads(path.read_text(encoding="utf-8"))


def _graph_from_json(data: dict[str, Any]):
    from networkx.readwrite import json_graph

    return json_graph.node_link_graph(data, edges="links")


def _find_matching_nodes(graph, query: str, limit: int = 3) -> list[str]:
    terms = [t.lower() for t in query.split() if len(t) > 1]
    scored: list[tuple[int, str]] = []
    for nid, ndata in graph.nodes(data=True):
        label = str(ndata.get("label", "")).lower()
        score = sum(1 for t in terms if t in label)
        if label and query.lower() in label:
            score += 5
        if score > 0:
            scored.append((score, nid))
    scored.sort(reverse=True)
    return [nid for _, nid in scored[:limit]]


def query_project_graph(
    project_id: str,
    question: str,
    depth: int = 2,
    limit: int = 40,
) -> dict[str, Any]:
    """BFS traversal from best-matching nodes, up to ``depth`` hops."""
    data = load_project_graph(project_id)
    graph = _graph_from_json(data)
    starts = _find_matching_nodes(graph, question)
    if not starts:
        return {"question": question, "matches": 0, "nodes": [], "edges": []}

    visited = set(starts)
    frontier = set(starts)
    edge_records: list[dict[str, Any]] = []
    for _ in range(depth):
        next_frontier = set()
        for n in frontier:
            for neighbor in graph.neighbors(n):
                edge = graph.edges[n, neighbor]
                edge_records.append(
                    {
                        "source": graph.nodes[n].get("label", n),
                        "target": graph.nodes[neighbor].get("label", neighbor),
                        "relation": edge.get("relation"),
                        "confidence": edge.get("confidence"),
                    }
                )
                if neighbor not in visited:
                    next_frontier.add(neighbor)
        visited.update(next_frontier)
        frontier = next_frontier
        if len(visited) >= limit:
            break

    nodes_out = [
        {
            "id": nid,
            "label": graph.nodes[nid].get("label", nid),
            "source_file": graph.nodes[nid].get("source_file"),
        }
        for nid in list(visited)[:limit]
    ]
    return {
        "question": question,
        "matches": len(starts),
        "start_labels": [graph.nodes[n].get("label", n) for n in starts],
        "nodes": nodes_out,
        "edges": edge_records[:limit],
    }


def explain_project_node(project_id: str, node_label: str) -> dict[str, Any]:
    """Return a node's direct neighbours and edge relations."""
    data = load_project_graph(project_id)
    graph = _graph_from_json(data)
    matches = _find_matching_nodes(graph, node_label, limit=1)
    if not matches:
        return {"label": node_label, "found": False}
    nid = matches[0]
    node = graph.nodes[nid]
    connections = []
    for neighbor in graph.neighbors(nid):
        edge = graph.edges[nid, neighbor]
        connections.append(
            {
                "target": graph.nodes[neighbor].get("label", neighbor),
                "relation": edge.get("relation"),
                "confidence": edge.get("confidence"),
                "source_file": graph.nodes[neighbor].get("source_file"),
            }
        )
    return {
        "found": True,
        "label": node.get("label", nid),
        "source_file": node.get("source_file"),
        "degree": graph.degree(nid),
        "connections": connections,
    }
