"""TASK-20: Tests for retrieval and reranking service."""

from __future__ import annotations

import importlib
import json
import sys
import types
from pathlib import Path
from unittest.mock import MagicMock

import pytest

API_ROOT = Path(__file__).resolve().parents[1]
if str(API_ROOT) not in sys.path:
    sys.path.insert(0, str(API_ROOT))


# ---------------------------------------------------------------------------
# Stub setup
# ---------------------------------------------------------------------------

def _stub_deps(monkeypatch: pytest.MonkeyPatch, *, knowledge=None, memories=None, embedding_route=None):
    """Stub all heavy deps and return fresh retrieval_service module."""
    # Stub embedder
    fake_embedder_mod = types.ModuleType("memory.embedder")
    fake_route = embedding_route or types.SimpleNamespace(
        version="bge",
        vector=[0.1] * 128,
        attempted_versions=[{"version": "bge", "status": "selected"}],
    )
    fake_embedder_mod.QueryEmbeddingRoute = types.SimpleNamespace
    fake_embedder = MagicMock()
    fake_embedder.encode.return_value = [fake_route.vector]
    fake_embedder_mod.get_embedder = lambda version=None: fake_embedder
    fake_embedder_mod.encode_query_with_fallback = (
        lambda query, *, project_id="default", table_names=("knowledge", "memories"): fake_route
    )
    monkeypatch.setitem(sys.modules, "memory.embedder", fake_embedder_mod)

    # Stub retrieval (low-level search)
    fake_retrieval_mod = types.ModuleType("memory.retrieval")
    knowledge_data = knowledge or []
    memory_data = memories or []
    search_calls: list[dict[str, object]] = []

    def mock_search_records(table_name, query_vector, top_k, persona_id="default", *, query_text="", project_id="default", embedding_version=None):
        search_calls.append(
            {
                "table_name": table_name,
                "query_vector": query_vector,
                "top_k": top_k,
                "persona_id": persona_id,
                "query_text": query_text,
                "project_id": project_id,
                "embedding_version": embedding_version,
            }
        )
        if table_name == "knowledge":
            return knowledge_data[:top_k]
        return memory_data[:top_k]

    fake_retrieval_mod.search_records = mock_search_records
    monkeypatch.setitem(sys.modules, "memory.retrieval", fake_retrieval_mod)

    # Stub infra.db
    fake_db_mod = types.ModuleType("infra.db")
    fake_db_mod.parse_record_metadata = lambda r: json.loads(r.get("metadata", "{}"))
    monkeypatch.setitem(sys.modules, "infra.db", fake_db_mod)

    # Stub observability
    logged_events: list[dict] = []
    fake_obs = types.ModuleType("safety.observability")
    fake_obs.log_event = lambda event, **kw: logged_events.append({"event": event, **kw})
    monkeypatch.setitem(sys.modules, "safety.observability", fake_obs)

    # Stub config
    fake_cfg = MagicMock()
    fake_cfg.rag_knowledge_top_k = 3
    fake_cfg.rag_memory_top_k = 2
    fake_cfg.rag_rerank_candidate_multiplier = 4
    fake_cfg.rag_distance_cutoff = 1.2
    fake_cfg.rag_memory_distance_bonus = 0.02
    fake_cfg.memory_decay_rate_per_day = 0.005
    fake_cfg.memory_importance_weight = 0.03
    fake_config_mod = types.ModuleType("config")
    fake_config_mod.get_settings = lambda: fake_cfg
    monkeypatch.setitem(sys.modules, "config", fake_config_mod)

    # Force reimport
    sys.modules.pop("core.retrieval_service", None)
    service = importlib.import_module("core.retrieval_service")
    return service, fake_cfg, logged_events, search_calls


def _make_record(text, distance, source="knowledge", path="doc.md", **extra_meta):
    meta = {"path": path, **extra_meta}
    return {
        "text": text,
        "_distance": distance,
        "source": source,
        "metadata": json.dumps(meta, ensure_ascii=False),
    }


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


class TestRetrievalService:
    def test_returns_knowledge_and_memory_results(self, monkeypatch):
        """retrieve_context returns both knowledge and memory results."""
        knowledge = [_make_record("k1", 0.1), _make_record("k2", 0.2)]
        memories = [_make_record("m1", 0.15, source="memory")]
        service, _, _, _ = _stub_deps(monkeypatch, knowledge=knowledge, memories=memories)

        bundle = service.retrieve_context(query="test query")
        assert len(bundle.knowledge_results) >= 1
        assert len(bundle.memory_results) >= 1

    def test_top_k_matches_config(self, monkeypatch):
        """Results respect configured top-k limits."""
        knowledge = [_make_record(f"k{i}", 0.1 * i) for i in range(10)]
        memories = [_make_record(f"m{i}", 0.1 * i, source="memory") for i in range(10)]
        service, cfg, _, _ = _stub_deps(monkeypatch, knowledge=knowledge, memories=memories)
        cfg.rag_knowledge_top_k = 3
        cfg.rag_memory_top_k = 2

        bundle = service.retrieve_context(query="test")
        assert len(bundle.knowledge_results) <= 3
        assert len(bundle.memory_results) <= 2

    def test_rerank_orders_by_distance(self, monkeypatch):
        """Results should be ordered by distance (ascending)."""
        knowledge = [
            _make_record("far", 0.9),
            _make_record("close", 0.1),
            _make_record("mid", 0.5),
        ]
        service, _, _, _ = _stub_deps(monkeypatch, knowledge=knowledge)

        bundle = service.retrieve_context(query="test")
        distances = [r["_distance"] for r in bundle.knowledge_results]
        assert distances == sorted(distances)

    def test_memory_distance_bonus_applies(self, monkeypatch):
        """Memory results get a distance bonus in reranking."""
        service, _, _, _ = _stub_deps(monkeypatch)

        # Test the internal rerank function
        candidates = [
            {"text": "a", "_distance": 0.5},
            {"text": "b", "_distance": 0.3},
        ]
        reranked = service._rerank_by_distance(candidates, distance_bonus=0.1)
        # With bonus, effective distances are 0.4 and 0.2, so 'b' still first
        assert reranked[0]["text"] == "b"

    def test_diagnostics_contains_required_fields(self, monkeypatch):
        """Diagnostics should contain candidate counts and top hits."""
        knowledge = [_make_record("k1", 0.1, path="diabetes.md")]
        service, _, _, _ = _stub_deps(monkeypatch, knowledge=knowledge)

        bundle = service.retrieve_context(query="糖尿病症狀")
        diag = bundle.diagnostics

        assert "knowledge_candidates" in diag
        assert "memory_candidates" in diag
        assert "final_knowledge" in diag
        assert "final_memory" in diag
        assert "top_hits" in diag
        assert "query_preview" in diag

    def test_diagnostics_logs_retrieval_event(self, monkeypatch):
        """retrieve_context should log a retrieval_completed event."""
        service, _, events, _ = _stub_deps(monkeypatch)

        service.retrieve_context(query="test")
        event_types = [e["event"] for e in events]
        assert "retrieval_completed" in event_types

    def test_empty_tables_return_empty_results(self, monkeypatch):
        """Empty knowledge/memory tables should return empty results without error."""
        service, _, _, _ = _stub_deps(monkeypatch)

        bundle = service.retrieve_context(query="test")
        assert bundle.knowledge_results == []
        assert bundle.memory_results == []

    def test_retrieval_bundle_is_frozen(self, monkeypatch):
        """RetrievalBundle should be immutable."""
        service, _, _, _ = _stub_deps(monkeypatch)

        bundle = service.retrieve_context(query="test")
        with pytest.raises(AttributeError):
            bundle.knowledge_results = []

    def test_decay_penalizes_old_records(self, monkeypatch):
        """Older memory records should rank lower due to time decay."""
        from datetime import date, timedelta

        today = date.today()
        old_date = (today - timedelta(days=60)).isoformat()
        recent_date = (today - timedelta(days=1)).isoformat()

        service, _, _, _ = _stub_deps(monkeypatch)

        # Both have the same raw distance
        candidates = [
            {"text": "old", "_distance": 0.3, "date": old_date, "metadata": "{}"},
            {"text": "recent", "_distance": 0.3, "date": recent_date, "metadata": "{}"},
        ]
        reranked = service._rerank_by_distance(
            candidates, decay_rate_per_day=0.005,
        )
        # Recent record should rank first (lower effective distance)
        assert reranked[0]["text"] == "recent"

    def test_decay_zero_has_no_effect(self, monkeypatch):
        """With decay_rate=0, old and new records rank the same by distance."""
        from datetime import date, timedelta

        today = date.today()
        old_date = (today - timedelta(days=100)).isoformat()

        service, _, _, _ = _stub_deps(monkeypatch)

        candidates = [
            {"text": "old", "_distance": 0.2, "date": old_date, "metadata": "{}"},
            {"text": "new", "_distance": 0.3, "date": today.isoformat(), "metadata": "{}"},
        ]
        reranked = service._rerank_by_distance(candidates, decay_rate_per_day=0.0)
        # Without decay, lower raw distance still wins
        assert reranked[0]["text"] == "old"

    def test_missing_date_no_decay_penalty(self, monkeypatch):
        """Records without a date field should not be penalized by decay."""
        service, _, _, _ = _stub_deps(monkeypatch)

        candidates = [
            {"text": "no_date", "_distance": 0.3, "metadata": "{}"},
            {"text": "with_date", "_distance": 0.3, "date": "2020-01-01", "metadata": "{}"},
        ]
        reranked = service._rerank_by_distance(
            candidates, decay_rate_per_day=0.01,
        )
        # no_date gets 0 days penalty, with_date gets huge penalty
        assert reranked[0]["text"] == "no_date"

    def test_importance_boosts_high_importance_records(self, monkeypatch):
        """Records with higher importance should rank better."""
        service, _, _, _ = _stub_deps(monkeypatch)

        candidates = [
            {
                "text": "low_importance",
                "_distance": 0.3,
                "metadata": json.dumps({"importance": 0.1}),
            },
            {
                "text": "high_importance",
                "_distance": 0.3,
                "metadata": json.dumps({"importance": 0.9}),
            },
        ]
        reranked = service._rerank_by_distance(
            candidates, importance_weight=0.1,
        )
        # high importance => lower effective distance => ranked first
        assert reranked[0]["text"] == "high_importance"

    def test_selected_embedding_version_is_used_for_search(self, monkeypatch):
        """retrieve_context passes the selected embedding version to search."""
        route = types.SimpleNamespace(
            version="gemini",
            vector=[0.9, 0.8],
            attempted_versions=[
                {"version": "bge", "status": "error", "reason": "RuntimeError"},
                {"version": "gemini", "status": "selected"},
            ],
        )
        service, _, _, search_calls = _stub_deps(
            monkeypatch,
            knowledge=[_make_record("k1", 0.1)],
            memories=[_make_record("m1", 0.2, source="memory")],
            embedding_route=route,
        )

        bundle = service.retrieve_context(query="test")

        assert bundle.diagnostics["embedding_version"] == "gemini"
        assert bundle.diagnostics["embedding_attempts"] == route.attempted_versions
        assert [call["embedding_version"] for call in search_calls] == [
            "gemini",
            "gemini",
        ]
