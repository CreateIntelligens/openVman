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
    summaries_path = workspace_root / "MEMORY_SUMMARIES.md"
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
    fake_db_mod.get_db = lambda project_id="default": fake_db
    fake_db_mod.get_memories_table = lambda project_id="default": fake_table
    fake_db_mod.get_knowledge_table = lambda project_id="default": MagicMock()
    fake_db_mod.normalize_vector = lambda v: v
    fake_db_mod.parse_record_metadata = lambda r: json.loads(r.get("metadata", "{}"))
    fake_db_mod.ensure_fts_index = lambda table_name, project_id="default": None
    monkeypatch.setitem(sys.modules, "infra.db", fake_db_mod)

    # Stub workspace
    fake_workspace_mod = types.ModuleType("knowledge.workspace")
    fake_workspace_mod.ensure_workspace_scaffold = lambda project_id="default": workspace_root
    fake_workspace_mod.get_workspace_root = lambda project_id="default": workspace_root
    fake_workspace_mod.get_core_documents = lambda project_id="default": {"memory_summaries": summaries_path}
    fake_workspace_mod.iter_indexable_documents = lambda project_id="default": []
    monkeypatch.setitem(sys.modules, "knowledge.workspace", fake_workspace_mod)

    # Stub personas
    fake_personas_mod = types.ModuleType("personas.personas")
    fake_personas_mod.normalize_persona_id = lambda x: x or "default"
    fake_personas_mod.extract_persona_id_from_relative_path = lambda _: "default"
    monkeypatch.setitem(sys.modules, "personas.personas", fake_personas_mod)

    # Stub archive paths
    archive_memory_dir = workspace_root / "archive" / "memory"
    archive_memory_dir.mkdir(parents=True, exist_ok=True)
    fake_workspace_mod.get_archive_paths = lambda project_id="default": {
        "errors_dir": workspace_root / "archive" / "errors",
        "memory_dir": archive_memory_dir,
    }

    # Stub config
    fake_cfg = MagicMock()
    fake_cfg.memory_maintenance_interval_seconds = 0
    fake_cfg.memory_merge_similarity_threshold = 0.92
    fake_cfg.transcript_retention_days = 30
    fake_config_mod = types.ModuleType("config")
    fake_config_mod.get_settings = lambda: fake_cfg
    monkeypatch.setitem(sys.modules, "config", fake_config_mod)

    # Stub observability
    logged_events: list[dict] = []
    fake_obs = types.ModuleType("safety.observability")
    fake_obs.log_event = lambda event, **kw: logged_events.append({"event": event, **kw})
    monkeypatch.setitem(sys.modules, "safety.observability", fake_obs)

    # Stub importance (used by _build_summary_records)
    fake_importance_mod = types.ModuleType("memory.importance")

    class FakeImportanceResult:
        score = 0.1
        level = "low"
        signals = ()

    fake_importance_mod.score_importance = lambda text: FakeImportanceResult()
    fake_importance_mod.ImportanceResult = FakeImportanceResult
    monkeypatch.setitem(sys.modules, "memory.importance", fake_importance_mod)

    # Force reimport
    sys.modules.pop("memory.memory_governance", None)
    gov = importlib.import_module("memory.memory_governance")
    gov._last_maintenance_at = {}

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


class TestSemanticDedup:
    def test_identical_vectors_are_merged(self, monkeypatch, tmp_path):
        """Records with identical vectors should be merged (newer wins)."""
        gov, _, _ = _stub_deps(monkeypatch, tmp_path)

        vec = [1.0] * 128
        records = [
            {
                "text": "older",
                "vector": vec,
                "date": "2026-03-10",
                "metadata": json.dumps({"persona_id": "default"}),
            },
            {
                "text": "newer",
                "vector": vec,
                "date": "2026-03-15",
                "metadata": json.dumps({"persona_id": "default"}),
            },
        ]
        result = gov._semantic_dedupe_records(records)
        assert len(result) == 1
        assert result[0]["text"] == "newer"

    def test_different_vectors_are_kept(self, monkeypatch, tmp_path):
        """Records with very different vectors should both be kept."""
        gov, _, _ = _stub_deps(monkeypatch, tmp_path)

        vec_a = [1.0, 0.0] + [0.0] * 126
        vec_b = [0.0, 1.0] + [0.0] * 126
        records = [
            {
                "text": "topic A",
                "vector": vec_a,
                "date": "2026-03-10",
                "metadata": json.dumps({"persona_id": "default"}),
            },
            {
                "text": "topic B",
                "vector": vec_b,
                "date": "2026-03-15",
                "metadata": json.dumps({"persona_id": "default"}),
            },
        ]
        result = gov._semantic_dedupe_records(records)
        assert len(result) == 2

    def test_different_personas_not_merged(self, monkeypatch, tmp_path):
        """Records from different personas should not be merged even if identical vectors."""
        gov, _, _ = _stub_deps(monkeypatch, tmp_path)

        vec = [1.0] * 128
        records = [
            {
                "text": "same content",
                "vector": vec,
                "date": "2026-03-10",
                "metadata": json.dumps({"persona_id": "alice"}),
            },
            {
                "text": "same content",
                "vector": vec,
                "date": "2026-03-15",
                "metadata": json.dumps({"persona_id": "bob"}),
            },
        ]
        result = gov._semantic_dedupe_records(records)
        assert len(result) == 2

    def test_records_without_vectors_are_preserved(self, monkeypatch, tmp_path):
        """Records without vector field should not be dropped."""
        gov, _, _ = _stub_deps(monkeypatch, tmp_path)

        records = [
            {"text": "no vector", "date": "2026-03-10", "metadata": "{}"},
            {"text": "also no vector", "date": "2026-03-15", "metadata": "{}"},
        ]
        result = gov._semantic_dedupe_records(records)
        assert len(result) == 2

    def test_merge_logs_event(self, monkeypatch, tmp_path):
        """Semantic dedup should log an event when merges occur."""
        gov, _, events = _stub_deps(monkeypatch, tmp_path)

        vec = [1.0] * 128
        records = [
            {
                "text": "dup A",
                "vector": vec,
                "date": "2026-03-10",
                "metadata": json.dumps({"persona_id": "default"}),
            },
            {
                "text": "dup B",
                "vector": vec,
                "date": "2026-03-15",
                "metadata": json.dumps({"persona_id": "default"}),
            },
        ]
        gov._semantic_dedupe_records(records)
        event_types = [e["event"] for e in events]
        assert "memory_semantic_dedup" in event_types


class TestTranscriptArchival:
    def test_old_transcripts_are_moved_to_archive(self, monkeypatch, tmp_path):
        """Transcripts older than retention_days should be archived."""
        gov, ws, _ = _stub_deps(monkeypatch, tmp_path)

        # Create an old transcript (60 days ago)
        from datetime import date, timedelta
        old_date = (date.today() - timedelta(days=60)).isoformat()
        old_file = ws / "memory" / "default" / f"{old_date}.md"
        old_file.parent.mkdir(parents=True, exist_ok=True)
        old_file.write_text("# Old transcript\n\n## Turn\n### User\nhello\n", encoding="utf-8")

        count = gov._archive_old_transcripts()
        assert count == 1
        assert not old_file.exists()

        archive_file = ws / "archive" / "memory" / "default" / f"{old_date}.md"
        assert archive_file.exists()
        assert "Old transcript" in archive_file.read_text(encoding="utf-8")

    def test_recent_transcripts_are_not_archived(self, monkeypatch, tmp_path):
        """Transcripts within retention_days should stay in place."""
        gov, ws, _ = _stub_deps(monkeypatch, tmp_path)

        from datetime import date, timedelta
        recent_date = (date.today() - timedelta(days=5)).isoformat()
        recent_file = ws / "memory" / "default" / f"{recent_date}.md"
        recent_file.parent.mkdir(parents=True, exist_ok=True)
        recent_file.write_text("# Recent transcript\n", encoding="utf-8")

        count = gov._archive_old_transcripts()
        assert count == 0
        assert recent_file.exists()

    def test_maintenance_result_includes_archived_count(self, monkeypatch, tmp_path):
        """run_memory_maintenance result should include transcripts_archived."""
        gov, ws, _ = _stub_deps(monkeypatch, tmp_path)

        from datetime import date, timedelta
        old_date = (date.today() - timedelta(days=60)).isoformat()
        old_file = ws / "memory" / "default" / f"{old_date}.md"
        old_file.parent.mkdir(parents=True, exist_ok=True)
        old_file.write_text("# Old\n## T\n### User\nhi\n### Assistant\nbye\n", encoding="utf-8")

        result = gov.run_memory_maintenance()
        assert "transcripts_archived" in result
        assert result["transcripts_archived"] == 1
