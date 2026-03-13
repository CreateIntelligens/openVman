"""LanceDB 連線初始化與資料表存取。"""

from datetime import date
from threading import Lock
from typing import Any

import lancedb

from config import get_settings
from embedder import encode_text

_db: lancedb.DBConnection | None = None
_tables_ready = False
_tables_lock = Lock()

TABLE_SEED_TEXTS = {
    "memories": "系統初始化記錄",
    "knowledge": "知識庫初始化記錄",
}


def get_db() -> lancedb.DBConnection:
    """Singleton 取得 LanceDB 連線。"""
    global _db
    if _db is not None:
        return _db

    cfg = get_settings()
    _db = lancedb.connect(cfg.lancedb_resolved_path)
    return _db


def ensure_tables() -> None:
    """確保所需資料表存在，不存在則以初始資料建立。"""
    global _tables_ready
    if _tables_ready:
        return

    with _tables_lock:
        if _tables_ready:
            return

        _create_missing_tables(get_db())
        _tables_ready = True


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


def get_table(table_name: str) -> lancedb.table.Table:
    """依表名開啟 LanceDB 資料表。"""
    ensure_tables()
    return get_db().open_table(table_name)


def get_memories_table() -> lancedb.table.Table:
    """取得 memories 表"""
    return get_table("memories")


def get_knowledge_table() -> lancedb.table.Table:
    """取得 knowledge 表"""
    return get_table("knowledge")
