"""語意檢索與結果整理。"""

from __future__ import annotations

from typing import Any

from infra.db import get_knowledge_table, get_memories_table, parse_record_metadata
from personas.personas import normalize_persona_id


def get_search_table(table_name: str):
    """根據請求表名回傳對應資料表，維持既有預設行為。"""
    if table_name == "memories":
        return get_memories_table()
    return get_knowledge_table()


def search_records(
    table_name: str,
    query_vector: list[float],
    top_k: int,
    persona_id: str = "default",
) -> list[dict[str, Any]]:
    """執行檢索並回傳符合 persona 的結果。"""
    normalized_persona = normalize_persona_id(persona_id)
    limit = max(top_k, 1)
    raw_records = _search_to_records(
        get_search_table(table_name).search(query_vector).limit(limit * 4)
    )
    filtered: list[dict[str, Any]] = []

    for record in raw_records:
        if not _matches_persona(record, normalized_persona):
            continue
        filtered.append(_strip_vector(record))
        if len(filtered) >= limit:
            break

    return filtered


def _search_to_records(search_result: Any) -> list[dict[str, Any]]:
    if hasattr(search_result, "to_list"):
        return list(search_result.to_list())
    if hasattr(search_result, "to_arrow"):
        return list(search_result.to_arrow().to_pylist())
    return []


def _matches_persona(record: dict[str, Any], persona_id: str) -> bool:
    metadata = parse_record_metadata(record)
    record_persona = str(metadata.get("persona_id", "")).strip()
    if not record_persona or record_persona == "global":
        return True
    return normalize_persona_id(record_persona) == persona_id


def _strip_vector(record: dict[str, Any]) -> dict[str, Any]:
    return {key: value for key, value in record.items() if key != "vector"}
