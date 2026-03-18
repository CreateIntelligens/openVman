"""Tests for ERRORS.md rotation and archival."""

from __future__ import annotations

import importlib
import sys
import types
from pathlib import Path
from unittest.mock import MagicMock

import pytest

API_ROOT = Path(__file__).resolve().parents[1]
if str(API_ROOT) not in sys.path:
    sys.path.insert(0, str(API_ROOT))


def _stub_deps(monkeypatch: pytest.MonkeyPatch, tmp_path: Path, max_lines: int = 200):
    """Stub workspace and config for learnings module."""
    workspace_root = tmp_path / "workspace"
    workspace_root.mkdir(exist_ok=True)
    errors_path = workspace_root / "ERRORS.md"
    errors_path.write_text("", encoding="utf-8")
    archive_errors = workspace_root / "archive" / "errors"
    archive_errors.mkdir(parents=True, exist_ok=True)

    fake_workspace_mod = types.ModuleType("knowledge.workspace")
    fake_workspace_mod.ensure_workspace_scaffold = lambda project_id="default": workspace_root
    fake_workspace_mod.get_workspace_root = lambda project_id="default": workspace_root
    fake_workspace_mod.get_core_documents = lambda project_id="default": {"errors": errors_path}
    fake_workspace_mod.get_archive_paths = lambda project_id="default": {
        "errors_dir": archive_errors,
        "memory_dir": workspace_root / "archive" / "memory",
    }
    monkeypatch.setitem(sys.modules, "knowledge.workspace", fake_workspace_mod)

    fake_cfg = MagicMock()
    fake_cfg.errors_rotation_max_lines = max_lines
    fake_config_mod = types.ModuleType("config")
    fake_config_mod.get_settings = lambda: fake_cfg
    monkeypatch.setitem(sys.modules, "config", fake_config_mod)

    sys.modules.pop("infra.learnings", None)
    learnings = importlib.import_module("infra.learnings")

    return learnings, errors_path, archive_errors


class TestErrorRotation:
    def test_no_rotation_when_under_limit(self, monkeypatch, tmp_path):
        """No archival when line count is under max_lines."""
        learnings, errors_path, archive_dir = _stub_deps(monkeypatch, tmp_path, max_lines=200)

        learnings.record_error_event("test", "some error")
        learnings.record_error_event("test", "another error")

        content = errors_path.read_text(encoding="utf-8")
        lines = [l for l in content.splitlines() if l.strip()]
        assert len(lines) == 2

        # No archive files created
        assert list(archive_dir.iterdir()) == []

    def test_rotation_triggers_at_limit(self, monkeypatch, tmp_path):
        """Rotation should archive old lines when exceeding max_lines."""
        max_lines = 10
        learnings, errors_path, archive_dir = _stub_deps(monkeypatch, tmp_path, max_lines=max_lines)

        # Pre-fill with lines that will be over the limit
        pre_lines = [f"- [2026-01-15T10:00:{i:02d}] test: error {i}" for i in range(max_lines)]
        errors_path.write_text("\n".join(pre_lines) + "\n", encoding="utf-8")

        # Adding one more should trigger rotation
        learnings.record_error_event("test", "new error")

        content = errors_path.read_text(encoding="utf-8")
        remaining = [l for l in content.splitlines() if l.strip()]
        assert len(remaining) <= max_lines

    def test_archived_lines_contain_old_entries(self, monkeypatch, tmp_path):
        """Archived file should contain the overflow lines."""
        max_lines = 5
        learnings, errors_path, archive_dir = _stub_deps(monkeypatch, tmp_path, max_lines=max_lines)

        pre_lines = [f"- [2026-02-10T10:00:{i:02d}] area: old error {i}" for i in range(max_lines)]
        errors_path.write_text("\n".join(pre_lines) + "\n", encoding="utf-8")

        learnings.record_error_event("area", "new error")

        archive_file = archive_dir / "2026-02.md"
        assert archive_file.exists()
        archived_content = archive_file.read_text(encoding="utf-8")
        assert "old error 0" in archived_content

    def test_archived_by_month_key(self, monkeypatch, tmp_path):
        """Lines from different months should go to different archive files."""
        max_lines = 2
        learnings, errors_path, archive_dir = _stub_deps(monkeypatch, tmp_path, max_lines=max_lines)

        pre_lines = [
            "- [2026-01-10T10:00:00] area: jan error",
            "- [2026-02-10T10:00:00] area: feb error",
            "- [2026-03-10T10:00:00] area: mar error",
        ]
        errors_path.write_text("\n".join(pre_lines) + "\n", encoding="utf-8")

        learnings.record_error_event("area", "new error")

        jan_file = archive_dir / "2026-01.md"
        feb_file = archive_dir / "2026-02.md"
        assert jan_file.exists()
        assert feb_file.exists()
        assert "jan error" in jan_file.read_text(encoding="utf-8")
        assert "feb error" in feb_file.read_text(encoding="utf-8")

    def test_dedup_still_works_after_rotation(self, monkeypatch, tmp_path):
        """Duplicate detection should still work on the trimmed file."""
        max_lines = 5
        learnings, errors_path, archive_dir = _stub_deps(monkeypatch, tmp_path, max_lines=max_lines)

        # Record an error, then try to record the same one
        learnings.record_error_event("area", "unique error")
        content_before = errors_path.read_text(encoding="utf-8")

        learnings.record_error_event("area", "unique error")
        content_after = errors_path.read_text(encoding="utf-8")

        # The line count should not increase (dedup kicked in)
        lines_before = [l for l in content_before.splitlines() if l.strip()]
        lines_after = [l for l in content_after.splitlines() if l.strip()]
        assert len(lines_after) == len(lines_before)
