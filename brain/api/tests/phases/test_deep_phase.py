"""Tests for the Deep Phase — scoring, dedup, and promotion."""

from __future__ import annotations

import json
import sys
import types
from pathlib import Path
from unittest.mock import MagicMock

import pytest

API_ROOT = Path(__file__).resolve().parents[1]
if str(API_ROOT) not in sys.path:
    sys.path.insert(0, str(API_ROOT))


@pytest.fixture(autouse=True)
def _stub_deps(monkeypatch, tmp_path):
    """Stub config, workspace, embedder, and infra.db."""
    class FakeSettings:
        dreaming_enabled = True
        dreaming_lookback_days = 7
        dreaming_min_score = 0.3
        dreaming_min_recall_count = 1
        dreaming_min_unique_queries = 1
        dreaming_candidate_limit = 100
        dreaming_similarity_threshold = 0.90

    fake_config = types.ModuleType("config")
    fake_config.get_settings = lambda: FakeSettings()
    monkeypatch.setitem(sys.modules, "config", fake_config)

    ws_root = tmp_path / "workspace"

    fake_ws = types.ModuleType("knowledge.workspace")
    fake_ws.get_workspace_root = lambda project_id="default": ws_root
    monkeypatch.setitem(sys.modules, "knowledge.workspace", fake_ws)

    # Stub embedder
    fake_embedder = types.ModuleType("memory.embedder")
    _mock_embedder = MagicMock()
    _mock_embedder.encode = lambda texts: [[0.1, 0.2, 0.3] for _ in texts]
    fake_embedder.get_embedder = lambda embedding_version=None: _mock_embedder
    fake_embedder.encode_text = lambda text, embedding_version=None: [0.1, 0.2, 0.3]
    monkeypatch.setitem(sys.modules, "memory.embedder", fake_embedder)

    # Stub infra.db
    fake_db = types.ModuleType("infra.db")
    _mock_table = MagicMock()
    _mock_arrow = MagicMock()
    _mock_arrow.to_pylist.return_value = []
    _mock_table.to_arrow.return_value = _mock_arrow
    _mock_table.add = MagicMock()
    fake_db.get_memories_table = lambda project_id="default", embedding_version=None: _mock_table
    fake_db.get_db = MagicMock()
    fake_db.normalize_vector = lambda v: list(v) if hasattr(v, "__iter__") else [v]
    fake_db.resolve_vector_table_name = lambda name, ev=None: name
    monkeypatch.setitem(sys.modules, "infra.db", fake_db)

    # Stub importance
    _imp_result = types.SimpleNamespace(score=0.5, level="medium", signals=())
    fake_imp = types.ModuleType("memory.importance")
    fake_imp.ImportanceResult = type("ImportanceResult", (), {})
    fake_imp.score_importance = lambda text: _imp_result
    monkeypatch.setitem(sys.modules, "memory.importance", fake_imp)

    # Clean module cache
    for mod_name in list(sys.modules):
        if mod_name.startswith("memory.dreaming"):
            del sys.modules[mod_name]


def _import_deep():
    import importlib
    return importlib.import_module("memory.dreaming.deep_phase")


def _write_candidates(ws_root: Path, candidates: list[dict]):
    dreams_dir = ws_root / "dreaming" / ".dreams"
    dreams_dir.mkdir(parents=True, exist_ok=True)
    (dreams_dir / "candidates.json").write_text(
        json.dumps(candidates, ensure_ascii=False), encoding="utf-8",
    )


class TestRunDeepPhase:
    def test_no_candidates_returns_zero(self, tmp_path):
        deep = _import_deep()
        result = deep.run_deep_phase("default")
        assert result["status"] == "ok"
        assert result["promoted_count"] == 0

    def test_promotes_qualifying_candidates(self, tmp_path):
        deep = _import_deep()
        ws = tmp_path / "workspace"
        candidates = [
            {
                "text": "重要的RAG知識",
                "persona_id": "default",
                "day": "2026-04-07",
                "fingerprint": "abc123",
                "score": 0.6,
                "signals": {
                    "raw_recall_count": 3,
                    "raw_unique_queries": 2,
                },
            },
        ]
        _write_candidates(ws, candidates)

        result = deep.run_deep_phase("default")
        assert result["status"] == "ok"
        assert result["promoted_count"] == 1
        assert "report_path" in result

    def test_filters_below_threshold(self, tmp_path):
        deep = _import_deep()
        ws = tmp_path / "workspace"
        candidates = [
            {
                "text": "low scoring memory",
                "score": 0.1,
                "signals": {"raw_recall_count": 0, "raw_unique_queries": 0},
            },
        ]
        _write_candidates(ws, candidates)

        result = deep.run_deep_phase("default")
        assert result["promoted_count"] == 0

    def test_writes_report(self, tmp_path):
        deep = _import_deep()
        ws = tmp_path / "workspace"
        candidates = [
            {
                "text": "promotable memory",
                "score": 0.6,
                "signals": {"raw_recall_count": 3, "raw_unique_queries": 2},
            },
        ]
        _write_candidates(ws, candidates)

        result = deep.run_deep_phase("default")
        report_dir = ws / "dreaming" / "deep"
        assert any(report_dir.glob("*.md"))
