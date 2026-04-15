#!/usr/bin/env python3
"""Graphify knowledge graph builder for openVman."""
from __future__ import annotations

import argparse
import shutil
import subprocess
from pathlib import Path

EXCLUDE_DIRS = {
    "graphify-out", "__pycache__", "node_modules",
    ".superpowers", ".claude", ".gemini", ".codex",
    ".agent", ".kilocode", ".github", ".git",
    ".pytest_cache", ".ruff_cache", "dist", "assets",
}


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


def _run(python: Path, code: str, cwd: Path) -> int:
    return subprocess.run([str(python), "-c", code], cwd=cwd, text=True).returncode


def main() -> int:
    parser = argparse.ArgumentParser(description="Graphify knowledge graph builder")
    parser.add_argument("--update", action="store_true", help="Incremental: only re-extract changed files")
    parser.add_argument("--watch", action="store_true", help="Auto-rebuild on file changes")
    parser.add_argument("--wiki", action="store_true", help="Generate agent-crawlable wiki")
    parser.add_argument("--query", metavar="QUESTION", help="BFS/DFS query on existing graph")
    parser.add_argument("--dfs", action="store_true", help="Use DFS instead of BFS for --query")
    args = parser.parse_args()

    repo_root = Path(__file__).resolve().parent.parent
    python = _resolve_graphify_python()
    exclude_json = __import__("json").dumps(list(EXCLUDE_DIRS))

    if args.query:
        mode = "dfs" if args.dfs else "bfs"
        code = f"""
import json, sys
from pathlib import Path
from networkx.readwrite import json_graph

graph_path = Path('graphify-out/graph.json')
if not graph_path.exists():
    print('[graphify] No graph found. Run rebuild first.', file=sys.stderr)
    raise SystemExit(1)

data = json.loads(graph_path.read_text())
G = json_graph.node_link_graph(data, edges='links')

question = {args.query!r}
mode = {mode!r}
terms = [t.lower() for t in question.split() if len(t) >= 2]

scored = [(sum(1 for t in terms if t in G.nodes[n].get('label','').lower()), n) for n in G.nodes()]
scored.sort(reverse=True)
start_nodes = [n for score, n in scored[:3] if score > 0]

if not start_nodes:
    print('No matching nodes found for:', terms)
    raise SystemExit(0)

subgraph_nodes = set()
subgraph_edges = []

if mode == 'dfs':
    visited = set()
    stack = [(n, 0) for n in reversed(start_nodes)]
    while stack:
        node, depth = stack.pop()
        if node in visited or depth > 6:
            continue
        visited.add(node)
        subgraph_nodes.add(node)
        for neighbor in G.neighbors(node):
            if neighbor not in visited:
                stack.append((neighbor, depth + 1))
                subgraph_edges.append((node, neighbor))
else:
    frontier = set(start_nodes)
    subgraph_nodes = set(start_nodes)
    for _ in range(3):
        next_frontier = set()
        for n in frontier:
            for neighbor in G.neighbors(n):
                if neighbor not in subgraph_nodes:
                    next_frontier.add(neighbor)
                    subgraph_edges.append((n, neighbor))
        subgraph_nodes.update(next_frontier)
        frontier = next_frontier

print(f'Traversal: {{mode.upper()}} | Start: {{[G.nodes[n].get("label",n) for n in start_nodes]}} | {{len(subgraph_nodes)}} nodes\\n')
print('NODES:')
for nid in sorted(subgraph_nodes, key=lambda n: sum(1 for t in terms if t in G.nodes[n].get('label','').lower()), reverse=True)[:30]:
    d = G.nodes[nid]
    print(f'  {{d.get("label", nid)}} [{{d.get("source_file", "")}}]')
print('\\nEDGES:')
for u, v in subgraph_edges[:50]:
    if u in subgraph_nodes and v in subgraph_nodes:
        d = G.edges[u, v]
        print(f'  {{G.nodes[u].get("label", u)}} --{{d.get("relation", "")}} [{{d.get("confidence", "")}}]--> {{G.nodes[v].get("label", v)}}')
"""
        return _run(python, code, repo_root)

    if args.wiki:
        code = """
import json
from pathlib import Path
from collections import defaultdict
from networkx.readwrite import json_graph

out = Path('graphify-out')
graph_path = out / 'graph.json'
if not graph_path.exists():
    print('[graphify] No graph found. Run rebuild first.')
    raise SystemExit(1)

data = json.loads(graph_path.read_text())
G = json_graph.node_link_graph(data, edges='links')

cid_to_nodes = defaultdict(list)
for nid, ndata in G.nodes(data=True):
    cid = ndata.get('community')
    if cid is not None:
        cid_to_nodes[cid].append(nid)

labels_raw = {}
if (out / '.graphify_labels.json').exists():
    labels_raw = json.loads((out / '.graphify_labels.json').read_text())
labels = {int(k): v for k, v in labels_raw.items()} if labels_raw else {cid: f'Community {cid}' for cid in cid_to_nodes}
communities = {nid: ndata.get('community') for nid, ndata in G.nodes(data=True)}

wiki_dir = out / 'wiki'
wiki_dir.mkdir(exist_ok=True)

index_lines = ['# openVman Knowledge Graph\\n', f'Communities: {len(cid_to_nodes)}\\n\\n']
for cid, nids in sorted(cid_to_nodes.items()):
    label = labels.get(cid, f'Community {cid}')
    node_labels = [G.nodes[n].get('label', n) for n in nids[:5]]
    index_lines.append(f'- [{label}](community_{cid}.md) — {", ".join(node_labels)}\\n')
(wiki_dir / 'index.md').write_text(''.join(index_lines), encoding='utf-8')

for cid, nids in sorted(cid_to_nodes.items()):
    label = labels.get(cid, f'Community {cid}')
    lines = [f'# {label}\\n\\n', f'Nodes: {len(nids)}\\n\\n## Members\\n']
    for nid in nids:
        d = G.nodes[nid]
        lines.append(f'- **{d.get("label", nid)}** (`{d.get("source_file", "")}`)\n')
    lines.append('\\n## Connections to other communities\\n')
    cross = set()
    for nid in nids:
        for neighbor in G.neighbors(nid):
            neighbor_cid = communities.get(neighbor)
            if neighbor_cid is not None and neighbor_cid != cid:
                cross.add(labels.get(neighbor_cid, f'Community {neighbor_cid}'))
    for c in sorted(cross):
        lines.append(f'- {c}\\n')
    (wiki_dir / f'community_{cid}.md').write_text(''.join(lines), encoding='utf-8')

print(f'[graphify] Wiki: {len(cid_to_nodes)+1} pages in graphify-out/wiki/')
print('[graphify] Entry point: graphify-out/wiki/index.md')
"""
        return _run(python, code, repo_root)

    # Default: full rebuild
    exclude_json = __import__("json").dumps(list(EXCLUDE_DIRS))
    code = f"""
import json, sys
from pathlib import Path

from graphify.analyze import god_nodes, surprising_connections, suggest_questions
from graphify.build import build_from_json
from graphify.cluster import cluster, score_all
from graphify.export import to_html, to_json
from graphify.extract import collect_files, extract
from graphify.report import generate

EXCLUDE_DIRS = set(json.loads('{exclude_json}'))
watch_path = Path('.')
code_files = collect_files(watch_path, follow_symlinks=False)
code_files = [f for f in code_files if not any(p in EXCLUDE_DIRS for p in f.parts)]
print(f'[graphify] Collected {{len(code_files)}} files after filtering', file=sys.stderr)

if not code_files:
    print('[graphify] No code files found.', file=sys.stderr)
    raise SystemExit(1)

result = extract(code_files)
G = build_from_json(result)
communities = cluster(G)
cohesion = score_all(G, communities)
gods = god_nodes(G)
surprises = surprising_connections(G, communities)
labels = {{cid: f'Community {{cid}}' for cid in communities}}
questions = suggest_questions(G, communities, labels)

out = watch_path / 'graphify-out'
out.mkdir(exist_ok=True)

detection = {{
    'files': {{'code': [str(f) for f in code_files], 'document': [], 'paper': [], 'image': []}},
    'total_files': len(code_files),
    'total_words': 0,
}}
report = generate(G, communities, cohesion, labels, gods, surprises, detection,
                  {{'input': 0, 'output': 0}}, str(watch_path), suggested_questions=questions)
(out / 'GRAPH_REPORT.md').write_text(report, encoding='utf-8')
to_json(G, communities, str(out / 'graph.json'))
to_html(G, communities, str(out / 'graph.html'), community_labels=labels)

flag = out / 'needs_update'
if flag.exists():
    flag.unlink()

print(f'[graphify] Rebuilt: {{G.number_of_nodes()}} nodes, {{G.number_of_edges()}} edges, {{len(communities)}} communities')
print('[graphify] Updated graphify-out/GRAPH_REPORT.md, graph.json, graph.html')
"""
    return _run(python, code, repo_root)


if __name__ == "__main__":
    raise SystemExit(main())
