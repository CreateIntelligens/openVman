"""Error journaling for workspace files."""

from __future__ import annotations

from datetime import datetime
from pathlib import Path

from knowledge.workspace import get_core_documents, ensure_workspace_scaffold


def record_error_event(area: str, summary: str, detail: str = "", project_id: str = "default") -> None:
    """Append a timestamped error line into ERRORS.md."""
    ensure_workspace_scaffold(project_id)
    core_docs = get_core_documents(project_id)
    path = core_docs["errors"]
    timestamp = datetime.now().isoformat(timespec="seconds")
    line = f"- [{timestamp}] {area}: {summary}"
    if detail.strip():
        line += f" | {detail.strip()}"

    recent_tail = _read_recent_tail(path)
    if line in recent_tail:
        return

    with path.open("a", encoding="utf-8") as handle:
        handle.write(f"{line}\n")


def _read_recent_tail(path: Path, max_lines: int = 20) -> str:
    if not path.exists():
        return ""
    lines = path.read_text(encoding="utf-8-sig").splitlines()
    return "\n".join(lines[-max_lines:])
