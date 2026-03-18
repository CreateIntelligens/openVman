"""LanceDB 連線初始化與資料表存取。"""

from __future__ import annotations

import json
from datetime import date
from threading import Lock
from typing import Any

import lancedb

from infra.project_context import get_project_db, resolve_project_context
from memory.embedder import encode_text

_tables_ready: set[str] = set()
_tables_lock = Lock()

TABLE_SEED_TEXTS = {
    "memories": "系統初始化記錄",
    "knowledge": "知識庫初始化記錄",
}


def get_db(project_id: str = "default") -> lancedb.DBConnection:
    """取得指定專案的 LanceDB 連線。"""
    ctx = resolve_project_context(project_id)
    return get_project_db(ctx)


def ensure_tables(project_id: str = "default") -> None:
    """確保所需資料表存在，不存在則以初始資料建立。"""
    if project_id in _tables_ready:
        return

    with _tables_lock:
        if project_id in _tables_ready:
            return

        _create_missing_tables(get_db(project_id))
        _tables_ready.add(project_id)


def _create_missing_tables(db: lancedb.DBConnection) -> None:
    existing_tables = set(db.table_names())

    for table_name, seed_text in TABLE_SEED_TEXTS.items():
        if table_name in existing_tables:
            continue
        db.create_table(table_name, data=[_build_seed_record(seed_text)])


def _build_seed_record(text: str) -> dict[str, Any]:
    return {
        "text": text,
        "vector": encode_text(text),
        "source": "system",
        "date": date.today().isoformat(),
        "metadata": "{}",
    }


def get_table(table_name: str, project_id: str = "default") -> lancedb.table.Table:
    """依表名開啟 LanceDB 資料表。"""
    ensure_tables(project_id)
    return get_db(project_id).open_table(table_name)


def ensure_fts_index(table_name: str, project_id: str = "default") -> None:
    """Create a full-text search index on the text column if not already present."""
    table = get_table(table_name, project_id)
    try:
        # 確保有資料才建立索引，否則 LanceDB 可能會報錯
        if len(table) > 0:
            table.create_fts_index("text", replace=True)
    except Exception as e:
        # FTS index may already exist or not be supported in this version
        import logging
        logging.getLogger(__name__).debug(f"FTS index creation skipped/failed for {table_name}: {e}")


def get_memories_table(project_id: str = "default") -> lancedb.table.Table:
    """取得 memories 表"""
    return get_table("memories", project_id)


def get_knowledge_table(project_id: str = "default") -> lancedb.table.Table:
    """取得 knowledge 表"""
    return get_table("knowledge", project_id)


def parse_record_metadata(record: dict[str, Any]) -> dict[str, Any]:
    """Parse the JSON metadata field from a LanceDB record."""
    raw = record.get("metadata", "{}")
    if isinstance(raw, dict):
        return raw
    try:
        parsed = json.loads(str(raw))
    except json.JSONDecodeError:
        return {}
    return parsed if isinstance(parsed, dict) else {}


def normalize_vector(vector: Any) -> list[float]:
    """Ensure a vector is a plain list[float], handling numpy arrays."""
    if hasattr(vector, "tolist"):
        return vector.tolist()
    return list(vector)
