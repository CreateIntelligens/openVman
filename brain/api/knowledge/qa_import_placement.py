"""Shared category lookup for QA placement and its read-only preview."""

from __future__ import annotations

import unicodedata
from typing import Any

from knowledge.qa_category_depth import is_root_category


def source_node_id(label: str) -> str:
    slug = "".join(ch if ch.isalnum() else "_" for ch in label.lower()).strip("_")
    slug = "_".join(part for part in slug.split("_") if part) or "node"
    return f"qa_{slug}"


def unique_source_node_id(existing: set[str], label: str) -> str:
    base = candidate = source_node_id(label)
    suffix = 2
    while candidate in existing:
        candidate = f"{base}_{suffix}"
        suffix += 1
    return candidate


def source_node_can_refill(nodes: dict[str, dict[str, Any]], node_id: str) -> bool:
    node = nodes.get(node_id)
    return node is not None and not node.get("qa_entries") and not node.get("child_ids")


def referencing_nodes(nodes: dict[str, dict[str, Any]], source: str) -> list[str]:
    """Put the category with the most existing mounts first, keeping ties in tree storage order."""
    counts = {
        node_id: sum(entry.get("source_path") == source for entry in node.get("qa_entries", []))
        for node_id, node in nodes.items()
    }
    return sorted((node_id for node_id, count in counts.items() if count), key=lambda nid: -counts[nid])


def _label_key(label: str) -> str:
    return unicodedata.normalize("NFKC", label).strip().casefold()


def _siblings(nodes: dict[str, dict[str, Any]], parent: str | None) -> list[str]:
    if parent is None:
        return [nid for nid, node in nodes.items() if is_root_category(nodes, node)]
    return [nid for nid in nodes[parent].get("child_ids", []) if nid in nodes]


def _matching_sibling(nodes: dict[str, dict[str, Any]], siblings: list[str], label: str) -> str | None:
    wanted = _label_key(label)
    matches = (nid for nid in siblings if _label_key(str(nodes[nid].get("label", ""))) == wanted)
    # 同名分類優先找顯示中的分類，訪客才看得到。
    return min(matches, key=lambda nid: bool(nodes[nid].get("hidden", False)), default=None)


def ensure_path_node(nodes: dict[str, dict[str, Any]], parts: list[str]) -> str:
    """Resolve the category path, creating missing categories in the supplied tree."""
    parent = None
    for part in parts:
        siblings = _siblings(nodes, parent)
        found = _matching_sibling(nodes, siblings, part)
        if found is None:
            found = unique_source_node_id(set(nodes), part)
            nodes[found] = {
                "label": part,
                "parent_ids": [parent] if parent else [],
                "child_ids": [],
                "order": max((float(nodes[nid].get("order", 1.0)) for nid in siblings), default=0.0) + 1.0,
                "hidden": False,
                "qa_entries": [],
            }
            if parent:
                nodes[parent].setdefault("child_ids", []).append(found)
        parent = found
    return str(parent)


def place_entries_by_path(
    nodes: dict[str, dict[str, Any]],
    source: str,
    entries: list[dict[str, Any]],
    paths: dict[str, list[str]],
    detached: set[str],
) -> list[str]:
    """Apply path placements to the supplied tree and return its name clashes."""
    mounted = {
        entry["question"]
        for node in nodes.values()
        for entry in node.get("qa_entries", [])
        if entry.get("source_path") == source
    }
    clashes: list[str] = []
    for entry in entries:
        question = entry["question"]
        parts = paths.get(question)
        if not parts or question in detached or question in mounted:
            continue
        node = nodes[ensure_path_node(nodes, parts)]
        if any(other["question"] == question for other in node.get("qa_entries", [])):
            clashes.append(question)
            continue
        node.setdefault("qa_entries", []).append(dict(entry))
        mounted.add(question)
    return clashes


def build_node_tree(nodes: dict[str, dict[str, Any]]) -> list[dict[str, Any]]:
    roots = []
    for nid, node in nodes.items():
        parents = node.get("parent_ids", [])
        is_root = not parents or all(p not in nodes for p in parents)
        if is_root:
            roots.append((nid, node))

    roots.sort(key=lambda item: item[1].get("order", 1.0))

    def build_subtree(node_id: str, visited_path: set[str]) -> dict[str, Any]:
        node = nodes[node_id]
        tree_node = {
            "node_id": node_id,
            "label": node.get("label", ""),
            "parent_ids": list(node.get("parent_ids", [])),
            "child_ids": list(node.get("child_ids", [])),
            "order": node.get("order", 1.0),
            "hidden": node.get("hidden", False),
            "qa_entries": list(node.get("qa_entries", [])),
            "children": [],
        }

        if node_id in visited_path:
            return tree_node

        new_visited = visited_path | {node_id}

        children_nodes = []
        for cid in node.get("child_ids", []):
            if cid in nodes:
                children_nodes.append((cid, nodes[cid]))

        children_nodes.sort(key=lambda x: x[1].get("order", 1.0))

        for cid, _ in children_nodes:
            tree_node["children"].append(build_subtree(cid, new_visited))

        return tree_node

    result = []
    for rid, _ in roots:
        result.append(build_subtree(rid, set()))

    return result
