from __future__ import annotations

import json
import logging
import os
import tempfile
import threading
import time
from pathlib import Path
from typing import Any

from knowledge.qa_category_depth import (
    LANGUAGE_LABELS,
    QA_CATEGORY_DEPTH_ERROR,
    QA_CATEGORY_DEPTH_LIMIT,
    is_root_category,
    move_exceeds_depth,
    subtree_height,
    category_depth,
    is_language_label,
    language_label_code,
)
from knowledge.qa_import_placement import (
    build_node_tree,
    place_entries_by_path,
    referencing_nodes,
    source_node_can_refill,
    source_node_id as _source_node_id,
    unique_source_node_id,
)
from knowledge.qa_node_sources import _build_entries_for_source, _parse_source_items
from knowledge.workspace import ensure_workspace_scaffold, resolve_workspace_document

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


def nodes_snapshot(project_id: str = "default") -> bytes | None:
    """The nodes file as stored, for putting it back if a multi-step save fails."""
    with _lock:
        path = _get_nodes_file_path(project_id)
        return path.read_bytes() if path.exists() else None


def restore_nodes_snapshot(snapshot: bytes | None, project_id: str = "default") -> None:
    with _lock:
        path = _get_nodes_file_path(project_id)
        if snapshot is None:
            path.unlink(missing_ok=True)
        else:
            path.write_bytes(snapshot)


def source_placement_snapshot(
    source: str, project_id: str = "default",
) -> tuple[dict[str, dict[str, Any]], set[str]]:
    """Read categories and questions deliberately detached from this source together."""
    with _lock:
        data = _load_nodes_data(project_id)
        return data["nodes"], set(data.get("detached", {}).get(source, []))


def list_nodes(project_id: str = "default") -> dict[str, dict[str, Any]]:
    with _lock:
        data = _load_nodes_data(project_id)
        return data.get("nodes", {})


def get_node(node_id: str, project_id: str = "default") -> dict[str, Any] | None:
    with _lock:
        data = _load_nodes_data(project_id)
        return data.get("nodes", {}).get(node_id)


def find_language_category(language: str, project_id: str = "default") -> str | None:
    """Return the id of the first-level node named after ``language``, if there is one.

    同語言有多個分類時，取顯示中、排序最前面的。
    """
    nodes = list_nodes(project_id)
    candidates = [
        (bool(node.get("hidden", False)), node.get("order", 1.0), node_id)
        for node_id, node in nodes.items()
        if language_label_code(node.get("label", "")) == language
        and is_root_category(nodes, node)
    ]
    return min(candidates)[2] if candidates else None


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


def _next_sibling_order(nodes: dict[str, dict[str, Any]], parent_ids: list[str]) -> float:
    if parent_ids:
        sibling_ids = {cid for pid in parent_ids for cid in nodes[pid].get("child_ids", [])}
    else:
        sibling_ids = {nid for nid, node in nodes.items() if not node.get("parent_ids")}
    orders = [float(nodes[nid].get("order", 1.0)) for nid in sibling_ids if nid in nodes]
    return max(orders, default=0.0) + 1.0


def create_node(
    node_id: str,
    label: str,
    parent_ids: list[str] | None = None,
    child_ids: list[str] | None = None,
    order: float | None = None,
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
    if order is not None and not isinstance(order, (int, float)):
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

        if parent_ids:
            new_depth = max(category_depth(data["nodes"], pid) for pid in parent_ids) + 1
        else:
            new_depth = 0 if is_language_label(label) else 1
        child_height = max(
            (1 + subtree_height(data["nodes"], cid) for cid in (child_ids or [])),
            default=0,
        )
        if new_depth + child_height > QA_CATEGORY_DEPTH_LIMIT:
            raise ValueError(QA_CATEGORY_DEPTH_ERROR)

        # 沒指定就排在同層最後；固定給 1.0 會跟排序後的第一項同分，新分類掉到第二個。
        if order is None:
            order = _next_sibling_order(data["nodes"], parent_ids or [])

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


def _descendants_or_self(data: dict, ancestor_id: str) -> set[str]:
    visited: set[str] = set()
    queue = [ancestor_id]
    while queue:
        curr = queue.pop(0)
        if curr in visited:
            continue
        visited.add(curr)
        curr_node = data["nodes"].get(curr)
        if curr_node:
            queue.extend(curr_node.get("child_ids", []))
    return visited


def _is_mounted(data: dict, source_path: str, question: str) -> bool:
    return any(
        entry.get("source_path") == source_path and entry.get("question") == question
        for node in data["nodes"].values()
        for entry in node.get("qa_entries", [])
    )


def _detach_if_unmounted(data: dict, entries: list[dict[str, Any]]) -> None:
    """Remember doc questions that were taken off the menu on purpose.

    同步會把還沒掛任何節點的題目放進節點；不記下來的話，刪掉的分類裡的題目
    下次同步就跑到別的分類去了。
    """
    for entry in entries:
        source_path = entry.get("source_path")
        question = entry.get("question")
        if not source_path or _is_mounted(data, source_path, question):
            continue
        detached = data.setdefault("detached", {}).setdefault(source_path, [])
        if question not in detached:
            detached.append(question)


def _unlink_from_parents(data: dict, node_id: str) -> None:
    node = data["nodes"][node_id]
    for pid in node.get("parent_ids", []):
        if pid in data["nodes"] and node_id in data["nodes"][pid]["child_ids"]:
            data["nodes"][pid]["child_ids"].remove(node_id)


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

        _unlink_from_parents(data, node_id)

        for cid in node.get("child_ids", []):
            if cid in data["nodes"] and node_id in data["nodes"][cid]["parent_ids"]:
                data["nodes"][cid]["parent_ids"].remove(node_id)

        del data["nodes"][node_id]
        _detach_if_unmounted(data, node.get("qa_entries", []))
        _save_nodes_data(data, project_id)
        return True


def move_node(
    node_id: str, new_parent_ids: list[str], project_id: str = "default"
) -> dict[str, Any] | None:
    with _lock:
        data = _load_nodes_data(project_id)
        if node_id not in data["nodes"]:
            return None
        descendants = _descendants_or_self(data, node_id)
        for pid in new_parent_ids:
            if pid not in data["nodes"]:
                raise ValueError(f"Parent node '{pid}' does not exist in the database.")
            if pid in descendants:
                raise ValueError("Cannot move a node to itself or any of its descendants.")

        if move_exceeds_depth(data["nodes"], node_id, new_parent_ids):
            raise ValueError(QA_CATEGORY_DEPTH_ERROR)

        node = data["nodes"][node_id]
        old_parents = set(node.get("parent_ids", []))
        new_parents = set(new_parent_ids)

        for pid in old_parents - new_parents:
            if pid in data["nodes"] and node_id in data["nodes"][pid]["child_ids"]:
                data["nodes"][pid]["child_ids"].remove(node_id)
        for pid in new_parents - old_parents:
            if pid in data["nodes"] and node_id not in data["nodes"][pid]["child_ids"]:
                data["nodes"][pid]["child_ids"].append(node_id)

        node["parent_ids"] = list(new_parent_ids)
        _save_nodes_data(data, project_id)
        return node


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

        for i, sid in enumerate(sibling_ids_ordered):
            data["nodes"][sid]["order"] = float(i + 1)

        _save_nodes_data(data, project_id)
        return data["nodes"][node_id]


def get_node_tree(project_id: str = "default") -> list[dict[str, Any]]:
    with _lock:
        data = _load_nodes_data(project_id)
        return build_node_tree(data["nodes"])


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
        detached = data.get("detached", {}).get(qa_entry.get("source_path"), [])
        if qa_entry.get("question") in detached:
            detached.remove(qa_entry["question"])

        _save_nodes_data(data, project_id)
        return node


def _referenced_source_paths(nodes: dict[str, dict[str, Any]]) -> set[str]:
    return {
        entry["source_path"]
        for node in nodes.values()
        for entry in node.get("qa_entries", [])
        if entry.get("source_path")
    }


def referenced_source_paths(project_id: str = "default") -> set[str]:
    """Return every document path referenced by any node's qa_entries."""
    with _lock:
        return _referenced_source_paths(_load_nodes_data(project_id)["nodes"])


def is_source_referenced(source_path: str, project_id: str = "default") -> bool:
    """Return True if any node's qa_entries reference the given document path."""
    return source_path in referenced_source_paths(project_id)


def is_qa_document(source_path: str, project_id: str = "default") -> bool:
    """A document the QA subsystem owns: mounted on a node, or a QA document taken off the menu."""
    from knowledge.doc_meta import get_document_meta

    return (
        is_source_referenced(source_path, project_id)
        or get_document_meta(source_path, project_id).get("source_type") == "qa"
    )


def remove_qa_entry_from_node(
    node_id: str,
    question: str,
    project_id: str = "default",
    source_path: str | None = None,
) -> dict[str, Any] | None:
    """Remove a question from a node; ``source_path`` limits it to one source."""
    with _lock:
        data = _load_nodes_data(project_id)
        if node_id not in data["nodes"]:
            return None

        node = data["nodes"][node_id]
        if "qa_entries" in node:
            taken = [
                entry
                for entry in node["qa_entries"]
                if entry.get("question") == question
                and (source_path is None or (entry.get("source_path") or "") == source_path)
            ]
            node["qa_entries"] = [entry for entry in node["qa_entries"] if entry not in taken]
            _detach_if_unmounted(data, taken)

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


def refill_emptied_node(
    source_path: str, label: str, project_id: str = "default"
) -> dict[str, Any] | None:
    """Put a re-uploaded source back into the node it was first imported as.

    題目全部拿掉後分類還留著，名稱與位置可能也改過；重傳時接回去，否則會多一個同名分類，
    舊的一直空著。只認當初匯入建立的節點，其他空分類（例如拿來分組的）不動。
    """
    entries = _build_entries_for_source(source_path, project_id)
    node_id = _source_node_id(label)
    with _lock:
        data = _load_nodes_data(project_id)
        nodes = data["nodes"]
        if not source_node_can_refill(nodes, node_id):
            return None
        node = nodes[node_id]
        node["qa_entries"] = entries
        # 整份接回去了，之前刻意拿下選單的記錄不再適用。
        data.get("detached", {}).pop(source_path, None)
        _save_nodes_data(data, project_id)
        return {**node, "node_id": node_id}


def create_node_for_source(
    source_path: str,
    label: str,
    project_id: str = "default",
    parent_ids: list[str] | None = None,
) -> dict[str, Any]:
    """Create a tree node holding every question of ``source_path``.

    Returns the created node dict augmented with its ``node_id``.
    """
    entries = _build_entries_for_source(source_path, project_id)
    with _lock:
        data = _load_nodes_data(project_id)
        node_id = unique_source_node_id(set(data["nodes"]), label)
    node = create_node(
        node_id,
        label,
        parent_ids=parent_ids,
        qa_entries=entries,
        project_id=project_id,
    )
    with _lock:
        data = _load_nodes_data(project_id)
        if data.get("detached", {}).pop(source_path, None) is not None:
            _save_nodes_data(data, project_id)
    return {**node, "node_id": node_id}


def node_label(node_id: str, project_id: str = "default") -> str:
    return str((get_node(node_id, project_id) or {}).get("label", ""))


def place_questions_by_path(
    source_path: str, paths: dict[str, list[str]], project_id: str = "default",
) -> list[str]:
    """Mount each question on the node its ``path`` names, creating nodes as needed.

    已經掛在某處的題目不搬：工作人員可能拖過。刻意拿下選單的也不放回去。
    照文件順序掛入，和表格的「順序」欄一致。
    回傳因為分類裡已有同名題目而放不進去的題目，呼叫端要告訴使用者。
    """
    entries = _build_entries_for_source(source_path, project_id)
    with _lock:
        data = _load_nodes_data(project_id)
        detached = set(data.get("detached", {}).get(source_path, []))
        clashes = place_entries_by_path(data["nodes"], source_path, entries, paths, detached)
        _save_nodes_data(data, project_id)
    return clashes


def _refill_source_slots(
    entries: list[dict[str, Any]],
    source_path: str,
    replacement: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Put ``replacement`` where the source's entries were; other sources keep their place."""
    result: list[dict[str, Any]] = []
    remaining = iter(replacement)
    used = 0
    last_slot = -1
    for entry in entries:
        if entry.get("source_path") != source_path:
            result.append(entry)
            continue
        if used < len(replacement):
            result.append(next(remaining))
            used += 1
            last_slot = len(result)
    insert_at = last_slot if used else len(result)
    result[insert_at:insert_at] = list(remaining)
    return result


def _delete_emptied_nodes(data: dict[str, Any], emptied: list[str]) -> None:
    for node_id in emptied:
        node = data["nodes"][node_id]
        if not node.get("qa_entries") and not node.get("child_ids"):
            _unlink_from_parents(data, node_id)
            del data["nodes"][node_id]


def sync_entries_for_source(
    source_path: str,
    project_id: str = "default",
    delete_emptied: bool = True,
    *,
    place_unmounted: bool = True,
    keep_order: bool = False,
) -> int:
    """Bring referencing nodes in line with ``source_path``; returns how many were updated.

    Each node keeps the questions it already has, so a file split across nodes
    stays split. Questions gone from the file leave every node; hidden and image
    follow the file on every mount. A question no node has yet goes to the first
    referencing node, unless it was taken off the menu on purpose. A file that
    exists but reads as empty changes nothing: the edit may be half done, and
    dropping the entries would lose where they lived. A node only goes away with
    its entries when the file itself is gone; an edit must not delete a category.
    ``delete_emptied=False`` keeps nodes even then: saving one node must not delete
    another because their shared file went missing.
    ``place_unmounted=False`` updates existing mounts without creating new ones.
    ``keep_order=True`` keeps each node's order even when one node owns the file.
    """
    doc_entries = _build_entries_for_source(source_path, project_id)
    file_exists = resolve_workspace_document(source_path, project_id).exists()
    if not doc_entries and file_exists:
        return 0
    doc_position = {entry["question"]: position for position, entry in enumerate(doc_entries)}
    doc_by_question = {entry["question"]: entry for entry in doc_entries}

    with _lock:
        data = _load_nodes_data(project_id)
        referencing = referencing_nodes(data["nodes"], source_path)
        if not referencing:
            return 0

        mounted = {
            entry["question"]
            for node_id in referencing
            for entry in data["nodes"][node_id]["qa_entries"]
            if entry.get("source_path") == source_path and entry["question"] in doc_by_question
        }
        all_detached = data.get("detached", {})
        detached = [q for q in all_detached.get(source_path, []) if q in doc_by_question and q not in mounted]
        if detached:
            all_detached[source_path] = detached
        else:
            all_detached.pop(source_path, None)
        unmounted = [
            entry
            for entry in doc_entries
            if entry["question"] not in mounted and entry["question"] not in detached
        ]

        emptied: list[str] = []
        for position, node_id in enumerate(referencing):
            node = data["nodes"][node_id]
            seen: set[str] = set()
            kept: list[dict[str, Any]] = []
            for entry in node["qa_entries"]:
                question = entry["question"]
                if entry.get("source_path") != source_path or question not in doc_by_question or question in seen:
                    continue
                seen.add(question)
                doc_entry = doc_by_question[question]
                kept.append({**entry, "hidden": doc_entry["hidden"], "image_id": doc_entry["image_id"]})
            if position == 0 and place_unmounted:
                for doc_entry in unmounted:
                    same_text = [e for e in node["qa_entries"] if e["question"] == doc_entry["question"]]
                    # 同節點不能有兩個同文字的條目：選單專用題接上文件，別的文件的同名題就不掛。
                    if not same_text:
                        kept.append(dict(doc_entry))
                    elif not same_text[0].get("source_path"):
                        same_text[0].update(doc_entry)
                        kept.append(same_text[0])
            # 只有一個節點用這份文件時，在文件頁調整的順序要反映到選單；分給多個節點時，
            # 每個節點各自排序，照檔案排會把別的節點拖過的順序打亂。新題放在最後。
            if len(referencing) == 1 and not keep_order:
                kept.sort(key=lambda entry: doc_position[entry["question"]])
            node["qa_entries"] = _refill_source_slots(node["qa_entries"], source_path, kept)
            if not node["qa_entries"]:
                emptied.append(node_id)

        if not file_exists and delete_emptied:
            _delete_emptied_nodes(data, emptied)
        _save_nodes_data(data, project_id)
    return len(referencing)


def rename_questions_in_nodes(
    source_path: str,
    renames: dict[str, str],
    project_id: str = "default",
    except_node: str | None = None,
) -> None:
    """Follow renamed questions on the nodes that mount them.

    一次套用整份對照：逐筆改的話，甲→乙、乙→丙 會把掛甲的節點一路改成丙，答案就錯了。
    """
    with _lock:
        data = _load_nodes_data(project_id)
        for node_id, node in data["nodes"].items():
            if node_id == except_node:
                continue
            for entry in node.get("qa_entries", []):
                if entry.get("source_path") == source_path and entry.get("question") in renames:
                    entry["question"] = renames[entry["question"]]
        detached = data.get("detached", {}).get(source_path)
        if isinstance(detached, list):
            data["detached"][source_path] = [renames.get(q, q) for q in detached]
        _save_nodes_data(data, project_id)


def remove_entries_for_source(source_path: str, project_id: str = "default") -> None:
    """Remove all qa_entries referencing ``source_path``; nodes left empty by that go too."""
    with _lock:
        data = _load_nodes_data(project_id)
        emptied: list[str] = []
        for node_id, node in data["nodes"].items():
            entries = node.get("qa_entries", [])
            filtered = [e for e in entries if e.get("source_path") != source_path]
            if len(filtered) == len(entries):
                continue
            node["qa_entries"] = filtered
            if not filtered:
                emptied.append(node_id)

        data.get("detached", {}).pop(source_path, None)
        _delete_emptied_nodes(data, emptied)
        _save_nodes_data(data, project_id)


def rename_source_path_in_nodes(
    source_path: str, target_path: str, project_id: str = "default"
) -> None:
    """Update all entries referencing ``source_path`` to point to ``target_path``.

    Also renames the node label if it matches the old file stem.
    """
    with _lock:
        data = _load_nodes_data(project_id)
        old_stem = Path(source_path).stem
        new_stem = Path(target_path).stem

        updated = False
        for node in data["nodes"].values():
            for entry in node.get("qa_entries", []):
                if entry.get("source_path") == source_path:
                    entry["source_path"] = target_path
                    updated = True
            if node.get("label") == old_stem:
                node["label"] = new_stem
                updated = True
        detached = data.get("detached", {})
        if source_path in detached:
            detached[target_path] = detached.pop(source_path)
            updated = True

        if updated:
            _save_nodes_data(data, project_id)


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

        # 刪節點不刪文件，所以沒掛節點的 QA 文件仍會被問到，它引用的圖不能算沒用到。
        from knowledge.doc_meta import load_doc_meta
        from knowledge.qa_csv import extract_image_id

        for path, meta in load_doc_meta(project_id).items():
            if meta.get("source_type") != "qa":
                continue
            # 看所有列：沒題目的列與重複題進不了選單，但索引照樣收，圖一樣會被回答用到。
            for item in _parse_source_items(path, project_id):
                image_id = extract_image_id(item.get("img") or "")
                if image_id:
                    used_image_ids.add(image_id)

        # 人設的聯絡圖片（例如每則回覆都附的 QR code）沒有掛在任何 QA 上，也算用到。
        from personas.personas import persona_contact_image_ids

        used_image_ids |= persona_contact_image_ids(project_id)

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
