"""Memory summarization, deduplication, and maintenance."""

from __future__ import annotations

import hashlib
import json
import logging
import re
import shutil
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from pathlib import Path
from threading import Lock
from time import monotonic
from typing import Any

import numpy as np

from config import get_settings
from infra.db import (
    get_db,
    get_memories_table,
    normalize_vector,
    parse_record_metadata,
    resolve_vector_table_name,
)
from knowledge.workspace import ensure_workspace_scaffold, get_archive_paths, get_core_documents, get_workspace_root
from memory.embedder import get_embedder
from memory.importance import score_importance
from personas.personas import normalize_persona_id
from safety.observability import log_event

logger = logging.getLogger(__name__)

_maintenance_lock = Lock()
_last_maintenance_at: dict[str, float] = {}


@dataclass(slots=True)
class DailyMemorySummary:
    persona_id: str
    day: str
    fingerprint: str
    summary_text: str
    markdown: str


def maybe_run_memory_maintenance(force: bool = False, project_id: str = "default") -> dict[str, Any]:
    """Run maintenance on a throttle to avoid heavy work every turn."""
    cfg = get_settings()
    now = monotonic()

    with _maintenance_lock:
        last = _last_maintenance_at.get(project_id, 0.0)
        if not force and now - last < cfg.memory_maintenance_interval_seconds:
            return {"status": "skipped", "reason": "throttled"}
        result = run_memory_maintenance(project_id)
        _last_maintenance_at[project_id] = monotonic()
        return result


def run_memory_maintenance(project_id: str = "default") -> dict[str, Any]:
    """Summarize archived logs and rewrite the memories table without duplicates."""
    ensure_workspace_scaffold(project_id)
    archived_count = _archive_old_transcripts(project_id)
    summaries = _build_daily_summaries(project_id)
    _write_summary_document(summaries, project_id)

    existing_records = get_memories_table(project_id).to_arrow().to_pylist()
    deduped = _dedupe_memory_records(existing_records)
    deduped = _semantic_dedupe_records(deduped)
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

    get_db(project_id).create_table(
        resolve_vector_table_name("memories"),
        data=curated_records,
        mode="overwrite",
    )
    return {
        "status": "ok",
        "summary_days": len(summaries),
        "memory_records": len(curated_records),
        "transcripts_archived": archived_count,
    }


_SUMMARY_SECTION_HEADER = "# 記憶摘要"


def write_summary_and_reindex(
    *,
    persona_id: str,
    day: str,
    summary_text: str,
    source_turns: int = 0,
    session_id: str = "",
    project_id: str = "default",
) -> dict[str, Any]:
    """Write a summary block to the daily memory file and trigger reindex.

    Returns a status dict with writeback and reindex results.
    Skips writeback if the same fingerprint already exists for (persona_id, day).
    """
    ensure_workspace_scaffold(project_id)
    fingerprint = hashlib.sha256(summary_text.encode("utf-8")).hexdigest()
    normalized_persona = normalize_persona_id(persona_id)

    daily_path = _resolve_daily_file(normalized_persona, day, project_id)

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
    reindex_result = run_memory_maintenance(project_id)
    return {
        "status": "ok",
        "writeback": "appended",
        "fingerprint": fingerprint[:12],
        "reindex": reindex_result,
    }


def _resolve_daily_file(persona_id: str, day: str, project_id: str = "default") -> Path:
    """Resolve the path to a daily memory file."""
    ws = get_workspace_root(project_id)
    memory_dir = ws / "memory" / persona_id
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


_DATE_STEM_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")


def _archive_old_transcripts(project_id: str = "default") -> int:
    """Move transcript files older than retention_days to archive/memory/."""
    cfg = get_settings()
    cutoff = date.today() - timedelta(days=cfg.transcript_retention_days)
    ws = get_workspace_root(project_id)
    memory_dir = ws / "memory"
    archive_memory_dir = get_archive_paths(project_id)["memory_dir"]

    archived = 0
    for path in sorted(memory_dir.rglob("*.md")):
        if not _DATE_STEM_RE.match(path.stem):
            continue
        try:
            if date.fromisoformat(path.stem) >= cutoff:
                continue
        except ValueError:
            continue

        dest = archive_memory_dir / path.relative_to(memory_dir)
        dest.parent.mkdir(parents=True, exist_ok=True)

        if dest.exists():
            # Merge: append source content to existing archive
            with dest.open("a", encoding="utf-8") as f:
                f.write("\n\n" + path.read_text(encoding="utf-8-sig"))
            path.unlink()
        else:
            shutil.move(str(path), str(dest))
        archived += 1

    return archived


def _build_daily_summaries(project_id: str = "default") -> list[DailyMemorySummary]:
    ws = get_workspace_root(project_id)
    memory_dir = ws / "memory"
    summaries: list[DailyMemorySummary] = []
    for path in sorted(memory_dir.rglob("*.md")):
        if path.stem == "_summaries":
            continue
        summary = _summarize_daily_file(path, memory_dir)
        if summary is not None:
            summaries.append(summary)
    return summaries


def _summarize_daily_file(path: Path, memory_dir: Path) -> DailyMemorySummary | None:
    """Build a summary from a single daily transcript file, or None if empty."""
    content = path.read_text(encoding="utf-8-sig").strip()
    if not content:
        return None
    turns = _extract_turns(content)
    if not turns:
        return None

    persona_id = _persona_id_from_memory_path(path, memory_dir)
    day = path.stem
    fingerprint = hashlib.sha256(content.encode("utf-8")).hexdigest()
    user_topics = _collect_unique([t["user"] for t in turns], 6, 80)
    assistant_notes = _collect_unique([t["assistant"] for t in turns], 6, 100)

    summary_text = (
        f"Persona：{persona_id}\n日期：{day}\n對話輪次：{len(turns)}\n"
        f"使用者主題：\n" + "\n".join(f"- {t}" for t in user_topics) +
        f"\n回覆重點：\n" + "\n".join(f"- {n}" for n in assistant_notes)
    )
    markdown = (
        f"## [{persona_id}] {day}\n\n"
        f"- 指紋：`{fingerprint[:12]}`\n- 對話輪次：{len(turns)}\n\n"
        f"### 使用者主題\n" + "\n".join(f"- {t}" for t in user_topics) +
        f"\n\n### 回覆重點\n" + "\n".join(f"- {n}" for n in assistant_notes)
    ).strip()

    return DailyMemorySummary(persona_id, day, fingerprint, summary_text, markdown)


def _write_summary_document(summaries: list[DailyMemorySummary], project_id: str = "default") -> None:
    core_docs = get_core_documents(project_id)
    path = core_docs["memory_summaries"]
    header = ["# 記憶摘要 (MEMORY_SUMMARIES)", ""]
    body = [s.markdown + "\n" for s in summaries] if summaries else ["- 尚未有可整理的每日對話。"]
    path.write_text("\n".join(header + body).strip() + "\n", encoding="utf-8")


def _extract_turns(content: str) -> list[dict[str, str]]:
    turns: list[dict[str, str]] = []
    current_user: list[str] = []
    current_assistant: list[str] = []
    section: str | None = None

    def _flush_turn() -> None:
        if current_user or current_assistant:
            turns.append({"user": " ".join(current_user), "assistant": " ".join(current_assistant)})

    for line in content.splitlines():
        line = line.strip()
        if line.startswith("## "):
            _flush_turn()
            current_user.clear()
            current_assistant.clear()
            section = None
        elif line == "### User":
            section = "user"
        elif line == "### Assistant":
            section = "assistant"
        elif line:
            if section == "user":
                current_user.append(line)
            elif section == "assistant":
                current_assistant.append(line)

    _flush_turn()
    return turns


def _collect_unique(items: list[str], limit: int, max_chars: int) -> list[str]:
    unique: list[str] = []
    for item in items:
        normalized = " ".join(item.split())[:max_chars]
        if normalized and normalized not in unique:
            unique.append(normalized)
            if len(unique) >= limit:
                break
    return unique


def _build_summary_records(summaries: list[DailyMemorySummary]) -> list[dict[str, Any]]:
    if not summaries:
        return []

    vectors = get_embedder().encode([s.summary_text for s in summaries])
    records: list[dict[str, Any]] = []
    for summary, vector in zip(summaries, vectors):
        importance = score_importance(summary.summary_text)
        records.append({
            "text": summary.summary_text,
            "vector": normalize_vector(vector),
            "source": "memory_summary",
            "date": summary.day,
            "metadata": json.dumps({
                "kind": "daily_summary",
                "persona_id": summary.persona_id,
                "day": summary.day,
                "fingerprint": summary.fingerprint,
                "importance": importance.score,
                "importance_level": importance.level,
            }, ensure_ascii=False),
        })
    return records


def _dedupe_memory_records(records: list[dict[str, Any]]) -> list[dict[str, Any]]:
    seen_keys: set[tuple[str, str]] = set()
    deduped: list[dict[str, Any]] = []

    for record in records:
        if _is_placeholder_record(record):
            deduped.append(record)
            continue

        normalized = _normalize_memory_text(str(record.get("text", "")))
        persona_id = _memory_persona_id(record)
        if not normalized:
            continue

        key = (normalized, persona_id)
        if key not in seen_keys:
            seen_keys.add(key)
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
    return normalize_persona_id(raw) if raw else "global"


def _persona_id_from_memory_path(path: Path, memory_dir: Path) -> str:
    relative = path.relative_to(memory_dir)
    return normalize_persona_id(relative.parts[0]) if len(relative.parts) > 1 else "default"


# ---------------------------------------------------------------------------
# Semantic dedup / merge
# ---------------------------------------------------------------------------


def _semantic_dedupe_records(records: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Remove near-duplicate memory records using cosine similarity."""
    cfg = get_settings()
    threshold = cfg.memory_merge_similarity_threshold

    groups: dict[str, list[tuple[int, dict[str, Any]]]] = {}
    for idx, record in enumerate(records):
        groups.setdefault(_memory_persona_id(record), []).append((idx, record))

    drop_indices: set[int] = set()
    for group in groups.values():
        vectors_with_idx = [(i, r.get("vector")) for i, r in group if r.get("vector") is not None]
        drop_indices.update(_find_merge_drops(vectors_with_idx, records, threshold, drop_indices))

    if drop_indices:
        logger.info("semantic dedup: merged %d pairs (threshold=%.2f)", len(drop_indices), threshold)
        log_event("memory_semantic_dedup", merged_pairs=len(drop_indices), threshold=threshold)

    return [r for idx, r in enumerate(records) if idx not in drop_indices]


def _find_merge_drops(
    vectors_with_idx: list[tuple[int, Any]],
    records: list[dict[str, Any]],
    threshold: float,
    already_dropped: set[int],
) -> set[int]:
    """Compare all pairs in a persona group and return indices to drop."""
    drops: set[int] = set()
    count = len(vectors_with_idx)
    for i in range(count):
        idx_a, vec_a = vectors_with_idx[i]
        if idx_a in already_dropped or idx_a in drops:
            continue
        for j in range(i + 1, count):
            idx_b, vec_b = vectors_with_idx[j]
            if idx_b in already_dropped or idx_b in drops:
                continue
            if _cosine_similarity(vec_a, vec_b) >= threshold:
                older_idx, _ = _merge_memory_pair(idx_a, records[idx_a], idx_b, records[idx_b])
                drops.add(older_idx)
    return drops


def _cosine_similarity(vec_a: Any, vec_b: Any) -> float:
    a = np.asarray(vec_a, dtype=np.float32)
    b = np.asarray(vec_b, dtype=np.float32)
    dot = np.dot(a, b)
    norm_a = np.linalg.norm(a)
    norm_b = np.linalg.norm(b)
    if norm_a == 0 or norm_b == 0:
        return 0.0
    return float(dot / (norm_a * norm_b))


def _merge_memory_pair(
    idx_a: int,
    record_a: dict[str, Any],
    idx_b: int,
    record_b: dict[str, Any],
) -> tuple[int, int]:
    date_a = str(record_a.get("date", ""))
    date_b = str(record_b.get("date", ""))

    if date_a < date_b:
        return idx_a, idx_b
    if date_b < date_a:
        return idx_b, idx_a
    if idx_a < idx_b:
        return idx_a, idx_b
    return idx_b, idx_a
