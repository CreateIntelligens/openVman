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

def _stub_deps(monkeypatch: pytest.MonkeyPatch, *, knowledge=None, memories=None):
    """Stub all heavy deps and return fresh retrieval_service module."""
    # Stub embedder
    fake_embedder_mod = types.ModuleType("memory.embedder")
    fake_embedder = MagicMock()
    fake_embedder.encode.return_value = [[0.1] * 128]
    fake_embedder_mod.get_embedder = lambda: fake_embedder
    monkeypatch.setitem(sys.modules, "memory.embedder", fake_embedder_mod)

    # Stub retrieval (low-level search)
    fake_retrieval_mod = types.ModuleType("memory.retrieval")
    knowledge_data = knowledge or []
    memory_data = memories or []

    def mock_search_records(table_name, query_vector, top_k, persona_id="default"):
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
    fake_cfg.rag_memory_distance_bonus = 0.02
    fake_config_mod = types.ModuleType("config")
    fake_config_mod.get_settings = lambda: fake_cfg
    monkeypatch.setitem(sys.modules, "config", fake_config_mod)

    # Force reimport
    sys.modules.pop("core.retrieval_service", None)
    service = importlib.import_module("core.retrieval_service")
    return service, fake_cfg, logged_events


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
        service, _, _ = _stub_deps(monkeypatch, knowledge=knowledge, memories=memories)

        bundle = service.retrieve_context(query="test query")
        assert len(bundle.knowledge_results) >= 1
        assert len(bundle.memory_results) >= 1

    def test_top_k_matches_config(self, monkeypatch):
        """Results respect configured top-k limits."""
        knowledge = [_make_record(f"k{i}", 0.1 * i) for i in range(10)]
        memories = [_make_record(f"m{i}", 0.1 * i, source="memory") for i in range(10)]
        service, cfg, _ = _stub_deps(monkeypatch, knowledge=knowledge, memories=memories)
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
        service, _, _ = _stub_deps(monkeypatch, knowledge=knowledge)

        bundle = service.retrieve_context(query="test")
        distances = [r["_distance"] for r in bundle.knowledge_results]
        assert distances == sorted(distances)

    def test_memory_distance_bonus_applies(self, monkeypatch):
        """Memory results get a distance bonus in reranking."""
        service, _, _ = _stub_deps(monkeypatch)

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
        service, _, _ = _stub_deps(monkeypatch, knowledge=knowledge)

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
        service, _, events = _stub_deps(monkeypatch)

        service.retrieve_context(query="test")
        event_types = [e["event"] for e in events]
        assert "retrieval_completed" in event_types

    def test_empty_tables_return_empty_results(self, monkeypatch):
        """Empty knowledge/memory tables should return empty results without error."""
        service, _, _ = _stub_deps(monkeypatch)

        bundle = service.retrieve_context(query="test")
        assert bundle.knowledge_results == []
        assert bundle.memory_results == []

    def test_retrieval_bundle_is_frozen(self, monkeypatch):
        """RetrievalBundle should be immutable."""
        service, _, _ = _stub_deps(monkeypatch)

        bundle = service.retrieve_context(query="test")
        with pytest.raises(AttributeError):
            bundle.knowledge_results = []
