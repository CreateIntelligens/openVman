"""Shared path helpers and constants for the dreaming subsystem."""

from __future__ import annotations

import re
from datetime import date
from pathlib import Path

from knowledge.workspace import get_workspace_root

DATE_STEM_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")

SOURCE_DREAMING = "dreaming"
TABLE_MEMORIES = "memories"
TABLE_KNOWLEDGE = "knowledge"


def dreams_dir(project_id: str) -> Path:
    """Return the .dreams state directory for a project."""
    return get_workspace_root(project_id) / "dreaming" / ".dreams"


def write_dreaming_report(project_id: str, phase: str, lines: list[str]) -> Path:
    """Write a dated markdown report to dreaming/{phase}/YYYY-MM-DD.md."""
    today = date.today().isoformat()
    report_path = get_workspace_root(project_id) / "dreaming" / phase / f"{today}.md"
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text("\n".join(lines), encoding="utf-8")
    return report_path
