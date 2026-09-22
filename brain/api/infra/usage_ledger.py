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

#: 非 token 單位各自加總成獨立欄位。把 chars 和 seconds 加在一起沒有意義，
#: 所以不做一個籠統的 SUM(units)，而是每種單位一欄。
_UNIT_SUMS = (
    ("chars", "chars"),
    ("seconds", "seconds"),
)
_UNIT_SUM_SQL = ", ".join(
    f"COALESCE(SUM(CASE WHEN unit_type = '{unit}' THEN units END), 0) AS {alias}"
    for unit, alias in _UNIT_SUMS
)
_UNIT_SUM_KEYS = tuple(alias for _, alias in _UNIT_SUMS)

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
    unit_type TEXT NOT NULL DEFAULT 'tokens',
    units REAL NOT NULL DEFAULT 0,
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
    # LLM 以外的用量不是 token 計價：TTS 按字元、Live 按音訊秒數。混進
    # input/output_tokens 會讓 total_tokens 變成把不同單位相加的無意義數字，
    # 所以另外用 (unit_type, units) 承接，查詢時依 unit_type 分開加總。
    ("unit_type", "TEXT NOT NULL DEFAULT 'tokens'"),
    ("units", "REAL NOT NULL DEFAULT 0"),
)

#: 計量單位。tokens 沿用既有的 *_tokens 欄位，其餘記在 units。
UNIT_TOKENS = "tokens"
UNIT_CHARS = "chars"
UNIT_SECONDS = "seconds"


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
    unit_type: str = UNIT_TOKENS,
    units: float = 0.0,
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
        "unit_type": unit_type or UNIT_TOKENS,
        "units": round(float(units), 3),
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
        + [_UNIT_SUM_SQL]
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
    for key in _UNIT_SUM_KEYS:
        totals[key] = round(float(totals.get(key) or 0), 3)
    return {"group_by": group_by, "filters": params, "totals": totals, "groups": groups}


_BUCKET_WIDTHS = {"hour": 13, "day": 10, "month": 7}
_REPORT_TIMEZONE_OFFSETS = {"UTC": "+0 hours", "Asia/Taipei": "+8 hours"}


def timeseries_usage(
    *,
    group_by: str = "",
    bucket: str = "day",
    limit: int = 8,
    report_timezone: str = "UTC",
    **filters: str,
) -> dict[str, Any]:
    """Aggregate tokens per time bucket, optionally split by one dimension.

    *limit* 只留用量最高的前 N 個分組，其餘併成 "__other__"——分組是使用者
    資料（帳號、專案可以有上百個），全部畫出來的圖沒有人看得懂。
    """
    width = _BUCKET_WIDTHS.get(bucket)
    if width is None:
        raise ValueError(f"unknown bucket: {bucket}")
    if report_timezone not in _REPORT_TIMEZONE_OFFSETS:
        raise ValueError(f"unknown report_timezone: {report_timezone}")

    columns = _GROUP_COLUMNS.get(group_by) if group_by else None
    if group_by and columns is None:
        raise ValueError(f"unknown group_by: {group_by}")

    where, params = _build_filters(**filters)
    sums = ", ".join(
        ["COUNT(*) AS calls"]
        + [f"SUM({column}) AS {column}" for column in _TOKEN_COLUMNS]
    )
    # UTC 帳本先截到秒，避免 SQLite 將 .999999 四捨五入到下個小時／日。
    # 時區只影響分桶；WHERE 仍直接比較 UTC 邊界，保留索引查詢。
    period = (
        "substr(strftime('%Y-%m-%dT%H:%M:%S', "
        "substr(created_at, 1, 19), :report_offset), "
        f"1, {width}) AS period"
    )
    params["report_offset"] = _REPORT_TIMEZONE_OFFSETS[report_timezone]

    with _LOCK, _connect() as conn:
        if columns is None:
            rows = [
                dict(row)
                for row in conn.execute(
                    f"SELECT {period}, {sums} FROM usage_events{where} "
                    "GROUP BY period ORDER BY period",
                    params,
                )
            ]
            return {
                "bucket": bucket,
                "report_timezone": report_timezone,
                "group_by": "",
                "series": [],
                "periods": [row["period"] for row in rows],
                "points": rows,
            }

        select_cols = ", ".join(columns)
        top = [
            tuple(row[column] or "" for column in columns)
            for row in conn.execute(
                f"SELECT {select_cols}, SUM(total_tokens) AS total_tokens "
                f"FROM usage_events{where} GROUP BY {select_cols} "
                "ORDER BY total_tokens DESC LIMIT :top_limit",
                {**params, "top_limit": max(1, min(int(limit), 50))},
            )
        ]
        rows = [
            dict(row)
            for row in conn.execute(
                f"SELECT {period}, {select_cols}, {sums} FROM usage_events{where} "
                f"GROUP BY period, {select_cols} ORDER BY period",
                params,
            )
        ]

    top_keys = set(top)
    periods = sorted({row["period"] for row in rows})
    points: dict[tuple[str, ...], dict[str, dict[str, Any]]] = {}
    for row in rows:
        key = tuple(row[column] or "" for column in columns)
        if key not in top_keys:
            key = ("__other__",) * len(columns)
        bucketed = points.setdefault(key, {})
        period_key = row["period"]
        if period_key not in bucketed:
            bucketed[period_key] = {
                "period": period_key,
                "calls": 0,
                **dict.fromkeys(_TOKEN_COLUMNS, 0),
            }
        current = bucketed[period_key]
        current["calls"] += int(row["calls"] or 0)
        for column in _TOKEN_COLUMNS:
            current[column] += int(row[column] or 0)

    series = [
        {
            **dict(zip(columns, key)),
            "points": [values[period] for period in periods if period in values],
        }
        for key, values in points.items()
    ]
    # __other__ 是併桶，總和常大於任何單一分組；讓它參與名次會排到最前面，
    # 圖例第一個變成「其他」。固定壓到最後。
    def _rank(item: dict[str, Any]) -> tuple[int, int]:
        is_other = item.get(columns[0]) == "__other__"
        total = sum(p["total_tokens"] for p in item["points"])
        return (1 if is_other else 0, -total)

    series.sort(key=_rank)
    return {
        "bucket": bucket,
        "report_timezone": report_timezone,
        "group_by": group_by,
        "periods": periods,
        "series": series,
        "points": [],
    }


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
