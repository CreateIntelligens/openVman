"""Re-embed every project's knowledge and long-term memories with the active embedding version.

換 embedding 模型（例如 BGE-M3 → EmbeddingGemma 2）後執行一次。新版本的向量寫進
另一組資料表（``knowledge__gemma``、``memories__gemma``），舊版本的表不動，要退回
只要把 ``EMBEDDING_ACTIVE_VERSION`` 改回去。新表建好之前，查詢會自動退回有索引的
舊版本，所以切換期間不會查不到東西。

- 知識庫：照文件重建索引（跟後台「重建索引」一樣）。
- 長期記憶：沒有原始檔可以重建，從來源版本的表逐筆用新模型重算向量後寫入；
  目標表已經有記憶的專案跳過，不重複寫。

    docker exec -w /app openvman-api-1 python -m scripts.migrate_embedding_version --dry-run
    docker exec -w /app openvman-api-1 python -m scripts.migrate_embedding_version --from bge
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

# Ensure the api package root is importable when invoked via ``python3 -m``.
_API_ROOT = Path(__file__).resolve().parents[1]
if str(_API_ROOT) not in sys.path:
    sys.path.insert(0, str(_API_ROOT))

from config import get_settings
from infra.db import (
    TABLE_SEED_TEXTS,
    ensure_fts_index,
    get_db,
    get_memories_table,
    normalize_vector,
    parse_record_metadata,
    resolve_vector_table_name,
)
from infra.project_admin import list_projects
from knowledge.indexer import rebuild_knowledge_index
from memory.embedder import get_embedder

_BATCH = 32


def _real_memories(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    seed = TABLE_SEED_TEXTS["memories"]
    return [row for row in rows if row.get("text") and row.get("text") != seed]


def _migrate_memories(project_id: str, source: str, dry_run: bool) -> str:
    db = get_db(project_id)
    source_table = resolve_vector_table_name("memories", source)
    if source_table not in db.table_names():
        return "沒有來源記憶表"
    rows = _real_memories(db.open_table(source_table).to_arrow().to_pylist())
    if not rows:
        return "沒有記憶"
    if dry_run:
        return f"{len(rows)} 筆待轉"
    target = get_memories_table(project_id)
    if _real_memories(target.to_arrow().to_pylist()):
        return "目標表已有記憶，跳過"

    cfg = get_settings()
    identity = cfg.resolved_embedding_write_identity
    columns = set(target.schema.names)
    embedder = get_embedder()
    migrated: list[dict[str, Any]] = []
    for start in range(0, len(rows), _BATCH):
        batch = rows[start:start + _BATCH]
        vectors, spec, _ = embedder.encode_with_metadata(
            [row["text"] for row in batch], input_type="document", forced_identity=identity,
        )
        if spec.get("identity") != identity:
            raise RuntimeError("Gateway returned an identity outside the write lease")
        for row, vector in zip(batch, vectors):
            metadata = parse_record_metadata(row)
            metadata["embedding_identity"] = identity
            record = {**row, "vector": normalize_vector(vector), "metadata": json.dumps(metadata, ensure_ascii=False)}
            migrated.append({key: value for key, value in record.items() if key in columns})
    target.add(migrated)
    ensure_fts_index("memories", project_id)
    return f"{len(migrated)} 筆已轉"


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--from", dest="source", default="bge", help="記憶從哪個版本搬過來（預設 bge）")
    parser.add_argument("--project", action="append", help="只做這些專案（可重複）；預設全部")
    parser.add_argument("--dry-run", action="store_true", help="只列出要做什麼，不寫入")
    args = parser.parse_args()

    cfg = get_settings()
    target = cfg.resolved_embedding_active_version
    if target == args.source:
        sys.exit(f"EMBEDDING_ACTIVE_VERSION 已經是 {target}，先改成新版本再跑")
    print(f"{args.source} → {target}（{cfg.resolved_embedding_write_identity}）")
    project_ids = args.project or [project["project_id"] for project in list_projects()]
    for project_id in project_ids:
        if args.dry_run:
            knowledge = "待重建"
        else:
            stats = rebuild_knowledge_index(project_id)
            knowledge = f"{stats.get('document_count')} 份文件、{stats.get('chunk_count')} 段"
        memories = _migrate_memories(project_id, args.source, args.dry_run)
        print(f"{project_id}: 知識庫 {knowledge}；記憶 {memories}")


if __name__ == "__main__":
    main()
