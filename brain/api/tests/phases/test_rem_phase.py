"""Tests for the REM Phase — embedding clustering and theme extraction."""

from __future__ import annotations

import json
import sys
import types
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import MagicMock

import numpy as np
import pytest

API_ROOT = Path(__file__).resolve().parents[1]
if str(API_ROOT) not in sys.path:
    sys.path.insert(0, str(API_ROOT))


@pytest.fixture(autouse=True)
def _stub_deps(monkeypatch, tmp_path):
    """Stub config, workspace, embedder, and recall_tracker."""
    class FakeSettings:
        dreaming_enabled = True
        dreaming_lookback_days = 7

    fake_config = types.ModuleType("config")
    fake_config.get_settings = lambda: FakeSettings()
    monkeypatch.setitem(sys.modules, "config", fake_config)

    ws_root = tmp_path / "workspace"

    fake_ws = types.ModuleType("knowledge.workspace")
    fake_ws.get_workspace_root = lambda project_id="default": ws_root
    monkeypatch.setitem(sys.modules, "knowledge.workspace", fake_ws)

    # Stub embedder — return distinct vectors for clustering
    fake_embedder = types.ModuleType("memory.embedder")
    _call_count = {"n": 0}

    def _fake_encode(texts):
        # Return vectors that form 2 clusters
        vectors = []
        for i, text in enumerate(texts):
            if "RAG" in text:
                vectors.append([1.0, 0.0, 0.0])
            elif "NLP" in text:
                vectors.append([0.0, 1.0, 0.0])
            else:
                vectors.append([float(i % 3) / 3, float(i % 5) / 5, 0.1])
        return vectors

    _mock_embedder = MagicMock()
    _mock_embedder.encode = _fake_encode
    fake_embedder.get_embedder = lambda embedding_version=None: _mock_embedder
    monkeypatch.setitem(sys.modules, "memory.embedder", fake_embedder)

    # Clean module cache
    for mod_name in list(sys.modules):
        if mod_name.startswith("memory.dreaming"):
            del sys.modules[mod_name]


def _import_rem():
    import importlib
    return importlib.import_module("memory.dreaming.rem_phase")


def _write_traces(ws_root: Path, traces: list[dict]):
    """Write fake recall traces JSONL file."""
    traces_dir = ws_root / "dreaming" / ".dreams"
    traces_dir.mkdir(parents=True, exist_ok=True)
    lines = [json.dumps(t, ensure_ascii=False) for t in traces]
    (traces_dir / "recall-traces.jsonl").write_text("\n".join(lines) + "\n")


class TestKmeans:
    def test_basic_clustering(self):
        rem = _import_rem()
        # Two clear clusters
        vectors = np.array([
            [1.0, 0.0], [1.1, 0.0], [0.9, 0.0],  # cluster A
            [0.0, 1.0], [0.0, 1.1], [0.0, 0.9],   # cluster B
        ], dtype=np.float32)

        labels = rem._kmeans(vectors, k=2)
        assert len(labels) == 6
        # First 3 should be in same cluster, last 3 in another
        assert labels[0] == labels[1] == labels[2]
        assert labels[3] == labels[4] == labels[5]
        assert labels[0] != labels[3]

    def test_single_vector(self):
        rem = _import_rem()
        vectors = np.array([[1.0, 2.0]], dtype=np.float32)
        labels = rem._kmeans(vectors, k=3)
        assert len(labels) == 1


class TestExtractUniqueQueries:
    def test_deduplicates(self):
        rem = _import_rem()
        traces = [
            {"query": "what is RAG"},
            {"query": "what is RAG"},
            {"query": "explain NLP"},
        ]
        queries = rem._extract_unique_queries(traces)
        assert len(queries) == 2


class TestRunRemPhase:
    def test_insufficient_queries(self, tmp_path):
        rem = _import_rem()
        ws = tmp_path / "workspace"
        now = datetime.now(timezone.utc).isoformat()
        _write_traces(ws, [
            {"ts": now, "query": "only one query", "results": []},
        ])

        result = rem.run_rem_phase("default")
        assert result["status"] == "ok"
        assert result["theme_count"] == 0

    def test_produces_themes(self, tmp_path):
        rem = _import_rem()
        ws = tmp_path / "workspace"
        now = datetime.now(timezone.utc).isoformat()
        traces = [
            {"ts": now, "query": "what is RAG", "results": []},
            {"ts": now, "query": "RAG architecture", "results": []},
            {"ts": now, "query": "NLP basics", "results": []},
            {"ts": now, "query": "explain NLP tasks", "results": []},
            {"ts": now, "query": "something else", "results": []},
        ]
        _write_traces(ws, traces)

        result = rem.run_rem_phase("default")
        assert result["status"] == "ok"
        assert result["theme_count"] >= 1

        # Check phase-signals.json was written
        signals_path = ws / "dreaming" / ".dreams" / "phase-signals.json"
        assert signals_path.exists()
        signals = json.loads(signals_path.read_text())
        assert "themes" in signals
        assert len(signals["themes"]) >= 1
