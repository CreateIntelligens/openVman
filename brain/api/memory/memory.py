"""Persistent memories and SQLite-backed chat session management."""

from __future__ import annotations

import json
from datetime import date, datetime
from typing import Any
from uuid import uuid4

from infra.db import get_memories_table
from infra.project_context import get_project_session_store, resolve_project_context
from knowledge.workspace import ensure_workspace_scaffold
from memory.session_store import SessionState, SessionStore
from personas.personas import normalize_persona_id


def build_memory_record(
    text: str,
    vector: list[float],
    source: str = "user",
    metadata: dict[str, Any] | None = None,
    record_date: str | None = None,
    persona_id: str | None = None,
) -> dict[str, Any]:
    """建立與 memories 表一致的資料格式。"""
    merged_metadata = dict(metadata or {})
    if persona_id is not None:
        merged_metadata["persona_id"] = normalize_persona_id(persona_id)
    return {
        "text": text,
        "vector": vector,
        "source": source,
        "date": record_date or date.today().isoformat(),
        "metadata": json.dumps(merged_metadata, ensure_ascii=False),
    }


def add_memory(
    text: str,
    vector: list[float],
    source: str = "user",
    metadata: dict[str, Any] | None = None,
    persona_id: str = "default",
    project_id: str = "default",
) -> dict[str, Any]:
    """寫入一筆記憶並回傳實際寫入內容。"""
    record = build_memory_record(
        text=text,
        vector=vector,
        source=source,
        metadata=metadata,
        persona_id=persona_id,
    )
    get_memories_table(project_id).add([record])
    return record


def get_or_create_session(
    session_id: str | None = None,
    persona_id: str = "default",
    project_id: str = "default",
) -> SessionState:
    """Return an existing chat session or create a new one."""
    session_key = (session_id or "").strip() or str(uuid4())
    return get_session_store(project_id).get_or_create_session(session_key, persona_id)


def append_session_message(
    session_id: str,
    persona_id: str,
    role: str,
    content: str,
    project_id: str = "default",
) -> SessionState:
    """Append a message to the session and enforce max rounds."""
    return get_session_store(project_id).append_message(session_id, persona_id, role, content)


def list_session_messages(
    session_id: str,
    persona_id: str | None = None,
    project_id: str = "default",
) -> list[dict[str, str]]:
    """Return serialized session messages for APIs and prompt building."""
    messages = get_session_store(project_id).list_messages(session_id, persona_id)
    return [dict(message) for message in messages]


def get_session_updated_at(
    session_id: str,
    persona_id: str | None = None,
    project_id: str = "default",
) -> str | None:
    """Return the session updated_at timestamp without mutating session state."""
    return get_session_store(project_id).get_session_updated_at(session_id, persona_id)


def archive_session_turn(
    session_id: str,
    user_message: str,
    assistant_message: str,
    persona_id: str = "default",
    project_id: str = "default",
) -> None:
    """Append the latest conversation turn into the daily markdown log."""
    root = ensure_workspace_scaffold(project_id)
    persona_key = normalize_persona_id(persona_id)
    log_dir = root / "memory"
    if persona_key != "default":
        log_dir = log_dir / persona_key
    log_dir.mkdir(parents=True, exist_ok=True)

    today = date.today().isoformat()
    now = datetime.now().strftime("%H:%M:%S")
    path = log_dir / f"{today}.md"

    if not path.exists():
        path.write_text(f"# {today} 對話日誌\n\n", encoding="utf-8")

    with path.open("a", encoding="utf-8") as handle:
        handle.write(f"## {now} | session {session_id}\n\n")
        handle.write(f"### User\n{user_message.strip()}\n\n")
        handle.write(f"### Assistant\n{assistant_message.strip()}\n\n")


def get_session_store(project_id: str = "default") -> SessionStore:
    ctx = resolve_project_context(project_id)
    return get_project_session_store(ctx)
