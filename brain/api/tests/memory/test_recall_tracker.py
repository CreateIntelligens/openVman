"""Tests for recall_tracker — JSONL write/read/rotate."""

from __future__ import annotations

import json
import sys
import types
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

API_ROOT = Path(__file__).resolve().parents[1]
if str(API_ROOT) not in sys.path:
    sys.path.insert(0, str(API_ROOT))


# ---------------------------------------------------------------------------
# Stub heavy deps before importing recall_tracker
# ---------------------------------------------------------------------------

def _make_fake_config(tmp_path: Path, enabled: bool = True):
    """Return a fake settings object with workspace pointing to tmp_path."""
    class FakeSettings:
        dreaming_enabled = enabled
        dreaming_lookback_days = 7
    return FakeSettings()


@pytest.fixture(autouse=True)
def _stub_deps(monkeypatch, tmp_path):
    """Replace config and workspace helpers with test stubs."""
    fake_cfg = _make_fake_config(tmp_path, enabled=True)

    fake_config_mod = types.ModuleType("config")
    fake_config_mod.get_settings = lambda: fake_cfg
    monkeypatch.setitem(sys.modules, "config", fake_config_mod)

    fake_ws_mod = types.ModuleType("knowledge.workspace")
    fake_ws_mod.get_workspace_root = lambda project_id="default": tmp_path / "workspace"
    monkeypatch.setitem(sys.modules, "knowledge.workspace", fake_ws_mod)

    # Force re-import of recall_tracker (and paths) with fresh stubs
    sys.modules.pop("memory.dreaming.recall_tracker", None)
    sys.modules.pop("memory.dreaming.paths", None)
    sys.modules.pop("memory.dreaming", None)


def _import_tracker():
    import importlib
    return importlib.import_module("memory.dreaming.recall_tracker")


class TestRecordTrace:
    def test_creates_jsonl_file(self, tmp_path):
        tracker = _import_tracker()
        tracker.record_trace(
            query="什麼是RAG",
            persona_id="default",
            project_id="default",
            table_name="memories",
            results=[{"text": "RAG是...", "_distance": 0.87, "id": "abc123"}],
        )
        # Wait for thread to finish
        import time
        time.sleep(0.5)

        traces_dir = tmp_path / "workspace" / "dreaming" / ".dreams"
        jsonl_path = traces_dir / "recall-traces.jsonl"
        assert jsonl_path.exists()
        lines = jsonl_path.read_text().strip().split("\n")
        assert len(lines) == 1
        entry = json.loads(lines[0])
        assert entry["query"] == "什麼是RAG"
        assert entry["persona"] == "default"
        assert len(entry["results"]) == 1

    def test_disabled_does_not_write(self, monkeypatch, tmp_path):
        fake_cfg = _make_fake_config(tmp_path, enabled=False)
        fake_config_mod = types.ModuleType("config")
        fake_config_mod.get_settings = lambda: fake_cfg
        monkeypatch.setitem(sys.modules, "config", fake_config_mod)
        sys.modules.pop("memory.dreaming.recall_tracker", None)

        tracker = _import_tracker()
        tracker.record_trace(
            query="test",
            persona_id="default",
            project_id="default",
            table_name="memories",
            results=[{"text": "x"}],
        )
        import time
        time.sleep(0.3)

        traces_dir = tmp_path / "workspace" / "dreaming" / ".dreams"
        assert not (traces_dir / "recall-traces.jsonl").exists()


class TestReadTraces:
    def test_reads_entries_within_date_range(self, tmp_path):
        tracker = _import_tracker()

        traces_dir = tmp_path / "workspace" / "dreaming" / ".dreams"
        traces_dir.mkdir(parents=True, exist_ok=True)

        now = datetime.now(timezone.utc)
        old = now - timedelta(days=10)
        recent = now - timedelta(days=1)

        lines = [
            json.dumps({"ts": old.isoformat(), "query": "old"}, ensure_ascii=False),
            json.dumps({"ts": recent.isoformat(), "query": "recent"}, ensure_ascii=False),
            json.dumps({"ts": now.isoformat(), "query": "now"}, ensure_ascii=False),
        ]
        (traces_dir / "recall-traces.jsonl").write_text("\n".join(lines) + "\n")

        results = tracker.read_traces("default", days=7)
        queries = [r["query"] for r in results]
        assert "old" not in queries
        assert "recent" in queries
        assert "now" in queries

    def test_empty_dir_returns_empty(self, tmp_path):
        tracker = _import_tracker()
        results = tracker.read_traces("default")
        assert results == []


class TestRotateTraces:
    def test_rotates_active_file(self, tmp_path):
        tracker = _import_tracker()

        traces_dir = tmp_path / "workspace" / "dreaming" / ".dreams"
        traces_dir.mkdir(parents=True, exist_ok=True)
        active = traces_dir / "recall-traces.jsonl"
        active.write_text('{"ts":"2026-04-07T00:00:00","query":"test"}\n')

        deleted = tracker.rotate_traces("default")
        assert deleted == 0
        assert not active.exists()
        # A rotated file should exist
        rotated_files = list(traces_dir.glob("recall-traces-*.jsonl"))
        assert len(rotated_files) == 1

    def test_cleans_old_rotated_files(self, tmp_path):
        tracker = _import_tracker()

        traces_dir = tmp_path / "workspace" / "dreaming" / ".dreams"
        traces_dir.mkdir(parents=True, exist_ok=True)

        old_date = (datetime.now(timezone.utc) - timedelta(days=20)).strftime("%Y-%m-%d")
        old_file = traces_dir / f"recall-traces-{old_date}.jsonl"
        old_file.write_text('{"ts":"old"}\n')

        deleted = tracker.rotate_traces("default")
        assert deleted == 1
        assert not old_file.exists()
