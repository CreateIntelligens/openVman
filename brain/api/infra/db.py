"""LanceDB 連線初始化與資料表存取。"""

from __future__ import annotations

from datetime import date
import hashlib
import json
from threading import Lock
from typing import TYPE_CHECKING, Any

from config import get_settings
from infra.project_context import get_project_db, resolve_project_context
from memory.embedder import encode_text

if TYPE_CHECKING:
    import lancedb

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


def ensure_tables(
    project_id: str = "default",
    embedding_version: str | None = None,
) -> None:
    """確保所需資料表存在，不存在則以初始資料建立。"""
    table_key = _table_cache_key(project_id, embedding_version)
    if table_key in _tables_ready:
        return

    with _tables_lock:
        if table_key in _tables_ready:
            return

        _create_missing_tables(get_db(project_id), embedding_version)
        _tables_ready.add(table_key)


def _create_missing_tables(
    db: lancedb.DBConnection,
    embedding_version: str | None = None,
) -> None:
    existing_tables = set(db.table_names())

    for logical_name, seed_text in TABLE_SEED_TEXTS.items():
        physical_name = resolve_vector_table_name(logical_name, embedding_version)
        if physical_name in existing_tables:
            continue
        db.create_table(
            physical_name,
            data=[_build_seed_record(seed_text, embedding_version)],
        )


def _build_seed_record(
    text: str,
    embedding_version: str | None = None,
) -> dict[str, Any]:
    cfg = get_settings()
    value = embedding_version or cfg.resolved_embedding_active_version
    resolver = getattr(cfg, "resolve_embedding_identity", None)
    identity = (
        resolver(value, input_semantics="document")
        if callable(resolver)
        else value
    )
    return {
        "text": text,
        "vector": encode_text(text, embedding_version),
        "source": "system",
        "date": date.today().isoformat(),
        "metadata": json.dumps({"embedding_identity": identity}),
    }


def get_table(
    table_name: str,
    project_id: str = "default",
    embedding_version: str | None = None,
) -> lancedb.table.Table:
    """依表名開啟 LanceDB 資料表。"""
    ensure_tables(project_id, embedding_version)
    return get_db(project_id).open_table(
        resolve_vector_table_name(table_name, embedding_version)
    )


def ensure_fts_index(
    table_name: str,
    project_id: str = "default",
    embedding_version: str | None = None,
) -> None:
    """Create a full-text search index on the text column if not already present."""
    table = get_table(table_name, project_id, embedding_version)
    try:
        # 確保有資料才建立索引，否則 LanceDB 可能會報錯
        if len(table) > 0:
            table.create_fts_index("text", replace=True)
    except Exception as e:
        # FTS index may already exist or not be supported in this version
        import logging
        logging.getLogger(__name__).debug(f"FTS index creation skipped/failed for {table_name}: {e}")


def get_memories_table(
    project_id: str = "default",
    embedding_version: str | None = None,
) -> lancedb.table.Table:
    """取得 memories 表"""
    return get_table("memories", project_id, embedding_version)


def get_knowledge_table(
    project_id: str = "default",
    embedding_version: str | None = None,
) -> lancedb.table.Table:
    """取得 knowledge 表"""
    return get_table("knowledge", project_id, embedding_version)


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


def resolve_vector_table_name(
    table_name: str,
    embedding_version: str | None = None,
) -> str:
    """Resolve a logical table name to the active embedding version's physical table name."""
    logical_name = table_name.strip()
    if logical_name not in TABLE_SEED_TEXTS:
        raise ValueError(f"未知的向量資料表: {table_name}")
    cfg = get_settings()
    raw_version = (
        (embedding_version or "").strip()
        or getattr(cfg, "resolved_embedding_write_identity", "")
        or cfg.resolved_embedding_active_version
    )
    version = raw_version.lower()
    if version == "default":
        version = "bge"

    aliases = getattr(cfg, "resolved_embedding_identity_aliases", {})
    compatible_legacy = getattr(
        cfg,
        "resolved_embedding_compatible_legacy_identities",
        set(),
    )
    if version in aliases:
        canonical = aliases[version]
    elif ":" in raw_version:
        canonical = raw_version
    else:
        canonical = aliases.get(version, version)

    for alias, document_identity in aliases.items():
        identities = {document_identity}
        identity_with_semantics = getattr(cfg, "_identity_with_semantics", None)
        if identity_with_semantics:
            identities.add(identity_with_semantics(document_identity, "query"))
            identities.add(identity_with_semantics(document_identity, "symmetric"))
        if canonical in identities:
            if alias == "bge":
                return logical_name
            return f"{logical_name}__{alias}"

    if canonical in compatible_legacy or version == "bge":
        return logical_name

    if ":" not in canonical:
        return f"{logical_name}__{version}"
    digest = hashlib.sha256(canonical.encode("utf-8")).hexdigest()[:16]
    return f"{logical_name}__emb_{digest}"


def vector_table_exists(
    table_name: str,
    project_id: str = "default",
    embedding_version: str | None = None,
) -> bool:
    physical_name = resolve_vector_table_name(table_name, embedding_version)
    return physical_name in set(get_db(project_id).table_names())


def _table_cache_key(
    project_id: str,
    embedding_version: str | None = None,
) -> str:
    cfg = get_settings()
    version = (
        (embedding_version or "").strip()
        or getattr(cfg, "resolved_embedding_write_identity", "")
        or cfg.resolved_embedding_active_version
    )
    return f"{project_id}:{version}"
