from __future__ import annotations

import json
import logging
import os
from pathlib import Path
import tempfile
import threading
import time
from typing import Any

from knowledge.workspace import ensure_workspace_scaffold

logger = logging.getLogger(__name__)


_lock = threading.RLock()


def _get_nodes_file_path(project_id: str = "default") -> Path:
    return ensure_workspace_scaffold(project_id) / "knowledge" / ".qa_nodes.json"


def _load_nodes_data(project_id: str = "default") -> dict[str, Any]:
    path = _get_nodes_file_path(project_id)
    if not path.exists():
        return {"nodes": {}}

    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
    except json.JSONDecodeError as e:
        raise ValueError(f"Failed to parse QA nodes file at {path}: {e}") from e
    except Exception as e:
        raise ValueError(f"Failed to read QA nodes file at {path}: {e}") from e

    if not isinstance(data, dict) or "nodes" not in data:
        raise ValueError(
            f"Invalid format in QA nodes file at {path}: must be a JSON object containing 'nodes' key."
        )

    return data


def _save_nodes_data(data: dict[str, Any], project_id: str = "default") -> None:
    path = _get_nodes_file_path(project_id)
    path.parent.mkdir(parents=True, exist_ok=True)

    dir_path = path.parent
    with tempfile.NamedTemporaryFile(
        mode="w",
        dir=dir_path,
        delete=False,
        encoding="utf-8",
        prefix=".qa_nodes_tmp_",
        suffix=".json",
    ) as tf:
        json.dump(data, tf, ensure_ascii=False, indent=2)
        temp_name = tf.name

    try:
        os.replace(temp_name, path)
    except Exception as e:
        if os.path.exists(temp_name):
            os.remove(temp_name)
        raise e


def list_nodes(project_id: str = "default") -> dict[str, dict[str, Any]]:
    with _lock:
        data = _load_nodes_data(project_id)
        return data.get("nodes", {})


def get_node(node_id: str, project_id: str = "default") -> dict[str, Any] | None:
    with _lock:
        data = _load_nodes_data(project_id)
        return data.get("nodes", {}).get(node_id)


def _validate_string_list(value: object, field_name: str) -> None:
    if value is None:
        return
    if not isinstance(value, list) or not all(isinstance(item, str) for item in value):
        raise ValueError(f"{field_name} must be a list of strings.")


def _validate_qa_entries(value: object) -> None:
    if value is None:
        return
    if not isinstance(value, list):
        raise ValueError("qa_entries must be a list.")
    for entry in value:
        if not isinstance(entry, dict):
            raise ValueError("Each entry in qa_entries must be a dictionary.")
        if "question" not in entry or not isinstance(entry["question"], str):
            raise ValueError("qa_entry must contain a 'question' string.")


def _upsert_qa_entry(
    entries: list[dict[str, Any]],
    qa_entry: dict[str, Any],
) -> None:
    question = qa_entry.get("question", "")
    source_path = qa_entry.get("source_path", "")
    hidden = bool(qa_entry.get("hidden", False))
    image_id = qa_entry.get("image_id", None)

    for entry in entries:
        if entry.get("question") == question:
            entry["source_path"] = source_path
            entry["hidden"] = hidden
            entry["image_id"] = image_id
            return

    entries.append(
        {
            "question": question,
            "source_path": source_path,
            "hidden": hidden,
            "image_id": image_id,
        }
    )


def create_node(
    node_id: str,
    label: str,
    parent_ids: list[str] | None = None,
    child_ids: list[str] | None = None,
    order: float = 1.0,
    hidden: bool = False,
    qa_entries: list[dict[str, Any]] | None = None,
    project_id: str = "default",
) -> dict[str, Any]:
    if not isinstance(node_id, str) or not node_id:
        raise ValueError("node_id must be a non-empty string.")
    if not isinstance(label, str):
        raise ValueError("label must be a string.")
    _validate_string_list(parent_ids, "parent_ids")
    _validate_string_list(child_ids, "child_ids")
    if not isinstance(order, (int, float)):
        raise ValueError("order must be a float or integer.")
    if not isinstance(hidden, bool):
        raise ValueError("hidden must be a boolean.")
    _validate_qa_entries(qa_entries)

    with _lock:
        data = _load_nodes_data(project_id)
        if node_id in data["nodes"]:
            raise ValueError(f"node_id '{node_id}' already exists.")

        for pid in parent_ids or []:
            if pid not in data["nodes"]:
                raise ValueError(f"Parent node '{pid}' does not exist in the database.")
        for cid in child_ids or []:
            if cid not in data["nodes"]:
                raise ValueError(f"Child node '{cid}' does not exist in the database.")

        node = {
            "label": label,
            "parent_ids": list(parent_ids) if parent_ids is not None else [],
            "child_ids": list(child_ids) if child_ids is not None else [],
            "order": float(order),
            "hidden": bool(hidden),
            "qa_entries": list(qa_entries) if qa_entries is not None else [],
        }

        data["nodes"][node_id] = node

        for pid in node["parent_ids"]:
            if node_id not in data["nodes"][pid]["child_ids"]:
                data["nodes"][pid]["child_ids"].append(node_id)

        for cid in node["child_ids"]:
            if node_id not in data["nodes"][cid]["parent_ids"]:
                data["nodes"][cid]["parent_ids"].append(node_id)

        _save_nodes_data(data, project_id)
        return node


def update_node(
    node_id: str, updates: dict[str, Any], project_id: str = "default"
) -> dict[str, Any] | None:
    if not isinstance(updates, dict):
        raise ValueError("updates must be a dictionary.")
    if "label" in updates and not isinstance(updates["label"], str):
        raise ValueError("label must be a string.")
    if "parent_ids" in updates:
        _validate_string_list(updates["parent_ids"], "parent_ids")
    if "child_ids" in updates:
        _validate_string_list(updates["child_ids"], "child_ids")
    if "order" in updates and not isinstance(updates["order"], (int, float)):
        raise ValueError("order must be a float or integer.")
    if "hidden" in updates and not isinstance(updates["hidden"], bool):
        raise ValueError("hidden must be a boolean.")
    if "qa_entries" in updates:
        _validate_qa_entries(updates["qa_entries"])

    with _lock:
        data = _load_nodes_data(project_id)
        if node_id not in data["nodes"]:
            return None

        node = data["nodes"][node_id]

        if "parent_ids" in updates:
            for pid in updates["parent_ids"]:
                if pid not in data["nodes"]:
                    raise ValueError(f"Parent node '{pid}' does not exist in the database.")
        if "child_ids" in updates:
            for cid in updates["child_ids"]:
                if cid not in data["nodes"]:
                    raise ValueError(f"Child node '{cid}' does not exist in the database.")

        if "parent_ids" in updates:
            old_parents = set(node.get("parent_ids", []))
            new_parents = set(updates["parent_ids"])

            for pid in old_parents - new_parents:
                if pid in data["nodes"] and node_id in data["nodes"][pid]["child_ids"]:
                    data["nodes"][pid]["child_ids"].remove(node_id)

            for pid in new_parents:
                if pid in data["nodes"] and node_id not in data["nodes"][pid]["child_ids"]:
                    data["nodes"][pid]["child_ids"].append(node_id)

        if "child_ids" in updates:
            old_children = set(node.get("child_ids", []))
            new_children = set(updates["child_ids"])

            for cid in old_children - new_children:
                if cid in data["nodes"] and node_id in data["nodes"][cid]["parent_ids"]:
                    data["nodes"][cid]["parent_ids"].remove(node_id)

            for cid in new_children:
                if cid in data["nodes"] and node_id not in data["nodes"][cid]["parent_ids"]:
                    data["nodes"][cid]["parent_ids"].append(node_id)

        for k, v in updates.items():
            if k in ("parent_ids", "child_ids"):
                node[k] = list(v)
            elif k == "order":
                node[k] = float(v)
            elif k == "hidden":
                node[k] = bool(v)
            elif k == "qa_entries":
                node[k] = list(v)
            else:
                node[k] = v

        _save_nodes_data(data, project_id)
        return node


def delete_node(node_id: str, project_id: str = "default") -> bool:
    with _lock:
        data = _load_nodes_data(project_id)
        if node_id not in data["nodes"]:
            return False

        node = data["nodes"][node_id]

        for pid in node.get("parent_ids", []):
            if pid in data["nodes"] and node_id in data["nodes"][pid]["child_ids"]:
                data["nodes"][pid]["child_ids"].remove(node_id)

        for cid in node.get("child_ids", []):
            if cid in data["nodes"] and node_id in data["nodes"][cid]["parent_ids"]:
                data["nodes"][cid]["parent_ids"].remove(node_id)

        del data["nodes"][node_id]
        _save_nodes_data(data, project_id)
        return True


def move_node(
    node_id: str, new_parent_ids: list[str], project_id: str = "default"
) -> dict[str, Any] | None:
    with _lock:
        return update_node(node_id, {"parent_ids": new_parent_ids}, project_id)


def reorder_node(
    node_id: str, sibling_ids_ordered: list[str], project_id: str = "default"
) -> dict[str, Any] | None:
    with _lock:
        data = _load_nodes_data(project_id)
        if node_id not in data["nodes"]:
            return None

        for sid in sibling_ids_ordered:
            if sid not in data["nodes"]:
                raise ValueError(f"Sibling node '{sid}' does not exist in the database.")

        if node_id not in sibling_ids_ordered:
            return data["nodes"][node_id]

        idx = sibling_ids_ordered.index(node_id)

        def get_order_of_node(sid: str) -> float:
            return data["nodes"][sid].get(
                "order", float(sibling_ids_ordered.index(sid))
            )

        need_rebalance = False
        if len(sibling_ids_ordered) == 1:
            new_order = 1.0
        elif idx == 0:
            sibling_after = sibling_ids_ordered[1]
            order_after = get_order_of_node(sibling_after)
            new_order = order_after - 1.0
        elif idx == len(sibling_ids_ordered) - 1:
            sibling_before = sibling_ids_ordered[idx - 1]
            order_before = get_order_of_node(sibling_before)
            new_order = order_before + 1.0
        else:
            sibling_before = sibling_ids_ordered[idx - 1]
            sibling_after = sibling_ids_ordered[idx + 1]
            order_before = get_order_of_node(sibling_before)
            order_after = get_order_of_node(sibling_after)

            if order_after - order_before < 1e-9:
                need_rebalance = True
                new_order = float(idx + 1)
            else:
                new_order = (order_before + order_after) / 2.0

        if need_rebalance:
            for i, sid in enumerate(sibling_ids_ordered):
                data["nodes"][sid]["order"] = float(i + 1)
            _save_nodes_data(data, project_id)
            return data["nodes"][node_id]
        else:
            return update_node(node_id, {"order": new_order}, project_id)


def get_node_tree(project_id: str = "default") -> list[dict[str, Any]]:
    with _lock:
        data = _load_nodes_data(project_id)
        nodes = data.get("nodes", {})

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


def add_qa_entry_to_node(
    node_id: str, qa_entry: dict[str, Any], project_id: str = "default"
) -> dict[str, Any] | None:
    with _lock:
        data = _load_nodes_data(project_id)
        if node_id not in data["nodes"]:
            return None

        node = data["nodes"][node_id]
        if "qa_entries" not in node:
            node["qa_entries"] = []

        _upsert_qa_entry(node["qa_entries"], qa_entry)

        _save_nodes_data(data, project_id)
        return node


def remove_qa_entry_from_node(
    node_id: str, question: str, project_id: str = "default"
) -> dict[str, Any] | None:
    with _lock:
        data = _load_nodes_data(project_id)
        if node_id not in data["nodes"]:
            return None

        node = data["nodes"][node_id]
        if "qa_entries" in node:
            node["qa_entries"] = [
                entry
                for entry in node["qa_entries"]
                if entry.get("question") != question
            ]

        _save_nodes_data(data, project_id)
        return node


def add_qa_entries_to_node(
    node_id: str, qa_entries: list[dict[str, Any]], project_id: str = "default"
) -> dict[str, Any] | None:
    with _lock:
        data = _load_nodes_data(project_id)
        if node_id not in data["nodes"]:
            return None

        node = data["nodes"][node_id]
        if "qa_entries" not in node:
            node["qa_entries"] = []

        for qa_entry in qa_entries:
            _upsert_qa_entry(node["qa_entries"], qa_entry)

        _save_nodes_data(data, project_id)
        return node


def cleanup_unused_images(project_id: str = "default") -> list[str]:
    with _lock:
        data = _load_nodes_data(project_id)
        nodes = data.get("nodes", {})

        used_image_ids = set()
        for node in nodes.values():
            for entry in node.get("qa_entries", []):
                image_id = entry.get("image_id")
                if image_id:
                    used_image_ids.add(image_id)

        images_dir = ensure_workspace_scaffold(project_id) / "knowledge" / ".qa_images"
        if not images_dir.exists() or not images_dir.is_dir():
            return []

        deleted_files = []
        for file_path in images_dir.iterdir():
            if file_path.is_file():
                if (
                    file_path.name not in used_image_ids
                    and file_path.stem not in used_image_ids
                ):
                    try:
                        if time.time() - file_path.stat().st_mtime > 600:
                            file_path.unlink()
                            deleted_files.append(str(file_path))
                    except Exception as e:
                        logger.warning(
                            "Failed to delete unused image file %s: %s",
                            file_path,
                            e,
                        )
        return deleted_files
