"""Memory summarization, deduplication, and maintenance."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from threading import Lock
from time import monotonic
from typing import Any

from config import get_settings
from infra.db import get_db, get_memories_table, normalize_vector, parse_record_metadata
from knowledge.workspace import CORE_DOCUMENTS, WORKSPACE_ROOT, ensure_workspace_scaffold
from memory.embedder import get_embedder
from personas.personas import normalize_persona_id
from safety.observability import log_event

_maintenance_lock = Lock()
_last_maintenance_at = 0.0


@dataclass(slots=True)
class DailyMemorySummary:
    persona_id: str
    day: str
    fingerprint: str
    summary_text: str
    markdown: str


def maybe_run_memory_maintenance(force: bool = False) -> dict[str, Any]:
    """Run maintenance on a throttle to avoid heavy work every turn."""
    global _last_maintenance_at
    cfg = get_settings()
    now = monotonic()

    with _maintenance_lock:
        if not force and now - _last_maintenance_at < cfg.memory_maintenance_interval_seconds:
            return {"status": "skipped", "reason": "throttled"}
        result = run_memory_maintenance()
        _last_maintenance_at = monotonic()
        return result


def run_memory_maintenance() -> dict[str, Any]:
    """Summarize archived logs and rewrite the memories table without duplicates."""
    ensure_workspace_scaffold()
    summaries = _build_daily_summaries()
    _write_summary_document(summaries)

    existing_records = get_memories_table().to_arrow().to_pylist()
    deduped = _dedupe_memory_records(existing_records)
    non_summary = [
        record
        for record in deduped
        if _memory_kind(record) != "daily_summary"
    ]
    curated_records = non_summary + _build_summary_records(summaries)

    if not curated_records:
        curated_records = [
            {
                "text": "系統初始化記錄",
                "vector": normalize_vector(get_embedder().encode(["系統初始化記錄"])[0]),
                "source": "system",
                "date": date.today().isoformat(),
                "metadata": json.dumps({"placeholder": True}, ensure_ascii=False),
            }
        ]

    get_db().create_table("memories", data=curated_records, mode="overwrite")
    return {
        "status": "ok",
        "summary_days": len(summaries),
        "memory_records": len(curated_records),
    }


_SUMMARY_SECTION_HEADER = "# 記憶摘要"


def write_summary_and_reindex(
    *,
    persona_id: str,
    day: str,
    summary_text: str,
    source_turns: int = 0,
    session_id: str = "",
) -> dict[str, Any]:
    """Write a summary block to the daily memory file and trigger reindex.

    Returns a status dict with writeback and reindex results.
    Skips writeback if the same fingerprint already exists for (persona_id, day).
    """
    ensure_workspace_scaffold()
    fingerprint = hashlib.sha256(summary_text.encode("utf-8")).hexdigest()
    normalized_persona = normalize_persona_id(persona_id)

    daily_path = _resolve_daily_file(normalized_persona, day)

    # Duplicate check: scan existing summary section for same fingerprint
    if _daily_file_has_fingerprint(daily_path, fingerprint):
        log_event(
            "memory_writeback_skipped",
            persona_id=normalized_persona,
            day=day,
            reason="duplicate_fingerprint",
        )
        return {"status": "skipped", "reason": "duplicate_fingerprint"}

    # Append summary block
    block = _format_summary_block(
        persona_id=normalized_persona,
        day=day,
        fingerprint=fingerprint,
        summary_text=summary_text,
        source_turns=source_turns,
        session_id=session_id,
    )
    _append_summary_block(daily_path, block)

    log_event(
        "memory_writeback_completed",
        persona_id=normalized_persona,
        day=day,
        fingerprint=fingerprint[:12],
    )

    # Trigger reindex
    reindex_result = run_memory_maintenance()
    return {
        "status": "ok",
        "writeback": "appended",
        "fingerprint": fingerprint[:12],
        "reindex": reindex_result,
    }


def _resolve_daily_file(persona_id: str, day: str) -> Path:
    """Resolve the path to a daily memory file."""
    memory_dir = WORKSPACE_ROOT / "memory" / persona_id
    memory_dir.mkdir(parents=True, exist_ok=True)
    return memory_dir / f"{day}.md"


def _daily_file_has_fingerprint(path: Path, fingerprint: str) -> bool:
    """Check if a daily file already contains a summary with the given fingerprint."""
    if not path.exists():
        return False
    content = path.read_text(encoding="utf-8-sig")
    return f"fingerprint: {fingerprint[:12]}" in content


def _format_summary_block(
    *,
    persona_id: str,
    day: str,
    fingerprint: str,
    summary_text: str,
    source_turns: int,
    session_id: str,
) -> str:
    """Format a stable summary block for appending to the daily file."""
    from datetime import datetime

    ts = datetime.now().isoformat(timespec="seconds")
    lines = [
        f"## {ts} | session {session_id}",
        "",
        f"- persona_id: {persona_id}",
        f"- fingerprint: {fingerprint[:12]}",
        f"- source_turns: {source_turns}",
        "",
        "### Summary",
        summary_text,
        "",
    ]
    return "\n".join(lines)


def _append_summary_block(path: Path, block: str) -> None:
    """Append a summary block to the daily file under the summary section."""
    if not path.exists():
        path.write_text(
            f"# {path.stem} 對話日誌\n\n"
            f"{_SUMMARY_SECTION_HEADER}\n\n"
            f"{block}\n",
            encoding="utf-8",
        )
        return

    content = path.read_text(encoding="utf-8-sig")
    if _SUMMARY_SECTION_HEADER in content:
        # Append after existing summary section
        content = content.rstrip() + "\n\n" + block + "\n"
    else:
        # Add summary section at end
        content = content.rstrip() + "\n\n" + _SUMMARY_SECTION_HEADER + "\n\n" + block + "\n"

    path.write_text(content, encoding="utf-8")


def _build_daily_summaries() -> list[DailyMemorySummary]:
    summaries: list[DailyMemorySummary] = []
    memory_dir = WORKSPACE_ROOT / "memory"
    for path in sorted(memory_dir.rglob("*.md")):
        if path.stem == "_summaries":
            continue
        content = path.read_text(encoding="utf-8-sig").strip()
        if not content:
            continue
        turns = _extract_turns(content)
        if not turns:
            continue

        persona_id = _persona_id_from_memory_path(path, memory_dir)
        day = path.stem
        fingerprint = hashlib.sha256(content.encode("utf-8")).hexdigest()
        user_topics = _collect_unique([turn["user"] for turn in turns], 6, 80)
        assistant_notes = _collect_unique([turn["assistant"] for turn in turns], 6, 100)
        summary_text = "\n".join(
            [
                f"Persona：{persona_id}",
                f"日期：{day}",
                f"對話輪次：{len(turns)}",
                "使用者主題：",
                *[f"- {topic}" for topic in user_topics],
                "回覆重點：",
                *[f"- {note}" for note in assistant_notes],
            ]
        )
        markdown = "\n".join(
            [
                f"## [{persona_id}] {day}",
                "",
                f"- 指紋：`{fingerprint[:12]}`",
                f"- 對話輪次：{len(turns)}",
                "",
                "### 使用者主題",
                *[f"- {topic}" for topic in user_topics],
                "",
                "### 回覆重點",
                *[f"- {note}" for note in assistant_notes],
                "",
            ]
        ).strip()
        summaries.append(
            DailyMemorySummary(
                persona_id=persona_id,
                day=day,
                fingerprint=fingerprint,
                summary_text=summary_text,
                markdown=markdown,
            )
        )
    return summaries


def _write_summary_document(summaries: list[DailyMemorySummary]) -> None:
    path = CORE_DOCUMENTS["memory_summaries"]
    lines = ["# 記憶摘要 (MEMORY_SUMMARIES)", ""]
    if not summaries:
        lines.append("- 尚未有可整理的每日對話。")
    else:
        for summary in summaries:
            lines.append(summary.markdown)
            lines.append("")
    path.write_text("\n".join(lines).strip() + "\n", encoding="utf-8")


def _extract_turns(content: str) -> list[dict[str, str]]:
    turns: list[dict[str, str]] = []
    current_user: list[str] = []
    current_assistant: list[str] = []
    section: str | None = None

    def _flush_turn() -> None:
        if current_user or current_assistant:
            turns.append(
                {
                    "user": " ".join(current_user),
                    "assistant": " ".join(current_assistant),
                }
            )

    for raw_line in content.splitlines():
        line = raw_line.strip()
        if line.startswith("## "):
            _flush_turn()
            current_user = []
            current_assistant = []
            section = None
            continue
        if line == "### User":
            section = "user"
            continue
        if line == "### Assistant":
            section = "assistant"
            continue
        if not line or section is None:
            continue
        if section == "user":
            current_user.append(line)
        else:
            current_assistant.append(line)

    _flush_turn()
    return [turn for turn in turns if turn["user"] or turn["assistant"]]


def _collect_unique(items: list[str], limit: int, max_chars: int) -> list[str]:
    unique: list[str] = []
    for item in items:
        normalized = " ".join(item.split())
        if not normalized:
            continue
        normalized = normalized[:max_chars]
        if normalized in unique:
            continue
        unique.append(normalized)
        if len(unique) >= limit:
            break
    return unique


def _build_summary_records(summaries: list[DailyMemorySummary]) -> list[dict[str, Any]]:
    if not summaries:
        return []

    vectors = get_embedder().encode([summary.summary_text for summary in summaries])
    records: list[dict[str, Any]] = []
    for summary, vector in zip(summaries, vectors):
        records.append(
            {
                "text": summary.summary_text,
                "vector": normalize_vector(vector),
                "source": "memory_summary",
                "date": summary.day,
                "metadata": json.dumps(
                    {
                        "kind": "daily_summary",
                        "persona_id": summary.persona_id,
                        "day": summary.day,
                        "fingerprint": summary.fingerprint,
                    },
                    ensure_ascii=False,
                ),
            }
        )
    return records


def _dedupe_memory_records(records: list[dict[str, Any]]) -> list[dict[str, Any]]:
    seen_texts: set[tuple[str, str]] = set()
    deduped: list[dict[str, Any]] = []

    for record in records:
        normalized = _normalize_memory_text(str(record.get("text", "")))
        persona_id = _memory_persona_id(record)
        if not normalized:
            continue
        if _is_placeholder_record(record):
            deduped.append(record)
            continue
        key = (normalized, persona_id)
        if key in seen_texts:
            continue
        seen_texts.add(key)
        deduped.append(record)

    return deduped


def _normalize_memory_text(text: str) -> str:
    return " ".join(text.split())


def _is_placeholder_record(record: dict[str, Any]) -> bool:
    metadata = parse_record_metadata(record)
    return bool(metadata.get("placeholder"))


def _memory_kind(record: dict[str, Any]) -> str:
    metadata = parse_record_metadata(record)
    return str(metadata.get("kind", "")).strip()


def _memory_persona_id(record: dict[str, Any]) -> str:
    metadata = parse_record_metadata(record)
    raw = str(metadata.get("persona_id", "")).strip()
    if not raw:
        return "global"
    return normalize_persona_id(raw)


def _persona_id_from_memory_path(path: Path, memory_dir: Path) -> str:
    relative = path.relative_to(memory_dir)
    if len(relative.parts) == 1:
        return "default"
    return normalize_persona_id(relative.parts[0])
