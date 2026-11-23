"""The embed daily quota counts atomically, across threads and processes."""

from __future__ import annotations

import sqlite3
import threading
from datetime import datetime, timezone
from zoneinfo import ZoneInfo

import pytest
from fastapi import HTTPException

from app.auth import embed
from app.auth.embed import (
    EmbedBookkeeper,
    LocalDailyCounter,
    RedisDailyCounter,
    authorize_embed_request,
)
from app.auth.models import EmbedKeyRecord

TAIPEI = ZoneInfo("Asia/Taipei")
ORIGIN = "https://ok.example"


def _key(quota: int = 5) -> EmbedKeyRecord:
    return EmbedKeyRecord(
        key_id="ovk_test", label="", project_id="p", allowed_origins=(ORIGIN,),
        default_character_id="", allowed_character_ids=(), default_persona_id="",
        default_tts_provider="", default_tts_voice="", rate_limit_per_minute=1000,
        daily_request_quota=quota, disabled=False, created_by=None, created_at="",
        updated_at="", last_used_at=None,
    )


class _Repository:
    def __init__(self, used: int = 0) -> None:
        self.used = used
        self.seed_reads = 0
        self.written: list[tuple[str, str | None]] = []
        self._lock = threading.Lock()

    def requests_today(self, key_id, day=None):
        with self._lock:
            self.seed_reads += 1
        return self.used

    def record_use(self, key_id, day=None):
        with self._lock:
            self.written.append((key_id, day))
            self.used += 1
        return self.used


class _NoLimit:
    def check(self, key, limit):
        return 0


class _FakeRedis:
    """Runs the two daily scripts with a lock so each eval is atomic like Lua."""

    def __init__(self) -> None:
        self.values: dict[str, int] = {}
        self.ttl: dict[str, int] = {}
        self.evals = 0
        self._lock = threading.Lock()

    def eval(self, script, _numkeys, key, *args):
        with self._lock:
            self.evals += 1
            if script == embed._REDIS_DAILY_INCR_SCRIPT:
                if key not in self.values:
                    return None
            elif script == embed._REDIS_DAILY_SEED_SCRIPT:
                if key not in self.values:
                    self.values[key] = int(args[0])
                    self.ttl[key] = int(args[1])
            else:
                raise AssertionError("unexpected script")
            self.values[key] += 1
            return self.values[key]

    def scan_iter(self, match=None):
        return list(self.values)

    def delete(self, key):
        self.values.pop(key, None)


class _BrokenRedis:
    def eval(self, *args, **kwargs):
        raise ConnectionError("redis down")


def _attempt(counter, repository, keeper, now=None) -> int:
    try:
        authorize_embed_request(
            _key(), method="POST", path="/api/v1/chat", origin=ORIGIN,
            repository=repository, limiter=_NoLimit(), bookkeeper=keeper,
            daily_counter=counter, now=now,
        )
    except HTTPException as exc:
        return exc.status_code
    return 200


def _race(counters, repository, attempts=20) -> list[int]:
    keeper = EmbedBookkeeper()
    barrier = threading.Barrier(attempts)
    results: list[int] = []

    def worker(index):
        barrier.wait()
        results.append(_attempt(counters[index % len(counters)], repository, keeper))

    threads = [threading.Thread(target=worker, args=(i,)) for i in range(attempts)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()
    assert keeper.drain(timeout=10)
    return results


def test_local_counter_lets_exactly_the_remaining_quota_through():
    results = _race([LocalDailyCounter()], _Repository(used=0))
    assert results.count(200) == 5
    assert results.count(429) == 15


def test_redis_counter_lets_exactly_the_remaining_quota_through():
    results = _race([RedisDailyCounter(_FakeRedis())], _Repository(used=0))
    assert results.count(200) == 5
    assert results.count(429) == 15


def test_two_processes_sharing_redis_never_exceed_the_quota():
    redis_client = _FakeRedis()
    processes = [RedisDailyCounter(redis_client), RedisDailyCounter(redis_client)]
    results = _race(processes, _Repository(used=0))
    assert results.count(200) == 5
    assert results.count(429) == 15


def test_a_write_landing_mid_request_is_never_counted_twice():
    repository = _Repository(used=0)
    keeper = EmbedBookkeeper()
    counter = LocalDailyCounter()
    codes = []
    for _ in range(5):
        codes.append(_attempt(counter, repository, keeper))
        # 每一筆寫入都在下一個請求之前完成或還在排隊，總數不會因此多算。
        keeper.drain(timeout=5)
    assert codes == [200] * 5
    assert repository.used == 5
    assert _attempt(counter, repository, keeper) == 429


def test_rejected_requests_are_still_counted_and_recorded():
    repository = _Repository(used=0)
    keeper = EmbedBookkeeper()
    counter = LocalDailyCounter()
    for _ in range(7):
        _attempt(counter, repository, keeper)
    assert keeper.drain(timeout=5)
    assert len(repository.written) == 7


def test_taipei_midnight_splits_the_redis_key():
    redis_client = _FakeRedis()
    counter = RedisDailyCounter(redis_client)
    repository = _Repository()
    keeper = EmbedBookkeeper()
    before = datetime(2026, 11, 20, 23, 59, tzinfo=TAIPEI)
    after = datetime(2026, 11, 21, 0, 1, tzinfo=TAIPEI)
    _attempt(counter, repository, keeper, now=before)
    _attempt(counter, repository, keeper, now=after)
    assert sorted(redis_client.values) == [
        "vman:embed-daily:ovk_test:2026-11-20",
        "vman:embed-daily:ovk_test:2026-11-21",
    ]
    assert keeper.drain(timeout=5)
    assert {day for _, day in repository.written} == {"2026-11-20", "2026-11-21"}


def test_utc_evening_is_already_the_next_taipei_day():
    # UTC 16:30 是台北隔天 00:30；舊的 UTC 日會把它算在前一天。
    moment = datetime(2026, 11, 20, 16, 30, tzinfo=timezone.utc)
    assert embed.taipei_day(moment) == "2026-11-21"


def test_retry_after_counts_down_to_taipei_midnight():
    repository = _Repository(used=5)
    keeper = EmbedBookkeeper()
    now = datetime(2026, 11, 20, 23, 59, 30, tzinfo=TAIPEI)
    with pytest.raises(HTTPException) as caught:
        authorize_embed_request(
            _key(), method="POST", path="/api/v1/chat", origin=ORIGIN,
            repository=repository, limiter=_NoLimit(), bookkeeper=keeper,
            daily_counter=LocalDailyCounter(), now=now,
        )
    assert caught.value.status_code == 429
    assert int(caught.value.headers["Retry-After"]) == 30
    assert keeper.drain(timeout=5)


def test_a_redis_failure_falls_back_to_local_counting_and_lets_requests_through():
    counter = RedisDailyCounter(_BrokenRedis())
    repository = _Repository(used=0)
    keeper = EmbedBookkeeper()
    codes = [_attempt(counter, repository, keeper) for _ in range(6)]
    assert codes == [200] * 5 + [429]
    assert keeper.drain(timeout=5)


def test_a_missing_redis_key_starts_from_the_sqlite_count():
    redis_client = _FakeRedis()
    counter = RedisDailyCounter(redis_client)
    repository = _Repository(used=3)
    keeper = EmbedBookkeeper()
    # 已寫入 3 筆、上限 5：只剩 2 筆。
    codes = [_attempt(counter, repository, keeper) for _ in range(3)]
    assert codes == [200, 200, 429]
    assert keeper.drain(timeout=5)


def test_sqlite_is_read_only_while_the_redis_key_is_missing():
    redis_client = _FakeRedis()
    counter = RedisDailyCounter(redis_client)
    repository = _Repository(used=0)
    for _ in range(4):
        counter.count_use("ovk_test", "2026-11-20", lambda: repository.requests_today("ovk_test"))
    assert repository.seed_reads == 1
    assert redis_client.ttl["vman:embed-daily:ovk_test:2026-11-20"] == 2 * 24 * 3600


def test_an_unreadable_sqlite_seed_counts_from_zero():
    def locked():
        raise sqlite3.OperationalError("database is locked")

    assert LocalDailyCounter().count_use("ovk_test", "2026-11-20", locked) == 1
    assert RedisDailyCounter(_FakeRedis()).count_use("ovk_test", "2026-11-20", locked) == 1
