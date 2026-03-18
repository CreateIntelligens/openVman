"""Error journaling for workspace files with rotation support."""

from __future__ import annotations

import re
from datetime import datetime
from pathlib import Path

from config import get_settings
from knowledge.workspace import ensure_workspace_scaffold, get_archive_paths, get_core_documents


_MONTH_RE = re.compile(r"^\- \[(\d{4}-\d{2})")


def record_error_event(area: str, summary: str, detail: str = "", project_id: str = "default") -> None:
    """Append a timestamped error line into ERRORS.md, rotating if needed."""
    ensure_workspace_scaffold(project_id)
    path = get_core_documents(project_id)["errors"]
    timestamp = datetime.now().isoformat(timespec="seconds")
    new_line = f"- [{timestamp}] {area}: {summary}"
    if detail.strip():
        new_line += f" | {detail.strip()}"

    existing_lines = _read_all_lines(path)

    # Dedup against recent tail
    tail_text = "\n".join(existing_lines[-20:])
    if new_line in tail_text:
        return

    all_lines = [*existing_lines, new_line]
    trimmed = _rotate_if_needed(all_lines, get_settings().errors_rotation_max_lines, project_id)

    path.write_text("\n".join(trimmed) + "\n", encoding="utf-8")


def _read_all_lines(path: Path) -> list[str]:
    """Read all non-empty content lines from a file."""
    if not path.exists():
        return []
    return [line for line in path.read_text(encoding="utf-8-sig").splitlines() if line.strip()]


def _rotate_if_needed(lines: list[str], max_lines: int, project_id: str) -> list[str]:
    """If lines exceed max_lines, archive old lines and return the trimmed tail."""
    if len(lines) <= max_lines:
        return lines

    overflow_count = len(lines) - max_lines
    old_lines = lines[:overflow_count]
    _archive_error_lines(old_lines, project_id)
    return lines[overflow_count:]


def _archive_error_lines(lines: list[str], project_id: str) -> None:
    """Append error lines to monthly archive files under archive/errors/."""
    archive_paths = get_archive_paths(project_id)
    errors_dir = archive_paths["errors_dir"]
    errors_dir.mkdir(parents=True, exist_ok=True)

    by_month: dict[str, list[str]] = {}
    for line in lines:
        month_key = _extract_month_key(line)
        by_month.setdefault(month_key, []).append(line)

    for month_key, month_lines in by_month.items():
        archive_file = errors_dir / f"{month_key}.md"
        with archive_file.open("a", encoding="utf-8") as f:
            f.write("\n".join(month_lines) + "\n")


def _extract_month_key(line: str) -> str:
    """Extract YYYY-MM from a line like '- [2026-03-15T10:00:00] ...'."""
    match = _MONTH_RE.match(line)
    return match.group(1) if match else "unknown"
