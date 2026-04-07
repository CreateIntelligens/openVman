"""Light Phase — collect candidates from daily files + recall traces.

Scans recent daily memory files, correlates with recall trace data,
deduplicates, and writes candidates to .dreams/candidates.json.
"""

from __future__ import annotations

import hashlib
import json
import logging
import re
from collections import defaultdict
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from config import get_settings
from knowledge.workspace import get_workspace_root
from memory.dreaming.paths import DATE_STEM_RE, dreams_dir
from memory.dreaming.recall_tracker import read_traces
from memory.dreaming.scoring import build_signals, score_candidate
from memory.importance import score_importance

logger = logging.getLogger(__name__)

_SUMMARY_HEADER_RE = re.compile(r"^###?\s+Summary", re.IGNORECASE)


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def run_light_phase(project_id: str = "default") -> dict[str, Any]:
    """Execute the Light phase and write candidates.json.

    Returns a status dict with candidate_count and details.
    """
    cfg = get_settings()
    lookback = cfg.dreaming_lookback_days
    limit = cfg.dreaming_candidate_limit

    # 1. Collect text fragments from daily files
    fragments = _collect_daily_fragments(project_id, lookback)
    logger.info("light phase: collected %d fragments from daily files", len(fragments))

    # 2. Read recall traces and build stats
    traces = read_traces(project_id, days=lookback)
    trace_stats = _build_trace_stats(traces)
    logger.info("light phase: %d unique texts in recall traces", len(trace_stats))

    # 3. Read REM phase signals (if available)
    phase_signals = _read_phase_signals(project_id)

    # 4. Merge fragments with trace data
    candidates = _merge_candidates(
        fragments, trace_stats, phase_signals, lookback,
    )

    # 5. Dedup by fingerprint
    candidates = _dedup_candidates(candidates)

    # 6. Limit
    candidates = candidates[:limit]

    # 7. Score each candidate
    for c in candidates:
        c["score"] = score_candidate(c)

    # 8. Sort by score descending
    candidates.sort(key=lambda c: c["score"], reverse=True)

    # 9. Write candidates.json
    _write_candidates(project_id, candidates)

    return {
        "status": "ok",
        "candidate_count": len(candidates),
        "fragment_count": len(fragments),
        "trace_unique_texts": len(trace_stats),
    }


# ---------------------------------------------------------------------------
# Daily file scanning
# ---------------------------------------------------------------------------

def _collect_daily_fragments(project_id: str, lookback_days: int) -> list[dict[str, Any]]:
    """Extract text fragments from recent daily memory files."""
    ws = get_workspace_root(project_id)
    memory_dir = ws / "memory"
    if not memory_dir.exists():
        return []

    cutoff = date.today() - timedelta(days=lookback_days)
    fragments: list[dict[str, Any]] = []

    for path in sorted(memory_dir.rglob("*.md")):
        if not DATE_STEM_RE.match(path.stem):
            continue
        try:
            file_date = date.fromisoformat(path.stem)
            if file_date < cutoff:
                continue
        except (ValueError, TypeError):
            continue

        persona_id = _persona_from_path(path, memory_dir)
        for block in _extract_summary_blocks(path):
            fragments.append({
                "text": block,
                "persona_id": persona_id,
                "day": path.stem,
                "source_file": str(path.relative_to(ws)),
            })
    return fragments


def _extract_summary_blocks(path: Path) -> list[str]:
    """Extract text blocks following ### Summary headers."""
    try:
        content = path.read_text(encoding="utf-8-sig")
    except OSError:
        return []

    blocks, current, in_summary = [], [], False
    for line in content.splitlines():
        if _SUMMARY_HEADER_RE.match(line.strip()):
            if current:
                blocks.append("\n".join(current).strip())
            current, in_summary = [], True
        elif in_summary and line.strip().startswith("#"):
            if current:
                blocks.append("\n".join(current).strip())
            current, in_summary = [], False
        elif in_summary:
            current.append(line)

    if current:
        blocks.append("\n".join(current).strip())
    return [b for b in blocks if b]


def _persona_from_path(path: Path, memory_dir: Path) -> str:
    rel_parts = path.relative_to(memory_dir).parts
    return rel_parts[0] if len(rel_parts) > 1 else "default"


# ---------------------------------------------------------------------------
# Trace stats
# ---------------------------------------------------------------------------

def _build_trace_stats(traces: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    """Build per-text statistics from recall traces."""
    stats: dict[str, dict[str, Any]] = defaultdict(lambda: {
        "recall_count": 0, "queries": set(), "relevance_scores": [],
        "last_seen": "", "days_seen": set()
    })

    for trace in traces:
        query, ts = trace.get("query", ""), trace.get("ts", "")
        day = ts[:10] if len(ts) >= 10 else ""

        for result in trace.get("results", []):
            text = str(result.get("text", ""))[:200].strip()
            if not text: continue

            entry = stats[text]
            entry["recall_count"] += 1
            if query: entry["queries"].add(query[:100])
            if (score := float(result.get("score", 0.0))) > 0:
                entry["relevance_scores"].append(score)
            entry["last_seen"] = max(entry["last_seen"], ts)
            if day: entry["days_seen"].add(day)

    return {
        text: {
            **s,
            "unique_queries": len(s.pop("queries")),
            "cross_day_count": len(s.pop("days_seen"))
        }
        for text, s in stats.items()
    }


# ---------------------------------------------------------------------------
# Merge + dedup
# ---------------------------------------------------------------------------

def _merge_candidates(
    fragments: list[dict[str, Any]],
    trace_stats: dict[str, dict[str, Any]],
    phase_signals: dict[str, Any],
    lookback_days: int,
) -> list[dict[str, Any]]:
    """Merge daily fragments with recall trace stats into candidates."""
    candidates: list[dict[str, Any]] = []
    seen: set[str] = set()

    def add_candidate(text: str, persona: str, day: str, source: str):
        key = text[:200].strip()
        if not key or key in seen: return
        seen.add(key)

        ts = trace_stats.get(key, {})
        imp = score_importance(text)
        candidates.append({
            "text": text, "persona_id": persona, "day": day, "source_file": source,
            "fingerprint": _fingerprint(text),
            "signals": build_signals(
                recall_count=ts.get("recall_count", 0),
                relevance_scores=ts.get("relevance_scores", []),
                unique_queries=ts.get("unique_queries", 0),
                lookback_days=lookback_days,
                last_seen_iso=ts.get("last_seen", ""),
                cross_day_count=ts.get("cross_day_count", 0),
                importance_score=imp.score,
            )
        })

    for f in fragments:
        add_candidate(f["text"], f["persona_id"], f["day"], f["source_file"])
    for text, ts in trace_stats.items():
        add_candidate(text, "default", "", "")

    return candidates


def _dedup_candidates(candidates: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Remove candidates with duplicate fingerprints."""
    seen: set[str] = set()
    result: list[dict[str, Any]] = []
    for c in candidates:
        fp = c.get("fingerprint")
        if not fp or fp not in seen:
            if fp:
                seen.add(fp)
            result.append(c)
    return result


def _fingerprint(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


# ---------------------------------------------------------------------------
# Phase signals (REM → Light feedback)
# ---------------------------------------------------------------------------

def _read_phase_signals(project_id: str) -> dict[str, Any]:
    path = _dreams_dir(project_id) / "phase-signals.json"
    try:
        return json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}
    except (json.JSONDecodeError, OSError):
        return {}


# ---------------------------------------------------------------------------
# Output
# ---------------------------------------------------------------------------

def _write_candidates(
    project_id: str,
    candidates: list[dict[str, Any]],
) -> None:
    path = _dreams_dir(project_id) / "candidates.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(candidates, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


def _dreams_dir(project_id: str) -> Path:
    return dreams_dir(project_id)
