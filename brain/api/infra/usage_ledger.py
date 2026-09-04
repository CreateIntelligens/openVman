"""Append-only SQLite ledger of model usage events."""

from __future__ import annotations

from datetime import datetime, timezone
import json
import logging
from pathlib import Path
import sqlite3
from threading import Lock
from typing import Any

from core.usage import LLMUsage, UsageScope, current_usage_scope
from infra.project_context import get_data_root

logger = logging.getLogger("brain.usage")

_LOCK = Lock()
_INITIALIZED: set[str] = set()
_DB_PATH_OVERRIDE: Path | None = None

_GROUP_COLUMNS = {
    "model": ("provider", "model"),
    "user": ("user_id",),
    "project": ("project_id",),
    "kind": ("kind",),
    "session": ("session_id",),
    "principal": ("principal_type", "principal_id"),
}
_TOKEN_COLUMNS = (
    "input_tokens",
    "output_tokens",
    "total_tokens",
    "cached_tokens",
    "reasoning_tokens",
)

_SCHEMA = """
CREATE TABLE IF NOT EXISTS usage_events (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    created_at TEXT NOT NULL,
    kind TEXT NOT NULL DEFAULT 'chat',
    user_id TEXT NOT NULL DEFAULT '',
    role TEXT NOT NULL DEFAULT '',
    principal_type TEXT NOT NULL DEFAULT '',
    principal_id TEXT NOT NULL DEFAULT '',
    project_id TEXT NOT NULL DEFAULT 'default',
    session_id TEXT NOT NULL DEFAULT '',
    persona_id TEXT NOT NULL DEFAULT 'default',
    trace_id TEXT NOT NULL DEFAULT '',
    channel TEXT NOT NULL DEFAULT '',
    provider TEXT NOT NULL DEFAULT '',
    model TEXT NOT NULL DEFAULT '',
    input_tokens INTEGER NOT NULL DEFAULT 0,
    output_tokens INTEGER NOT NULL DEFAULT 0,
    total_tokens INTEGER NOT NULL DEFAULT 0,
    cached_tokens INTEGER NOT NULL DEFAULT 0,
    reasoning_tokens INTEGER NOT NULL DEFAULT 0,
    latency_ms REAL NOT NULL DEFAULT 0,
    raw TEXT
);
CREATE INDEX IF NOT EXISTS idx_usage_user_created ON usage_events(user_id, created_at);
CREATE INDEX IF NOT EXISTS idx_usage_project_created ON usage_events(project_id, created_at);
CREATE INDEX IF NOT EXISTS idx_usage_trace ON usage_events(trace_id);
"""

_PRINCIPAL_INDEX = """
CREATE INDEX IF NOT EXISTS idx_usage_principal
ON usage_events(principal_type, principal_id, created_at)
"""

# 既有帳本用 CREATE TABLE IF NOT EXISTS 建過了，新欄位只能靠 ALTER 補。
_ADDED_COLUMNS = (
    ("principal_type", "TEXT NOT NULL DEFAULT ''"),
    ("principal_id", "TEXT NOT NULL DEFAULT ''"),
)


def _add_missing_columns(conn: sqlite3.Connection) -> None:
    existing = {
        str(row["name"])
        for row in conn.execute("PRAGMA table_info(usage_events)").fetchall()
    }
    for column, definition in _ADDED_COLUMNS:
        if column not in existing:
            conn.execute(
                f"ALTER TABLE usage_events ADD COLUMN {column} {definition}"
            )


def get_usage_db_path() -> Path:
    if _DB_PATH_OVERRIDE is not None:
        return _DB_PATH_OVERRIDE
    return get_data_root().parent / "usage.db"


def set_usage_db_path(path: Path | None) -> None:
    """Override the ledger location (tests only)."""
    global _DB_PATH_OVERRIDE
    _DB_PATH_OVERRIDE = path
    _INITIALIZED.clear()


def _connect() -> sqlite3.Connection:
    path = get_usage_db_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(path, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    key = str(path)
    if key not in _INITIALIZED:
        conn.executescript(_SCHEMA)
        _add_missing_columns(conn)
        conn.execute(_PRINCIPAL_INDEX)
        _INITIALIZED.add(key)
    return conn


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds")


def record_usage_event(
    *,
    provider: str,
    model: str,
    usage: LLMUsage | None,
    latency_ms: float = 0.0,
    kind: str | None = None,
    scope: UsageScope | None = None,
    raw: dict[str, Any] | None = None,
) -> dict[str, Any] | None:
    """Persist one usage event and mirror it into the active scope.

    Never raises: a ledger failure must not fail the user's request.
    """
    scope = scope if scope is not None else current_usage_scope()
    counts = (usage or LLMUsage()).as_dict()
    event: dict[str, Any] = {
        "created_at": _now_iso(),
        "kind": kind or (scope.kind if scope else "background"),
        "user_id": scope.user_id if scope else "",
        "role": scope.role if scope else "",
        "principal_type": scope.principal_type if scope else "",
        "principal_id": scope.principal_id if scope else "",
        "project_id": scope.project_id if scope else "default",
        "session_id": scope.session_id if scope else "",
        "persona_id": scope.persona_id if scope else "default",
        "trace_id": scope.trace_id if scope else "",
        "channel": scope.channel if scope else "",
        "provider": provider,
        "model": model,
        **counts,
        "latency_ms": round(float(latency_ms), 2),
        "raw": json.dumps(raw, ensure_ascii=False) if raw else None,
    }
    try:
        with _LOCK, _connect() as conn:
            columns = ", ".join(event)
            placeholders = ", ".join(f":{name}" for name in event)
            conn.execute(
                f"INSERT INTO usage_events ({columns}) VALUES ({placeholders})", event,
            )
    except Exception as exc:
        logger.warning(
            "usage ledger write failed provider=%s model=%s: %s",
            provider,
            model,
            exc,
        )
        return None
    if scope is not None:
        scope.collected.append({**event, **_timeline_offsets(scope, latency_ms)})
    return event


def _timeline_offsets(scope: UsageScope, latency_ms: float) -> dict[str, float]:
    """位移只放進 scope 鏡像，不進 DB：帳本存的是計費事實，位移只服務
    單次回應的「時間花在哪」視覺化。

    起點由「結束時間往回推延遲」得出。延遲若比 scope 已經歷的時間還長
    （呼叫早於 scope 建立，或兩邊用不同時鐘量測），把起點釘在 0 並讓長度
    跟著縮短——寧可讓長條短一點，也不要讓它從負的時間開始。
    """
    ended_ms = max(0.0, scope.elapsed_ms())
    started_ms = max(0.0, ended_ms - max(0.0, float(latency_ms)))
    return {
        "started_at_ms": round(started_ms, 2),
        "ended_at_ms": round(ended_ms, 2),
    }


def _build_filters(
    *,
    user_id: str = "",
    principal_type: str = "",
    principal_id: str = "",
    project_id: str = "",
    session_id: str = "",
    trace_id: str = "",
    kind: str = "",
    since: str = "",
    until: str = "",
) -> tuple[str, dict[str, Any]]:
    clauses: list[str] = []
    params: dict[str, Any] = {}
    for column, value in (
        ("user_id", user_id),
        ("principal_type", principal_type),
        ("principal_id", principal_id),
        ("project_id", project_id),
        ("session_id", session_id),
        ("trace_id", trace_id),
        ("kind", kind),
    ):
        if value:
            clauses.append(f"{column} = :{column}")
            params[column] = value
    if since:
        clauses.append("created_at >= :since")
        params["since"] = since
    if until:
        clauses.append("created_at < :until")
        params["until"] = until
    where = f" WHERE {' AND '.join(clauses)}" if clauses else ""
    return where, params


def summarize_usage(*, group_by: str = "model", **filters: str) -> dict[str, Any]:
    """Aggregate tokens over the filtered events, grouped by one dimension."""
    columns = _GROUP_COLUMNS.get(group_by)
    if columns is None:
        raise ValueError(f"unknown group_by: {group_by}")
    where, params = _build_filters(**filters)
    select_cols = ", ".join(columns)
    sums = ", ".join(
        ["COUNT(*) AS calls"]
        + [f"SUM({column}) AS {column}" for column in _TOKEN_COLUMNS]
    )
    with _LOCK, _connect() as conn:
        groups = [
            dict(row)
            for row in conn.execute(
                f"SELECT {select_cols}, {sums} FROM usage_events{where} "
                f"GROUP BY {select_cols} ORDER BY total_tokens DESC",
                params,
            )
        ]
        totals = dict(
            conn.execute(
                f"SELECT {sums} FROM usage_events{where}",
                params,
            ).fetchone()
        )
    for key in _TOKEN_COLUMNS:
        totals[key] = int(totals.get(key) or 0)
    return {"group_by": group_by, "filters": params, "totals": totals, "groups": groups}


def list_usage_events(*, limit: int = 100, **filters: str) -> list[dict[str, Any]]:
    where, params = _build_filters(**filters)
    params["limit"] = max(1, min(int(limit), 1000))
    with _LOCK, _connect() as conn:
        rows = conn.execute(
            f"SELECT * FROM usage_events{where} ORDER BY id DESC LIMIT :limit", params,
        ).fetchall()
    events: list[dict[str, Any]] = []
    for row in rows:
        event = dict(row)
        if event.get("raw"):
            try:
                event["raw"] = json.loads(event["raw"])
            except ValueError:
                pass
        events.append(event)
    return events
