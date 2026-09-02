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
    metadata: dict[str, Any] | None = None,
) -> SessionState:
    """Append a message to the session and enforce max rounds."""
    state, _ = get_session_store(project_id).append_message(
        session_id,
        persona_id,
        role,
        content,
        metadata=metadata,
    )
    return state


def append_session_message_with_id(
    session_id: str,
    persona_id: str,
    role: str,
    content: str,
    project_id: str = "default",
    metadata: dict[str, Any] | None = None,
) -> tuple[SessionState, int]:
    """Append and return the new message's row id for later metadata patches."""
    return get_session_store(project_id).append_message(
        session_id,
        persona_id,
        role,
        content,
        metadata=metadata,
    )


def update_session_message_metadata(
    message_id: int,
    metadata: dict[str, Any],
    project_id: str = "default",
) -> None:
    """Merge metadata into an existing message (used for late PII warnings)."""
    get_session_store(project_id).update_message_metadata(message_id, metadata)


def list_session_messages(
    session_id: str,
    persona_id: str | None = None,
    project_id: str = "default",
) -> list[dict[str, Any]]:
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
    log_dir = root / "memory" / persona_key
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


def list_memories(
    project_id: str = "default",
    page: int = 1,
    page_size: int = 20,
) -> dict[str, Any]:
    """List memories with pagination, excluding vectors."""
    table = get_memories_table(project_id)
    records = table.to_arrow().to_pylist()
    if not records:
        return {"memories": [], "total": 0, "page": page, "page_size": page_size}

    records = [
        {key: value for key, value in record.items() if key != "vector"}
        for record in records
    ]
    dated_records = [record for record in records if record.get("date") is not None]
    undated_records = [record for record in records if record.get("date") is None]
    dated_records.sort(key=lambda record: str(record["date"]), reverse=True)
    records = dated_records + undated_records

    total = len(records)
    start = (page - 1) * page_size
    end = start + page_size
    return {
        "memories": records[start:end],
        "total": total,
        "page": page,
        "page_size": page_size,
    }


def delete_memory(
    project_id: str = "default",
    text: str = "",
) -> bool:
    """Delete a memory record by exact text match."""
    # LanceDB's delete predicate is an SQL expression.  It has no parameter
    # binding API, so reject expression syntax at the boundary instead of
    # interpolating attacker-controlled text into a predicate.  Apostrophes
    # and operators can be stored in memories; deletion of those records must
    # use the administrative data path rather than this legacy text endpoint.
    if not text or any(char in text for char in "'\"\\;=<>`()"):
        raise ValueError("memory text contains unsupported filter syntax")
    table = get_memories_table(project_id)
    table.delete(f"text = '{text}'")
    return True


def list_sessions_for_project(
    project_id: str = "default",
    persona_id: str | None = None,
    date_from: str | None = None,
    date_to: str | None = None,
    search: str | None = None,
) -> list[dict[str, Any]]:
    """List all chat sessions for a project."""
    return get_session_store(project_id).list_sessions(
        persona_id=persona_id,
        date_from=date_from,
        date_to=date_to,
        search=search,
    )


def delete_session_for_project(
    project_id: str = "default",
    session_id: str = "",
) -> bool:
    """Delete a chat session for a project."""
    return get_session_store(project_id).delete_session(session_id)


def get_session_store(project_id: str = "default") -> SessionStore:
    ctx = resolve_project_context(project_id)
    return get_project_session_store(ctx)
