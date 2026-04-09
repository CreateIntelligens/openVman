#!/usr/bin/env python3
from __future__ import annotations

import shutil
import subprocess
import sys
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

    inline = """
from pathlib import Path
import sys

from graphify.analyze import god_nodes, surprising_connections, suggest_questions
from graphify.build import build_from_json
from graphify.cluster import cluster, score_all
from graphify.export import to_html, to_json
from graphify.extract import collect_files, extract
from graphify.report import generate

watch_path = Path('.')
code_files = collect_files(watch_path, follow_symlinks=False)
code_files = [
    f for f in code_files
    if 'graphify-out' not in f.parts and '__pycache__' not in f.parts
]

if not code_files:
    print('[graphify rebuild] No code files found.', file=sys.stderr)
    raise SystemExit(1)

result = extract(code_files)
G = build_from_json(result)
communities = cluster(G)
cohesion = score_all(G, communities)
gods = god_nodes(G)
surprises = surprising_connections(G, communities)
labels = {cid: f'Community {cid}' for cid in communities}
questions = suggest_questions(G, communities, labels)

out = watch_path / 'graphify-out'
out.mkdir(exist_ok=True)

detection = {
    'files': {'code': [str(f) for f in code_files], 'document': [], 'paper': [], 'image': []},
    'total_files': len(code_files),
    'total_words': 0,
}

report = generate(
    G,
    communities,
    cohesion,
    labels,
    gods,
    surprises,
    detection,
    {'input': 0, 'output': 0},
    str(watch_path),
    suggested_questions=questions,
)
(out / 'GRAPH_REPORT.md').write_text(report, encoding='utf-8')
to_json(G, communities, str(out / 'graph.json'))
to_html(G, communities, str(out / 'graph.html'), community_labels=labels)

flag = out / 'needs_update'
if flag.exists():
    flag.unlink()

print(
    f'[graphify rebuild] Rebuilt: {G.number_of_nodes()} nodes, '
    f'{G.number_of_edges()} edges, {len(communities)} communities'
)
print('[graphify rebuild] Updated graphify-out/GRAPH_REPORT.md, graph.json, graph.html')
"""

    result = subprocess.run(
        [str(graphify_python), "-c", inline],
        cwd=repo_root,
        text=True,
    )
    return result.returncode


if __name__ == "__main__":
    raise SystemExit(main())
