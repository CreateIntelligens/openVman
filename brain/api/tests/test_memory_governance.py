"""TASK-21: Tests for daily memory writeback and re-index hooks."""

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

def _stub_deps(monkeypatch: pytest.MonkeyPatch, tmp_path: Path):
    """Stub all heavy deps for memory_governance testing."""
    workspace_root = tmp_path / "workspace"
    workspace_root.mkdir(exist_ok=True)
    memory_dir = workspace_root / "memory" / "default"
    memory_dir.mkdir(parents=True, exist_ok=True)
    learnings_dir = workspace_root / ".learnings"
    learnings_dir.mkdir(exist_ok=True)
    summaries_path = learnings_dir / "MEMORY_SUMMARIES.md"
    summaries_path.write_text("# 記憶摘要 (MEMORY_SUMMARIES)\n", encoding="utf-8")

    # Stub embedder
    fake_embedder_mod = types.ModuleType("memory.embedder")
    fake_embedder = MagicMock()
    fake_embedder.encode.return_value = [[0.1] * 128]
    fake_embedder_mod.get_embedder = lambda: fake_embedder
    monkeypatch.setitem(sys.modules, "memory.embedder", fake_embedder_mod)

    # Stub infra.db
    fake_db_mod = types.ModuleType("infra.db")
    fake_db = MagicMock()
    fake_table = MagicMock()
    fake_table.to_arrow.return_value.to_pylist.return_value = []
    fake_db.create_table = MagicMock()
    fake_db_mod.get_db = lambda: fake_db
    fake_db_mod.get_memories_table = lambda: fake_table
    fake_db_mod.get_knowledge_table = MagicMock()
    fake_db_mod.normalize_vector = lambda v: v
    fake_db_mod.parse_record_metadata = lambda r: json.loads(r.get("metadata", "{}"))
    monkeypatch.setitem(sys.modules, "infra.db", fake_db_mod)

    # Stub workspace
    fake_workspace_mod = types.ModuleType("knowledge.workspace")
    fake_workspace_mod.ensure_workspace_scaffold = lambda: workspace_root
    fake_workspace_mod.WORKSPACE_ROOT = workspace_root
    fake_workspace_mod.CORE_DOCUMENTS = {"memory_summaries": summaries_path}
    fake_workspace_mod.iter_indexable_documents = lambda: []
    monkeypatch.setitem(sys.modules, "knowledge.workspace", fake_workspace_mod)

    # Stub personas
    fake_personas_mod = types.ModuleType("personas.personas")
    fake_personas_mod.normalize_persona_id = lambda x: x or "default"
    fake_personas_mod.extract_persona_id_from_relative_path = lambda _: "default"
    monkeypatch.setitem(sys.modules, "personas.personas", fake_personas_mod)

    # Stub config
    fake_cfg = MagicMock()
    fake_cfg.memory_maintenance_interval_seconds = 0
    fake_config_mod = types.ModuleType("config")
    fake_config_mod.get_settings = lambda: fake_cfg
    monkeypatch.setitem(sys.modules, "config", fake_config_mod)

    # Stub observability
    logged_events: list[dict] = []
    fake_obs = types.ModuleType("safety.observability")
    fake_obs.log_event = lambda event, **kw: logged_events.append({"event": event, **kw})
    monkeypatch.setitem(sys.modules, "safety.observability", fake_obs)

    # Force reimport
    sys.modules.pop("memory.memory_governance", None)
    gov = importlib.import_module("memory.memory_governance")
    gov._last_maintenance_at = 0.0

    return gov, workspace_root, logged_events


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


class TestDailySummaryWriteback:
    def test_summary_written_to_daily_file(self, monkeypatch, tmp_path):
        """Summary block is appended to memory/YYYY-MM-DD.md."""
        gov, ws, _ = _stub_deps(monkeypatch, tmp_path)

        result = gov.write_summary_and_reindex(
            persona_id="default",
            day="2026-03-15",
            summary_text="- 使用者詢問糖尿病飲食控制",
            source_turns=8,
            session_id="abc123",
        )

        assert result["status"] == "ok"
        daily_file = ws / "memory" / "default" / "2026-03-15.md"
        assert daily_file.exists()

        content = daily_file.read_text(encoding="utf-8")
        assert "記憶摘要" in content
        assert "糖尿病飲食控制" in content
        assert "session abc123" in content

    def test_duplicate_fingerprint_is_skipped(self, monkeypatch, tmp_path):
        """Same summary text written twice should be deduplicated."""
        gov, ws, _ = _stub_deps(monkeypatch, tmp_path)

        summary = "- 使用者喜歡簡短回覆"
        gov.write_summary_and_reindex(
            persona_id="default",
            day="2026-03-15",
            summary_text=summary,
        )
        result = gov.write_summary_and_reindex(
            persona_id="default",
            day="2026-03-15",
            summary_text=summary,
        )

        assert result["status"] == "skipped"
        assert result["reason"] == "duplicate_fingerprint"

    def test_raw_transcript_and_summary_coexist(self, monkeypatch, tmp_path):
        """Existing transcript content should not be destroyed."""
        gov, ws, _ = _stub_deps(monkeypatch, tmp_path)

        daily_file = ws / "memory" / "default" / "2026-03-15.md"
        daily_file.write_text(
            "# 2026-03-15 對話日誌\n\n## 10:00 | session xyz\n\n### User\n你好\n",
            encoding="utf-8",
        )

        gov.write_summary_and_reindex(
            persona_id="default",
            day="2026-03-15",
            summary_text="- 打招呼",
            session_id="xyz",
        )

        content = daily_file.read_text(encoding="utf-8")
        assert "## 10:00 | session xyz" in content  # original preserved
        assert "### User" in content
        assert "記憶摘要" in content  # summary section added
        assert "打招呼" in content

    def test_reindex_hook_runs_after_writeback(self, monkeypatch, tmp_path):
        """Writeback should trigger run_memory_maintenance."""
        gov, ws, events = _stub_deps(monkeypatch, tmp_path)

        result = gov.write_summary_and_reindex(
            persona_id="default",
            day="2026-03-15",
            summary_text="- 測試 reindex hook",
        )

        assert result["status"] == "ok"
        assert "reindex" in result
        assert result["reindex"]["status"] == "ok"

    def test_writeback_logs_event(self, monkeypatch, tmp_path):
        """Writeback should log memory_writeback_completed event."""
        gov, ws, events = _stub_deps(monkeypatch, tmp_path)

        gov.write_summary_and_reindex(
            persona_id="default",
            day="2026-03-15",
            summary_text="- 測試 log",
        )

        event_types = [e["event"] for e in events]
        assert "memory_writeback_completed" in event_types

    def test_summary_block_format_is_stable(self, monkeypatch, tmp_path):
        """Summary block format should contain required fields."""
        gov, ws, _ = _stub_deps(monkeypatch, tmp_path)

        gov.write_summary_and_reindex(
            persona_id="default",
            day="2026-03-15",
            summary_text="- 格式測試",
            source_turns=5,
            session_id="sess-1",
        )

        daily_file = ws / "memory" / "default" / "2026-03-15.md"
        content = daily_file.read_text(encoding="utf-8")

        assert "persona_id: default" in content
        assert "fingerprint:" in content
        assert "source_turns: 5" in content
        assert "### Summary" in content
