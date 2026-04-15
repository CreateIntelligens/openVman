## graphify

This project uses [graphify](https://github.com/safishamsi/graphify) to generate knowledge graphs from the codebase and documentation.

### Setup

```bash
pip install graphifyy
```

### Generated Artifacts

| Path | Description |
|------|-------------|
| `graphify-out/GRAPH_REPORT.md` | Text summary: god nodes, communities, surprising connections |
| `graphify-out/graph.json` | Raw graph data (nodes + edges) |
| `graphify-out/graph.html` | Interactive visual graph — open in browser |
| `docs/graphify-out/` | Same outputs but for `docs/*.md` only |

### Rebuild Commands

```bash
# Rebuild code graph (brain/ backend/ frontend/ — excludes dist, node_modules, .superpowers, etc.)
python3 scripts/rebuild_graphify.py

# Rebuild docs knowledge graph (docs/*.md only — concepts, headings, cross-doc similarity)
python3 scripts/rebuild_graphify_docs.py
```

### Rules for AI Agents
- Before answering architecture or codebase questions, read `graphify-out/GRAPH_REPORT.md` for god nodes and community structure
- If `graphify-out/wiki/index.md` exists, navigate it instead of reading raw files
- After modifying code files in this session, run `python3 scripts/rebuild_graphify.py` to keep `GRAPH_REPORT.md`, `graph.json`, and `graph.html` current
