"""Automatic learning and error journaling for workspace files."""

from __future__ import annotations

import re
from datetime import datetime
from pathlib import Path

from knowledge.workspace import CORE_DOCUMENTS, ensure_workspace_scaffold

_LEARNING_PATTERNS = (
    (re.compile(r"(簡短|簡潔|精簡|直接)"), "使用者偏好簡潔、直接的回答。"),
    (re.compile(r"(繁體中文|繁中)"), "使用者偏好使用繁體中文回覆。"),
    (re.compile(r"(不要|別用).*(emoji|表情|貼圖)"), "使用者偏好不要使用 emoji 或表情符號。"),
    (re.compile(r"(條列|列表|bullet)"), "使用者在整理資訊時偏好條列式輸出。"),
    (re.compile(r"(不要|別)長篇大論"), "使用者偏好避免長篇大論。"),
)


def capture_learnings_from_message(user_message: str) -> list[str]:
    """Append stable user preferences into LEARNINGS.md if they are new."""
    ensure_workspace_scaffold()
    normalized = " ".join(user_message.strip().split())
    if not normalized:
        return []

    candidates = [
        learning
        for pattern, learning in _LEARNING_PATTERNS
        if pattern.search(normalized)
    ]
    if not candidates:
        return []

    path = CORE_DOCUMENTS["learnings"]
    existing = path.read_text(encoding="utf-8-sig")
    appended: list[str] = []

    with path.open("a", encoding="utf-8") as handle:
        for learning in candidates:
            if learning in existing or learning in appended:
                continue
            handle.write(f"- {learning}\n")
            appended.append(learning)

    return appended


def record_error_event(area: str, summary: str, detail: str = "") -> None:
    """Append a timestamped error line into ERRORS.md."""
    ensure_workspace_scaffold()
    path = CORE_DOCUMENTS["errors"]
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
