"""Check real LanceDB retrieval with cached queries and synthetic data only.

Run from brain/api in its container: python /experiments/retrieval_cache.py
All project files and tables live in a TemporaryDirectory. No LLM or TTS.
"""

from __future__ import annotations

from datetime import date
import json
import logging
from pathlib import Path
import sys
from tempfile import TemporaryDirectory

sys.path.insert(0, str(Path.cwd()))

import config  # noqa: E402
from core.turn_reads import knowledge_queries  # noqa: E402
from infra import db, project_context  # noqa: E402
from knowledge.doc_meta import upsert_document_meta  # noqa: E402
from memory import embedder  # noqa: E402
from memory.query_embedding_cache import QueryEmbeddingCache  # noqa: E402
from safety import observability  # noqa: E402
from tools.builtin.knowledge_tools import _search_tool  # noqa: E402
from tools.context import active_project_id, active_user_message  # noqa: E402

PROJECT = "synthetic-cache-probe"
QUESTION = "測試服務中心週一幾點開門？"
DOCUMENT = "測試服務中心週一幾點開門？週一上午九點開門，下午五點關門。"


def counters() -> dict:
    return observability.get_metrics_store().snapshot()["counters"]


def run_turn(cfg, size: int, label: str) -> dict:
    cfg.embedding_query_cache_size = size
    observability._metrics = observability.MetricsStore()
    knowledge = _search_tool(
        "knowledge", {"queries": knowledge_queries(QUESTION, "請介紹測試服務中心")},
    )
    memories = _search_tool("memories", {"queries": [QUESTION]})
    assert knowledge["results"], "Expected a real knowledge hit"
    assert memories["results"], "Expected a real memory hit"
    metrics = counters()
    return {
        "case": label,
        "query_calls": metrics["embedding_query_requests_total"],
        "http_requests": metrics.get(
            "embedding_http_requests_total|input_type=query", 0,
        ),
        "vector_searches": sum(
            value for key, value in metrics.items()
            if key.startswith("node_attempts_total|node=rag_vector,")
        ),
        "lexical_searches": sum(
            value for key, value in metrics.items()
            if key.startswith("node_attempts_total|node=rag_lexical,")
        ),
        "knowledge_texts": [r["text"] for r in knowledge["results"]],
        "memory_texts": [r["text"] for r in memories["results"]],
    }


def main() -> None:
    logging.basicConfig(level=logging.CRITICAL)
    cfg = config.BrainSettings(_env_file=None, rag_query_expansion_enabled=False)
    config._settings = cfg
    with TemporaryDirectory(prefix="embedding-cache-retrieval-") as temporary:
        project_context._DATA_ROOT = Path(temporary) / "projects"
        ctx = project_context.resolve_project_context(PROJECT)
        ctx.workspace_root.mkdir(parents=True)
        document_path = ctx.workspace_root / "knowledge" / "centre.md"
        document_path.parent.mkdir()
        document_path.write_text(DOCUMENT, encoding="utf-8")
        vector = embedder.get_embedder().encode(
            [DOCUMENT], input_type="document",
            forced_identity=cfg.resolved_embedding_write_identity,
        )[0]
        db.ensure_tables(PROJECT)
        row = {
            "text": DOCUMENT,
            "vector": vector,
            "source": "synthetic",
            "date": date.today().isoformat(),
            "metadata": json.dumps({
                "path": "knowledge/centre.md", "persona_id": "global",
            }),
        }
        for name in ("knowledge", "memories"):
            table = db.get_table(name, PROJECT)
            table.delete("source = 'system'")
            table.add([row])
            table.create_fts_index("text", replace=True)
        project_token = active_project_id.set(PROJECT)
        message_token = active_user_message.set(QUESTION)
        try:
            baseline = run_turn(cfg, 0, "disabled")
            embedder._query_vector_cache = QueryEmbeddingCache()
            cold = run_turn(cfg, 1024, "cold")
            warm = run_turn(cfg, 1024, "warm")
            assert [r["http_requests"] for r in (baseline, cold, warm)] == [3, 2, 0]
            for result in (cold, warm):
                assert result["knowledge_texts"] == baseline["knowledge_texts"]
                assert result["memory_texts"] == baseline["memory_texts"]
            for result in (baseline, cold, warm):
                print(json.dumps(result, ensure_ascii=False), flush=True)
            upsert_document_meta("knowledge/centre.md", PROJECT, enabled=False)
            hidden = _search_tool("knowledge", {"queries": [QUESTION]})
            assert hidden["results"] == [], "Cached vector exposed disabled document"
            db.get_db(PROJECT).drop_table(db.resolve_vector_table_name("knowledge"))
            try:
                embedder.encode_query_with_fallback(
                    QUESTION, project_id=PROJECT, table_names=("knowledge",),
                )
            except RuntimeError:
                pass
            else:
                raise AssertionError("Cached vector bypassed dropped table check")
            print(json.dumps({
                "disabled_document_hidden": True,
                "dropped_table_rejected": True,
                "same_retrieval_results": True,
            }), flush=True)
        finally:
            active_user_message.reset(message_token)
            active_project_id.reset(project_token)
            project_context._db_cache.clear()
            project_context._session_store_cache.clear()
    for adapter in embedder._embedder_cache.values():
        adapter.close()


if __name__ == "__main__":
    main()
