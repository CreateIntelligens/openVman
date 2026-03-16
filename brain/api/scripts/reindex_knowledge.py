"""CLI entrypoint: rebuild the knowledge vector index from workspace documents.

Usage::

    python3 -m brain.api.scripts.reindex_knowledge
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

# Ensure the api package root is importable when invoked via ``python3 -m``.
_API_ROOT = Path(__file__).resolve().parents[1]
if str(_API_ROOT) not in sys.path:
    sys.path.insert(0, str(_API_ROOT))


def main() -> None:
    from knowledge.indexer import rebuild_knowledge_index

    project_id = sys.argv[1] if len(sys.argv) > 1 else "default"
    try:
        result = rebuild_knowledge_index(project_id=project_id)
    except Exception as exc:
        print(f"[reindex] 索引失敗: {exc}", file=sys.stderr)
        sys.exit(1)

    print(json.dumps(result, ensure_ascii=False, indent=2))
    print(
        f"[reindex] 完成 — "
        f"文件數: {result['document_count']}, "
        f"chunk 數: {result['chunk_count']}, "
        f"變更文件: {result['changed_documents']}"
    )


if __name__ == "__main__":
    main()
