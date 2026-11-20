"""Compute per-category indexing sync status for Quick Q&A.

每個分類只看直接掛在它上面的題目（``qa_entries``），不往下合併子分類：
- 選單專用題（沒有 ``source_path``）略過。
- 只看可索引且沒停用的文件；全部都在索引裡或沒有要看的文件即為 ``synced``。
- 有文件不在索引裡時：
  - 專案 ``pending`` 或 ``running`` → ``updating``。
  - 否則 ``last_error`` 有值 → ``failed``。
  - 兩者都不是（例如剛重啟清空記憶體狀態，或外部改了檔沒排重建）→ 標記需補排一次
    背景重建（刻意的自我修復），回 ``updating``。
"""

from __future__ import annotations

import posixpath
from collections.abc import Callable
from pathlib import Path
from typing import Any

from knowledge.doc_meta import _resolved_entry, load_doc_meta
from knowledge.indexer import fingerprint_document, load_index_state
from knowledge.qa_nodes import list_nodes
from knowledge.workspace import (
    ALLOWED_INDEX_SUFFIXES,
    ensure_workspace_scaffold,
    is_indexable_document,
)


def _normalize_source_path(source_path: str) -> str | None:
    cleaned = source_path.strip()
    if not cleaned:
        return None
    normalized = posixpath.normpath(cleaned)
    if not normalized or normalized in {".", ".."} or normalized.startswith(("/", "../")):
        return None
    return normalized


def _source_is_synced_or_ignored(
    normalized: str,
    *,
    project_id: str,
    root: Path,
    real_root: Path,
    index_state: dict[str, str],
    doc_meta: dict[str, dict[str, Any]],
) -> bool:
    """Return True if the file is ignored (not indexable / disabled / absent) or up to date."""
    path = root / normalized
    if path.suffix.lower() not in ALLOWED_INDEX_SUFFIXES:
        return True
    try:
        # 與 iter_indexable_documents 一致：符號連結、經過連結資料夾、硬連結與不存在的檔案
        # 不會進索引，不能算成未同步，否則每次輪詢都會重複觸發自我修復重建。
        if path.is_symlink() or not path.is_file():
            return True
        if path.resolve(strict=True) != real_root / normalized:
            return True
        if path.stat().st_nlink > 1:
            return True
    except (OSError, RuntimeError, ValueError):
        return True

    if not is_indexable_document(path, project_id, root=root):
        return True

    raw_meta = doc_meta.get(normalized, {})
    if not _resolved_entry(raw_meta)["enabled"]:
        return True

    stored_fp = index_state.get(normalized, "")
    if not stored_fp:
        return False
    try:
        return stored_fp == fingerprint_document(path)
    except OSError:
        return True


def compute_qa_sync_status(
    project_id: str = "default",
    *,
    status: dict[str, Any],
    visible: Callable[[str], bool] | None = None,
) -> tuple[dict[str, str], bool]:
    """Compute ``({node_id: status}, needs_reindex)`` for every Q&A category.

    ``visible`` 供廠商請求傳入 ``visible_workspace_path``，過濾規則與 ``_vendor_node`` 一致：
    對廠商只看可見來源文件；只含隱藏來源的分類在過濾後沒有要檢查的文件，一律回 ``synced``，
    既不洩漏隱藏來源的失敗狀態，也不讓廠商從分類鍵值有無反推隱藏題目的存在，同時不會因隱藏
    檔案觸發自我修復重建。
    """
    nodes = list_nodes(project_id)
    if not nodes:
        return {}, False

    root = ensure_workspace_scaffold(project_id)
    real_root = root.resolve()
    index_state = load_index_state(project_id)
    doc_meta = load_doc_meta(project_id)

    pending = bool(status.get("pending"))
    running = bool(status.get("running"))
    last_error = status.get("last_error")

    # 同一份文件可能被多個分類引用；每次請求對每份文件只做一次指紋比對並共用結果。
    file_synced: dict[str, bool] = {}

    def is_synced(normalized: str) -> bool:
        cached = file_synced.get(normalized)
        if cached is not None:
            return cached
        result = _source_is_synced_or_ignored(
            normalized,
            project_id=project_id,
            root=root,
            real_root=real_root,
            index_state=index_state,
            doc_meta=doc_meta,
        )
        file_synced[normalized] = result
        return result

    categories: dict[str, str] = {}
    needs_reindex = False

    for node_id, node in nodes.items():
        sources: list[str] = []
        seen_sources: set[str] = set()
        for entry in node.get("qa_entries", []):
            raw_source = entry.get("source_path") or ""
            if not raw_source:
                continue
            if visible is not None and not visible(raw_source):
                continue
            normalized = _normalize_source_path(raw_source)
            if normalized is None or normalized in seen_sources:
                continue
            seen_sources.add(normalized)
            sources.append(normalized)

        has_stale = any(not is_synced(source) for source in sources)
        if not has_stale:
            categories[node_id] = "synced"
        elif pending or running:
            categories[node_id] = "updating"
        elif last_error:
            categories[node_id] = "failed"
        else:
            # 刻意的自我修復：有可索引且啟用的文件不在索引裡，但記憶體沒有
            # pending／running／last_error（通常是服務剛重啟清空記憶體狀態，或別的流程
            # 直接改了檔沒排重建）。由呼叫端補排一次 schedule_reindex(project_id) 並先回
            # updating；重建本來就會合併同專案請求，重複呼叫不會跑兩次。
            needs_reindex = True
            categories[node_id] = "updating"

    return categories, needs_reindex
