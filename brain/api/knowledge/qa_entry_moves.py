"""Validate and apply an atomic batch of quick-QA category moves."""

from __future__ import annotations

from collections import Counter, defaultdict
import posixpath
from typing import Any

from knowledge.qa_merged import (
    MergedSaveError,
    canonical_knowledge_path,
    normalized_qa_source,
)
from knowledge.qa_node_sources import _build_entries_for_source
from knowledge.qa_nodes import (
    _load_nodes_data,
    _lock,
    _referenced_source_paths,
    _save_nodes_data,
)
from knowledge.workspace import resolve_workspace_document


class QaEntryMoveError(ValueError):
    """Refusal when moving QA entries between categories, before anything is written."""

    def __init__(self, status: int, detail: str) -> None:
        super().__init__(detail)
        self.status = status
        self.detail = detail


def _format_move_questions(questions: list[str]) -> str:
    return "、".join(f"「{q}」" for q in dict.fromkeys(questions))


def _entry_source(entry: dict[str, Any]) -> str:
    source_path = entry.get("source_path")
    return posixpath.normpath(source_path) if source_path else ""


def move_qa_entries(
    to_node_id: str,
    items: list[dict[str, Any]],
    project_id: str = "default",
) -> dict[str, Any]:
    """Move or mount a batch of QA entries into ``to_node_id`` in one read and one write."""
    target_id = (to_node_id or "").strip()
    with _lock:
        data = _load_nodes_data(project_id)
        nodes = data.get("nodes", {})
        if not target_id or target_id not in nodes:
            raise QaEntryMoveError(404, "目標分類不存在")

        normalized_items: list[tuple[str, str, list[str]]] = []
        mounted_sources: set[str] | None = None
        for item in items:
            question = (item.get("question") or "").strip()
            if not question:
                raise QaEntryMoveError(400, "題目不可空白")
            raw_source = (item.get("source_path") or "").strip()
            from_ids = list(dict.fromkeys(
                fid.strip() for fid in (item.get("from_node_ids") or []) if isinstance(fid, str) and fid.strip()
            ))
            try:
                if not from_ids:
                    if not raw_source:
                        raise QaEntryMoveError(400, f"「{question}」沒有指定來源文件")
                    if mounted_sources is None:
                        mounted_sources = _referenced_source_paths(nodes)
                    source_path = normalized_qa_source(
                        raw_source, project_id, mounted_sources=mounted_sources,
                    )
                else:
                    source_path = canonical_knowledge_path(raw_source, project_id) if raw_source else ""
            except MergedSaveError as exc:
                raise QaEntryMoveError(exc.status, exc.detail) from exc
            normalized_items.append((question, source_path, from_ids))

        counts = Counter(question for question, _, _ in normalized_items)
        duplicates = [question for question, count in counts.items() if count > 1]
        if duplicates:
            raise QaEntryMoveError(
                400, f"{_format_move_questions(duplicates)}在同一批移動裡重複，同一個分類不能有相同的題目",
            )

        missing_from: list[str] = []
        missing_in_source: list[str] = []
        target_clashes: list[str] = []
        source_entries_cache: dict[str, dict[str, dict[str, Any]]] = {}
        target_sources: dict[str, set[str]] = defaultdict(set)
        for entry in nodes[target_id].get("qa_entries", []):
            target_sources[entry["question"]].add(_entry_source(entry))
        resolved_items: list[tuple[str, str, list[str], dict[str, Any]]] = []

        for question, source_path, from_ids in normalized_items:
            entry_to_keep: dict[str, Any] | None = None
            if from_ids:
                missing = False
                for fid in from_ids:
                    node = nodes.get(fid)
                    matched = next(
                        (
                            entry
                            for entry in (node.get("qa_entries", []) if node else [])
                            if entry.get("question") == question
                            and _entry_source(entry) == source_path
                        ),
                        None,
                    )
                    if matched is None:
                        missing = True
                        break
                    if entry_to_keep is None or fid == target_id:
                        entry_to_keep = dict(matched)
                if missing or entry_to_keep is None:
                    missing_from.append(question)
                    continue
            else:
                if source_path not in source_entries_cache:
                    doc_path = resolve_workspace_document(source_path, project_id)
                    if not doc_path.exists():
                        raise QaEntryMoveError(404, "找不到指定文件")
                    source_entries_cache[source_path] = {
                        entry["question"]: entry
                        for entry in _build_entries_for_source(source_path, project_id)
                    }
                found_doc_entry = source_entries_cache[source_path].get(question)
                if found_doc_entry is None:
                    missing_in_source.append(question)
                    continue
                entry_to_keep = dict(found_doc_entry)

            existing_sources = target_sources.get(question)
            if existing_sources and existing_sources != {source_path}:
                target_clashes.append(question)
                continue

            resolved_items.append((question, source_path, from_ids, entry_to_keep))

        if missing_from:
            raise QaEntryMoveError(404, f"{_format_move_questions(missing_from)}不在原本的分類裡，請重新整理")
        if missing_in_source:
            raise QaEntryMoveError(404, f"{_format_move_questions(missing_in_source)}不在來源文件裡，請重新整理")
        if target_clashes:
            raise QaEntryMoveError(400, f"{_format_move_questions(target_clashes)}在目標分類已經有相同的題目")

        updated_from_ids: list[str] = []
        target_entries = nodes[target_id].setdefault("qa_entries", [])
        for question, source_path, from_ids, entry_to_keep in resolved_items:
            # 搬移題目是換分類（或收斂多分類掛載），不是刻意把題目從選單拿下；
            # 就算拿掉後不再掛在任何分類，也不記進 detached（這點與 remove_qa_entry_from_node 不同）。
            for fid in from_ids:
                if fid == target_id:
                    continue
                if fid not in updated_from_ids:
                    updated_from_ids.append(fid)
                nodes[fid]["qa_entries"] = [
                    entry
                    for entry in nodes[fid].get("qa_entries", [])
                    if not (
                        entry.get("question") == question
                        and _entry_source(entry) == source_path
                    )
                ]
            if question not in target_sources:
                target_entries.append(entry_to_keep)
                if not from_ids and source_path:
                    detached = data.get("detached", {}).get(source_path, [])
                    if question in detached:
                        detached.remove(question)

        _save_nodes_data(data, project_id)
        return {
            "to": {**nodes[target_id], "node_id": target_id},
            "from": [{**nodes[fid], "node_id": fid} for fid in updated_from_ids],
        }
