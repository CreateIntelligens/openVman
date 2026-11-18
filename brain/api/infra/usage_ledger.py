"""Append-only SQLite ledger of model usage events."""

from __future__ import annotations

import atexit
import json
import logging
import math
import os
import sqlite3
import threading
import time
from collections import deque
from collections.abc import Iterator
from contextlib import closing, contextmanager, suppress
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from core.usage import LLMUsage, UsageScope, current_usage_scope
from infra.file_lock import file_lock
from infra.project_context import get_data_root

logger = logging.getLogger("brain.usage")

_INIT_LOCK = threading.Lock()
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
    # 排隊中的事件已綁定舊路徑；先寫完並關掉常駐連線，才不會殘留到下一個路徑。
    flush_usage_events(timeout=_SHUTDOWN_FLUSH_TIMEOUT_S)
    _WRITER.close_connection()
    _DB_PATH_OVERRIDE = path
    with _INIT_LOCK:
        _INITIALIZED.clear()


def _connect(
    path: Path | None = None,
    *,
    busy_timeout_ms: int = 5000,
    autocommit: bool = False,
) -> sqlite3.Connection:
    path = path if path is not None else get_usage_db_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(
        path,
        check_same_thread=False,
        isolation_level=None if autocommit else "",
    )
    conn.execute(f"PRAGMA busy_timeout={int(busy_timeout_ms)}")
    conn.execute("PRAGMA synchronous=NORMAL")
    conn.row_factory = sqlite3.Row
    key = str(path)
    if key not in _INITIALIZED:
        with _INIT_LOCK, file_lock(path):
            conn.execute("PRAGMA journal_mode=WAL")
            conn.executescript(_SCHEMA)
            _add_missing_columns(conn)
            conn.execute(_PRINCIPAL_INDEX)
            if not autocommit:
                conn.commit()
            _INITIALIZED.add(key)
    return conn


@contextmanager
def _read_connection() -> Iterator[sqlite3.Connection]:
    """讀取前先把本 process 排隊中的事件寫完，同一 process 先寫後讀才一致。

    讀取用自己的短連線、不碰寫入執行緒；等不到（別的 process 長時間鎖住）
    就照讀，寧可少算剛發生的幾筆也不要卡住查詢。
    """
    flush_usage_events(timeout=_READ_FLUSH_TIMEOUT_S)
    with closing(_connect()) as conn:
        yield conn


# ---------------------------------------------------------------------------
# 背景寫入
#
# 回覆路徑上每次決策、每次 LLM 呼叫都會記一筆用量。十幾個 worker process
# 共用同一個 usage.db，同步寫入時每筆都要搶 SQLite 寫鎖，一秒湧進上百題時
# 每筆最多等 busy_timeout，決策被拖到十秒，等不到的紀錄還直接丟掉。
# 改成每個 process 一條背景執行緒、一條常駐連線，批次寫入；呼叫端只排隊。
# ---------------------------------------------------------------------------

#: 累積到這麼多筆就立刻寫，不等滿一個間隔。
_BATCH_SIZE = 100
#: 單一交易最多寫幾筆。
_MAX_BATCH = 500
#: 第一筆排隊後最多等多久就寫。
_FLUSH_INTERVAL_S = 0.5
#: 佇列上限。SQLite 長時間鎖住時，超過的事件直接丟棄並記一次 log。
_QUEUE_CAP = 10_000
#: 寫入連線每次嘗試的 busy 等待；等不到就退避重試，不會卡住呼叫端。
_WRITER_BUSY_TIMEOUT_MS = 1000
_RETRY_BACKOFF_INITIAL_S = 0.05
_RETRY_BACKOFF_MAX_S = 2.0
#: 非鎖定類錯誤（磁碟、權限、schema）重試幾次後放棄該批。
_MAX_NON_BUSY_ATTEMPTS = 3
#: 常駐連線不會在關閉時順手 checkpoint，所以定期做 PASSIVE checkpoint，
#: 並限制 WAL 檔在 checkpoint 後縮回的大小。
_CHECKPOINT_INTERVAL_S = 30.0
_JOURNAL_SIZE_LIMIT_BYTES = 4 * 1024 * 1024
_READ_FLUSH_TIMEOUT_S = 2.0
_SHUTDOWN_FLUSH_TIMEOUT_S = 5.0


def _is_busy_error(exc: BaseException) -> bool:
    if not isinstance(exc, sqlite3.OperationalError):
        return False
    code = getattr(exc, "sqlite_errorcode", None)
    if code is not None and code & 0xFF in (sqlite3.SQLITE_BUSY, sqlite3.SQLITE_LOCKED):
        return True
    message = str(exc).lower()
    return "locked" in message or "busy" in message


def _is_row_error(exc: BaseException) -> bool:
    """這一批裡某筆資料本身寫不進去（約束、型別、整數超出範圍），重試也一樣。"""
    return isinstance(
        exc,
        (
            sqlite3.IntegrityError,
            sqlite3.InterfaceError,
            sqlite3.ProgrammingError,
            OverflowError,
            TypeError,
            ValueError,
        ),
    )


class _DeadlinePassed(Exception):
    """停機期限到了還拿不到寫鎖。"""


@dataclass
class _Pending:
    seq: int
    path: Path
    event: dict[str, Any]


@dataclass
class _UsageWriter:
    cond: threading.Condition = field(default_factory=threading.Condition)
    #: 退避等待用 Event 而不是 time.sleep：flush／停機要能把它叫醒。
    wake: threading.Event = field(default_factory=threading.Event)
    queue: deque[_Pending] = field(default_factory=deque)
    enqueued: int = 0
    done: int = 0
    #: 處理完但沒寫進去的事件序號；flush 只看自己等的那段範圍。
    lost: deque[int] = field(default_factory=lambda: deque(maxlen=_QUEUE_CAP))
    flush_requested: bool = False
    stopping: bool = False
    #: 停機期限：等寫鎖、最後一次重試與寫入執行緒結束都以它為準。
    deadline: float | None = None
    overflowing: bool = False
    dropped: int = 0
    thread: threading.Thread | None = None
    conn: sqlite3.Connection | None = None
    conn_path: Path | None = None
    last_checkpoint: float = 0.0

    def enqueue(self, path: Path, event: dict[str, Any]) -> bool:
        with self.cond:
            if len(self.queue) >= _QUEUE_CAP:
                self.dropped += 1
                if not self.overflowing:
                    self.overflowing = True
                    logger.warning(
                        "usage ledger queue full (%d events); dropping new events"
                        " until the writer catches up",
                        _QUEUE_CAP,
                    )
                return False
            self.enqueued += 1
            # 存一份快照：呼叫端拿到的 dict 之後被改，不能改到帳本。
            self.queue.append(_Pending(self.enqueued, path, dict(event)))
            # 第一筆叫醒閒置中的寫入執行緒開始計時；滿一批則立刻寫。
            if len(self.queue) == 1 or len(self.queue) >= _BATCH_SIZE:
                self.cond.notify_all()
            started = self._ensure_thread()
        if not started:
            # 直譯器關閉中不能再開執行緒；這時已沒有回覆在等，直接同步寫掉。
            self._drain_inline(time.monotonic() + _SHUTDOWN_FLUSH_TIMEOUT_S)
        return True

    def _ensure_thread(self) -> bool:
        if self.thread is not None and self.thread.is_alive():
            return True
        self.stopping = False
        self.deadline = None
        thread = threading.Thread(
            target=self._run, name="usage-ledger-writer", daemon=True,
        )
        try:
            thread.start()
        except RuntimeError:
            return False
        self.thread = thread
        return True

    def _committed(self, baseline: int, target: int) -> bool:
        """呼叫端等的那段（baseline, target] 都處理完、而且一筆都沒丟。"""
        return self.done >= target and not any(
            baseline < seq <= target for seq in self.lost
        )

    def flush(self, timeout: float) -> bool:
        """等到呼叫前排進來的事件都寫完為止。

        逾時，或其中有事件寫不進去（被丟掉）時回 False。
        """
        deadline = time.monotonic() + max(0.0, timeout)
        with self.cond:
            target = self.enqueued
            baseline = self.done
            if self.done >= target:
                return self._committed(baseline, target)
            if self._ensure_thread():
                self.flush_requested = True
                self.cond.notify_all()
                # 寫入執行緒可能正在退避；叫醒它立刻重試。
                self.wake.set()
                while self.done < target:
                    remaining = deadline - time.monotonic()
                    if remaining <= 0:
                        return False
                    self.cond.wait(remaining)
                return self._committed(baseline, target)
        self._drain_inline(deadline)
        with self.cond:
            return self._committed(baseline, target)

    def shutdown(self, timeout: float) -> bool:
        """寫完排隊中的事件並停下寫入執行緒，全部寫進去才回 True。

        等寫鎖、最後一次重試與執行緒結束共用同一個期限。
        """
        deadline = time.monotonic() + max(0.0, timeout)
        with self.cond:
            target = self.enqueued
            baseline = self.done
            self.stopping = True
            self.deadline = deadline
            self.cond.notify_all()
            thread = self.thread
        self.wake.set()
        if thread is None or not thread.is_alive():
            self._drain_inline(deadline)
        else:
            # 最後一次嘗試的等鎖時間也以期限為上限，給它一點時間收尾。
            thread.join(timeout=max(0.0, deadline - time.monotonic()) + 0.2)
        with self.cond:
            committed = self._committed(baseline, target)
            unwritten = self.enqueued - self.done
        if not committed:
            logger.error(
                "usage ledger exiting with unwritten events (%d still queued)",
                unwritten,
            )
        if thread is None or not thread.is_alive():
            self.close_connection()
        return committed

    def close_connection(self) -> None:
        with self.cond:
            conn, self.conn, self.conn_path = self.conn, None, None
        if conn is not None:
            try:
                conn.close()
            except sqlite3.Error:  # pragma: no cover - best effort
                pass

    def _take_batch(self) -> list[_Pending] | None:
        with self.cond:
            while not self.queue and not self.stopping:
                self.cond.wait()
            if not self.queue:
                return None
            deadline = time.monotonic() + _FLUSH_INTERVAL_S
            while (
                len(self.queue) < _BATCH_SIZE
                and not self.flush_requested
                and not self.stopping
            ):
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    break
                self.cond.wait(remaining)
            count = min(len(self.queue), _MAX_BATCH)
            batch = [self.queue.popleft() for _ in range(count)]
            if not self.queue:
                self.flush_requested = False
            return batch

    def _mark_done(self, batch: list[_Pending], lost: list[int]) -> None:
        with self.cond:
            self.done = max(self.done, batch[-1].seq)
            self.lost.extend(lost)
            if self.overflowing and len(self.queue) < _QUEUE_CAP // 2:
                logger.warning(
                    "usage ledger queue drained; %d events were dropped while full",
                    self.dropped,
                )
                self.overflowing = False
                self.dropped = 0
            self.cond.notify_all()

    def _run(self) -> None:
        while True:
            try:
                batch = self._take_batch()
                if batch is None:
                    return
                lost = self._write_batch(batch)
                self._mark_done(batch, lost)
            except Exception:  # pragma: no cover - the writer must never die
                logger.exception("usage ledger writer loop error")
                self.wake.wait(_RETRY_BACKOFF_MAX_S)
                self.wake.clear()

    def _drain_inline(self, deadline: float) -> None:
        while True:
            with self.cond:
                if not self.queue:
                    return
                batch = [self.queue.popleft() for _ in range(len(self.queue))]
            lost = self._write_batch(batch, deadline=deadline)
            self._mark_done(batch, lost)

    def _write_batch(
        self, batch: list[_Pending], *, deadline: float | None = None,
    ) -> list[int]:
        """Write the batch; return the sequence numbers that were dropped."""
        groups: dict[Path, list[_Pending]] = {}
        for item in batch:
            groups.setdefault(item.path, []).append(item)
        lost: list[int] = []
        for path, items in groups.items():
            lost.extend(self._write_group(path, items, deadline=deadline))
        return lost

    def _connection(self, path: Path) -> sqlite3.Connection:
        with self.cond:
            if self.conn is not None and self.conn_path == path:
                return self.conn
        self.close_connection()
        conn = _connect(
            path, busy_timeout_ms=_WRITER_BUSY_TIMEOUT_MS, autocommit=True,
        )
        conn.execute("PRAGMA wal_autocheckpoint=1000")
        conn.execute(f"PRAGMA journal_size_limit={_JOURNAL_SIZE_LIMIT_BYTES}")
        with self.cond:
            self.conn, self.conn_path = conn, path
        self.last_checkpoint = time.monotonic()
        return conn

    def _write_group(
        self, path: Path, items: list[_Pending], *, deadline: float | None,
    ) -> list[int]:
        try:
            error = self._insert(
                path, [item.event for item in items],
                attempts=_MAX_NON_BUSY_ATTEMPTS, deadline=deadline,
            )
        except _DeadlinePassed:
            logger.error(
                "usage ledger dropped %d events at shutdown: database stayed locked",
                len(items),
            )
            return [item.seq for item in items]
        if error is None:
            return []
        # 整批失敗不代表每筆都壞：逐筆再寫一次，有效的照樣進帳本，只丟寫不進去的。
        lost: list[int] = []
        for index, item in enumerate(items):
            try:
                if self._insert(path, [item.event], attempts=1, deadline=deadline):
                    lost.append(item.seq)
            except _DeadlinePassed:
                lost.extend(pending.seq for pending in items[index:])
                break
        logger.warning(
            "usage ledger write failed, dropped %d of %d events: %s",
            len(lost), len(items), error,
        )
        return lost

    def _insert(
        self,
        path: Path,
        events: list[dict[str, Any]],
        *,
        attempts: int,
        deadline: float | None,
    ) -> Exception | None:
        """Insert *events* in one transaction; return the error that made it give up.

        鎖住只是暫時的，退避後重試、不算次數；停機時改等到期限為止。
        """
        columns = list(events[0])
        sql = (
            f"INSERT INTO usage_events ({', '.join(columns)}) "
            f"VALUES ({', '.join(':' + name for name in columns)})"
        )
        backoff = _RETRY_BACKOFF_INITIAL_S
        failures = 0
        while True:
            limit = deadline if deadline is not None else self.deadline
            busy_ms = _WRITER_BUSY_TIMEOUT_MS
            if limit is not None:
                remaining = limit - time.monotonic()
                if remaining <= 0:
                    raise _DeadlinePassed
                # 停機時交給 SQLite 自己等鎖：鎖一放開就拿到，不必等下一輪退避。
                busy_ms = max(1, int(remaining * 1000))
            try:
                conn = self._connection(path)
                conn.execute(f"PRAGMA busy_timeout={busy_ms}")
                conn.execute("BEGIN IMMEDIATE")
                try:
                    conn.executemany(sql, events)
                    conn.execute("COMMIT")
                except BaseException:
                    with suppress(sqlite3.Error):
                        conn.execute("ROLLBACK")
                    raise
                self._maybe_checkpoint(conn)
                return None
            except Exception as exc:
                if _is_busy_error(exc):
                    logger.debug("usage ledger busy, retrying %d events", len(events))
                else:
                    failures += 1
                    if _is_row_error(exc):
                        return exc
                    self.close_connection()
                    if failures >= attempts:
                        return exc
            wait = backoff
            limit = deadline if deadline is not None else self.deadline
            if limit is not None:
                wait = min(wait, max(0.0, limit - time.monotonic()))
            self.wake.wait(wait)
            self.wake.clear()
            backoff = min(backoff * 2, _RETRY_BACKOFF_MAX_S)

    def _maybe_checkpoint(self, conn: sqlite3.Connection) -> None:
        now = time.monotonic()
        if now - self.last_checkpoint < _CHECKPOINT_INTERVAL_S:
            return
        self.last_checkpoint = now
        try:
            conn.execute("PRAGMA wal_checkpoint(PASSIVE)")
        except sqlite3.Error as exc:
            logger.debug("usage ledger checkpoint skipped: %s", exc)


_WRITER = _UsageWriter()
_FORK_ORPHANS: list[_UsageWriter] = []


def _reset_after_fork() -> None:
    """fork 出來的子 process 沒有寫入執行緒，繼承來的連線也不能沿用。

    舊物件留著不關：在子 process 關掉父 process 開的 SQLite 連線並不安全。
    """
    global _INIT_LOCK, _WRITER
    _FORK_ORPHANS.append(_WRITER)
    _WRITER = _UsageWriter()
    # fork 當下若別的執行緒正在建表，繼承來的鎖會永遠是鎖住的。
    _INIT_LOCK = threading.Lock()


if hasattr(os, "register_at_fork"):
    os.register_at_fork(after_in_child=_reset_after_fork)


def flush_usage_events(timeout: float = _SHUTDOWN_FLUSH_TIMEOUT_S) -> bool:
    """Block until this process's queued usage events are committed.

    Returns False when *timeout* elapses first (e.g. the database stayed locked)
    or when any of those events could not be stored and was dropped.
    """
    return _WRITER.flush(timeout)


def shutdown_usage_writer(timeout: float = _SHUTDOWN_FLUSH_TIMEOUT_S) -> bool:
    """Write pending events and stop the writer thread within one deadline.

    Returns True only when every event queued before the call was committed.
    """
    return _WRITER.shutdown(timeout)


atexit.register(shutdown_usage_writer)


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds")


_SQLITE_INT_MIN = -(2**63)
_SQLITE_INT_MAX = 2**63 - 1


def storable_int(value: Any) -> bool:
    """SQLite INTEGER 存得下（64 位元有號整數）。"""
    return (
        isinstance(value, int)
        and not isinstance(value, bool)
        and _SQLITE_INT_MIN <= value <= _SQLITE_INT_MAX
    )


def storable_float(value: Any) -> bool:
    """有限的數字。NaN 綁進 SQLite 會變成 NULL，撞上 NOT NULL 讓整批交易失敗。"""
    try:
        return math.isfinite(float(value))
    except (TypeError, ValueError, OverflowError):
        return False


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
    """Queue one usage event for the ledger and mirror it into the active scope.

    Never raises and never waits on SQLite: a background writer commits the
    event. Returns None only when the event could not be queued (queue full).
    """
    scope = scope if scope is not None else current_usage_scope()
    counts = (usage or LLMUsage()).as_dict()
    if not (
        all(storable_int(value) for value in counts.values())
        and storable_float(units)
        and storable_float(latency_ms)
    ):
        # 入列前就擋掉：寫入時才失敗會連同同一批的其他事件一起回滾。
        logger.warning(
            "usage ledger rejected an event with unstorable numbers provider=%s model=%s",
            provider,
            model,
        )
        return None
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
        queued = _WRITER.enqueue(get_usage_db_path(), event)
    except Exception as exc:
        logger.warning(
            "usage ledger enqueue failed provider=%s model=%s: %s",
            provider,
            model,
            exc,
        )
        return None
    if not queued:
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
    project_ids: list[str] | None = None,
) -> tuple[str, dict[str, Any]]:
    clauses: list[str] = []
    params: dict[str, Any] = {}
    if project_ids is not None:
        # Backend 替受限管理員帶他範圍內的專案；清單是空的就是一個都不能看，
        # 不能當成沒篩選而回全部。
        allowed = [value for value in project_ids if value]
        if not allowed:
            clauses.append("1 = 0")
        else:
            names = [f"project_ids_{index}" for index in range(len(allowed))]
            clauses.append(f"project_id IN ({', '.join(':' + name for name in names)})")
            params.update(zip(names, allowed))
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


def summarize_usage(*, group_by: str = "model", **filters: Any) -> dict[str, Any]:
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
    with _read_connection() as conn:
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
    **filters: Any,
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

    with _read_connection() as conn:
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


def list_usage_events(*, limit: int = 100, **filters: Any) -> list[dict[str, Any]]:
    where, params = _build_filters(**filters)
    params["limit"] = max(1, min(int(limit), 1000))
    with _read_connection() as conn:
        rows = conn.execute(
            # 多個 worker 各自批次寫入，id 是提交順序而不是發生順序。
            f"SELECT * FROM usage_events{where}"
            " ORDER BY created_at DESC, id DESC LIMIT :limit",
            params,
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


def count_usage_events_since(*, provider: str, kind: str, since: str) -> int:
    """Count events for one provider/kind; failures count as 0 so callers fail open."""
    try:
        with _read_connection() as conn:
            row = conn.execute(
                "SELECT COUNT(*) FROM usage_events"
                " WHERE provider = ? AND kind = ? AND created_at >= ?",
                (provider, kind, since),
            ).fetchone()
    except Exception as exc:
        logger.warning("usage ledger count failed provider=%s: %s", provider, exc)
        return 0
    return int(row[0])
