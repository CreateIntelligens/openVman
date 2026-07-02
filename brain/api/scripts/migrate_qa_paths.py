from __future__ import annotations

import json
import shutil
import sys
from pathlib import Path

# Ensure the api package root is importable when invoked via ``python3 -m``.
_API_ROOT = Path(__file__).resolve().parents[1]
if str(_API_ROOT) not in sys.path:
    sys.path.insert(0, str(_API_ROOT))

from infra.project_context import get_data_root
from knowledge.indexer import rebuild_knowledge_index, rename_document_records
from knowledge.workspace import get_workspace_root


def _load_nodes_data(nodes_path: Path, project_id: str) -> dict | None:
    """Load .qa_nodes.json; missing file means an empty tree, invalid means abort."""
    if not nodes_path.exists():
        return {"nodes": {}}
    try:
        with open(nodes_path, "r", encoding="utf-8") as f:
            nodes_data = json.load(f)
    except Exception as exc:
        print(f"Error reading {nodes_path} for project {project_id}: {exc}", file=sys.stderr)
        return None
    if not isinstance(nodes_data, dict) or "nodes" not in nodes_data:
        print(f"Invalid QA nodes format for project: {project_id}", file=sys.stderr)
        return None
    return nodes_data


def _collect_referenced_paths(nodes_data: dict) -> set[str]:
    return {
        entry["source_path"]
        for node in nodes_data["nodes"].values()
        for entry in node.get("qa_entries", [])
        if entry.get("source_path")
    }


def _move_referenced_files(
    workspace_root: Path, referenced_paths: set[str], project_id: str
) -> dict[str, str]:
    """Move node-referenced QA md files from knowledge/ root into knowledge/qa/."""
    moved_mappings: dict[str, str] = {}
    for relative_path in sorted(referenced_paths):
        parts = relative_path.split("/")
        if not (
            relative_path.startswith("knowledge/")
            and relative_path.endswith(".md")
            and len(parts) == 2
        ):
            continue
        old_file_path = workspace_root / relative_path
        new_relative_path = f"knowledge/qa/{parts[1]}"
        new_file_path = workspace_root / new_relative_path
        if not (old_file_path.exists() and old_file_path.is_file()):
            continue
        try:
            new_file_path.parent.mkdir(parents=True, exist_ok=True)
            shutil.move(str(old_file_path), str(new_file_path))
            moved_mappings[relative_path] = new_relative_path
            print(f"[{project_id}] Moved physical file: {relative_path} -> {new_relative_path}")
        except Exception as exc:
            print(
                f"[{project_id}] Failed to move file {relative_path} to {new_relative_path}: {exc}",
                file=sys.stderr,
            )
    return moved_mappings


def _rewrite_node_references(
    nodes_path: Path, nodes_data: dict, moved_mappings: dict[str, str], project_id: str
) -> bool:
    for node in nodes_data["nodes"].values():
        for entry in node.get("qa_entries", []):
            source_path = entry.get("source_path", "")
            if source_path in moved_mappings:
                entry["source_path"] = moved_mappings[source_path]
    try:
        with open(nodes_path, "w", encoding="utf-8") as f:
            json.dump(nodes_data, f, ensure_ascii=False, indent=2)
        print(f"[{project_id}] Updated QA nodes JSON file.")
        return True
    except Exception as exc:
        print(f"[{project_id}] Failed to save {nodes_path}: {exc}", file=sys.stderr)
        return False


def _update_doc_meta(
    workspace_root: Path,
    moved_mappings: dict[str, str],
    referenced_paths: set[str],
    project_id: str,
) -> None:
    """Rename moved doc-meta entries and downgrade orphan QA docs to manual.

    A ``source_type == "qa"`` doc not referenced by any node is unreachable
    from the QA tree while the documents-API ownership guard blocks edits and
    deletion — downgrading to ``manual`` returns it to normal management.
    """
    doc_meta_path = workspace_root / ".doc_meta.json"
    if not doc_meta_path.exists():
        return
    try:
        with open(doc_meta_path, "r", encoding="utf-8") as f:
            doc_meta = json.load(f)
    except Exception as exc:
        print(f"[{project_id}] Failed to read {doc_meta_path}: {exc}", file=sys.stderr)
        return

    changed = False
    for old_path, new_path in moved_mappings.items():
        if old_path in doc_meta:
            doc_meta[new_path] = doc_meta.pop(old_path)
            changed = True

    referenced_after_move = {moved_mappings.get(path, path) for path in referenced_paths}
    for path, meta in doc_meta.items():
        if meta.get("source_type") == "qa" and path not in referenced_after_move:
            meta["source_type"] = "manual"
            changed = True
            print(f"[{project_id}] Downgraded orphan QA doc to manual: {path}")

    if not changed:
        return
    sorted_doc_meta = {key: doc_meta[key] for key in sorted(doc_meta.keys())}
    try:
        with open(doc_meta_path, "w", encoding="utf-8") as f:
            json.dump(sorted_doc_meta, f, ensure_ascii=False, indent=2)
        print(f"[{project_id}] Updated doc metadata JSON file.")
    except Exception as exc:
        print(f"[{project_id}] Failed to save {doc_meta_path}: {exc}", file=sys.stderr)


def migrate_project_qa_paths(project_id: str) -> None:
    """Migrate QA files from knowledge/ to knowledge/qa/ and update JSON metadata."""
    workspace_root = get_workspace_root(project_id)
    nodes_path = workspace_root / "knowledge" / ".qa_nodes.json"
    nodes_data = _load_nodes_data(nodes_path, project_id)
    if nodes_data is None:
        return

    referenced_paths = _collect_referenced_paths(nodes_data)
    moved_mappings = _move_referenced_files(workspace_root, referenced_paths, project_id)

    if moved_mappings and not _rewrite_node_references(
        nodes_path, nodes_data, moved_mappings, project_id
    ):
        return

    _update_doc_meta(workspace_root, moved_mappings, referenced_paths, project_id)

    if not moved_mappings:
        print(f"No QA files needed migration for project: {project_id}")
        return

    for old_path, new_path in moved_mappings.items():
        try:
            rename_document_records(old_path, new_path, project_id)
            print(f"[{project_id}] Renamed database records: {old_path} -> {new_path}")
        except Exception as exc:
            print(
                f"[{project_id}] Failed to rename document records from {old_path} to {new_path}: {exc}",
                file=sys.stderr,
            )

    try:
        rebuild_knowledge_index(project_id)
        print(f"[{project_id}] Rebuilt knowledge index.")
    except Exception as exc:
        print(f"[{project_id}] Failed to rebuild knowledge index: {exc}", file=sys.stderr)


def main() -> None:
    data_root = get_data_root()
    if not data_root.exists() or not data_root.is_dir():
        print(f"Data root {data_root} does not exist or is not a directory.", file=sys.stderr)
        sys.exit(1)

    for item in data_root.iterdir():
        if item.is_dir():
            project_id = item.name
            print(f"=== Starting migration for project: {project_id} ===")
            try:
                migrate_project_qa_paths(project_id)
            except Exception as exc:
                print(f"Migration failed for project {project_id}: {exc}", file=sys.stderr)
            print(f"=== Completed migration for project: {project_id} ===")


if __name__ == "__main__":
    main()
