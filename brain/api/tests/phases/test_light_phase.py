"""Tests for the Light Phase — candidate collection and dedup."""

from __future__ import annotations

import json
import sys
import types
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

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
        dreaming_min_score = 0.45
        dreaming_min_recall_count = 2
        dreaming_candidate_limit = 100
        dreaming_similarity_threshold = 0.90

    fake_config = types.ModuleType("config")
    fake_config.get_settings = lambda: FakeSettings()
    monkeypatch.setitem(sys.modules, "config", fake_config)

    ws_root = tmp_path / "workspace"

    fake_ws = types.ModuleType("knowledge.workspace")
    fake_ws.get_workspace_root = lambda project_id="default": ws_root
    monkeypatch.setitem(sys.modules, "knowledge.workspace", fake_ws)

    # Clean module cache
    for mod_name in list(sys.modules):
        if mod_name.startswith("memory.dreaming"):
            del sys.modules[mod_name]


def _import_light():
    import importlib
    return importlib.import_module("memory.dreaming.light_phase")


def _write_daily_file(ws_root: Path, persona: str, day: str, summary: str):
    """Write a fake daily file with a summary block."""
    memory_dir = ws_root / "memory" / persona
    memory_dir.mkdir(parents=True, exist_ok=True)
    content = f"""# {day} 對話日誌

## 14:00:00 | session test

- persona_id: {persona}
- fingerprint: abc123

### Summary
{summary}

"""
    (memory_dir / f"{day}.md").write_text(content, encoding="utf-8")


class TestCollectDailyFragments:
    def test_collects_recent_files(self, tmp_path):
        light = _import_light()
        ws = tmp_path / "workspace"
        today = date.today().isoformat()
        _write_daily_file(ws, "default", today, "今天討論了RAG架構")

        fragments = light._collect_daily_fragments("default", lookback_days=7)
        assert len(fragments) >= 1
        assert "RAG" in fragments[0]["text"]

    def test_skips_old_files(self, tmp_path):
        light = _import_light()
        ws = tmp_path / "workspace"
        old_date = (date.today() - timedelta(days=30)).isoformat()
        _write_daily_file(ws, "default", old_date, "very old summary")

        fragments = light._collect_daily_fragments("default", lookback_days=7)
        assert len(fragments) == 0


class TestExtractSummaryBlocks:
    def test_extracts_summary(self, tmp_path):
        light = _import_light()
        path = tmp_path / "test.md"
        path.write_text(
            "# Log\n\n### Summary\nThis is a summary\nSecond line\n\n## Next section\n",
            encoding="utf-8",
        )
        blocks = light._extract_summary_blocks(path)
        assert len(blocks) == 1
        assert "This is a summary" in blocks[0]

    def test_no_summary_returns_empty(self, tmp_path):
        light = _import_light()
        path = tmp_path / "empty.md"
        path.write_text("# Just a header\nSome text\n", encoding="utf-8")
        assert light._extract_summary_blocks(path) == []


class TestBuildTraceStats:
    def test_aggregates_results(self):
        light = _import_light()
        now = datetime.now(timezone.utc).isoformat()
        traces = [
            {
                "ts": now,
                "query": "what is RAG",
                "results": [{"text": "RAG is retrieval augmented generation", "score": 0.9}],
            },
            {
                "ts": now,
                "query": "explain RAG",
                "results": [{"text": "RAG is retrieval augmented generation", "score": 0.85}],
            },
        ]
        stats = light._build_trace_stats(traces)
        key = "RAG is retrieval augmented generation"
        assert key in stats
        assert stats[key]["recall_count"] == 2
        assert stats[key]["unique_queries"] == 2
        assert len(stats[key]["relevance_scores"]) == 2


class TestRunLightPhase:
    def test_produces_candidates(self, tmp_path):
        light = _import_light()
        ws = tmp_path / "workspace"
        today = date.today().isoformat()
        _write_daily_file(ws, "default", today, "重要的記憶內容")

        result = light.run_light_phase("default")
        assert result["status"] == "ok"
        assert result["candidate_count"] >= 1

        # Check candidates.json was written
        cand_path = ws / "dreaming" / ".dreams" / "candidates.json"
        assert cand_path.exists()
        candidates = json.loads(cand_path.read_text())
        assert len(candidates) >= 1
        assert "score" in candidates[0]
        assert "signals" in candidates[0]

    def test_deduplicates(self, tmp_path):
        light = _import_light()
        ws = tmp_path / "workspace"
        today = date.today().isoformat()
        yesterday = (date.today() - timedelta(days=1)).isoformat()
        _write_daily_file(ws, "default", today, "same content")
        _write_daily_file(ws, "default", yesterday, "same content")

        result = light.run_light_phase("default")
        # Should be deduped to 1
        assert result["candidate_count"] == 1
