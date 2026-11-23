"""A busy auth database must not turn embed requests into 500s."""

from __future__ import annotations

import sqlite3

from app.auth.embed import authorize_embed_request
from app.auth.models import EmbedKeyRecord


def _key() -> EmbedKeyRecord:
    return EmbedKeyRecord(
        key_id="ovk_test", label="", project_id="p", allowed_origins=("https://ok.example",),
        default_character_id="", allowed_character_ids=(), default_persona_id="",
        default_tts_provider="", default_tts_voice="", rate_limit_per_minute=100,
        daily_request_quota=10, disabled=False, created_by=None, created_at="", updated_at="",
        last_used_at=None,
    )


class _LockedRepository:
    def requests_today(self, key_id, day=None):
        raise sqlite3.OperationalError("database is locked")

    def record_use(self, key_id, day=None):
        raise sqlite3.OperationalError("database is locked")


class _CountingRepository:
    def __init__(self, used):
        self.used = used
        self.recorded = 0

    def requests_today(self, key_id, day=None):
        return self.used

    def record_use(self, key_id, day=None):
        self.recorded += 1
        return self.used + self.recorded


class _SlowRepository(_CountingRepository):
    def record_use(self, key_id, day=None):
        import time

        time.sleep(1.0)
        return super().record_use(key_id)


class _NoLimit:
    def check(self, key, limit):
        return 0


def test_a_locked_database_lets_the_request_through():
    from app.auth.embed import EmbedBookkeeper, LocalDailyCounter

    keeper = EmbedBookkeeper()
    authorize_embed_request(
        _key(), method="POST", path="/api/v1/chat/stream", origin="https://ok.example",
        repository=_LockedRepository(), limiter=_NoLimit(), bookkeeper=keeper,
        daily_counter=LocalDailyCounter(),
    )
    assert keeper.drain(timeout=5)


def test_a_slow_bookkeeping_write_does_not_hold_the_request():
    import time

    from app.auth.embed import EmbedBookkeeper, LocalDailyCounter

    keeper = EmbedBookkeeper()
    repository = _SlowRepository(0)
    started = time.perf_counter()
    authorize_embed_request(
        _key(), method="POST", path="/api/v1/chat/stream", origin="https://ok.example",
        repository=repository, limiter=_NoLimit(), bookkeeper=keeper,
        daily_counter=LocalDailyCounter(),
    )
    assert time.perf_counter() - started < 0.5
    assert keeper.drain(timeout=5)
    assert repository.recorded == 1


def test_the_daily_quota_does_not_wait_for_slow_bookkeeping_writes():
    import pytest
    from fastapi import HTTPException

    from app.auth.embed import EmbedBookkeeper, LocalDailyCounter

    keeper = EmbedBookkeeper()
    counter = LocalDailyCounter()
    repository = _SlowRepository(8)  # 已寫入 8 筆，上限 10；寫入很慢，配額仍照計數器判斷
    for _ in range(2):
        authorize_embed_request(
            _key(), method="POST", path="/api/v1/chat/stream", origin="https://ok.example",
            repository=repository, limiter=_NoLimit(), bookkeeper=keeper,
            daily_counter=counter,
        )
    with pytest.raises(HTTPException) as caught:
        authorize_embed_request(
            _key(), method="POST", path="/api/v1/chat/stream", origin="https://ok.example",
            repository=repository, limiter=_NoLimit(), bookkeeper=keeper,
            daily_counter=counter,
        )
    assert caught.value.status_code == 429
    assert keeper.drain(timeout=10)


def test_the_daily_quota_still_applies_when_bookkeeping_succeeds():
    import pytest
    from fastapi import HTTPException

    from app.auth.embed import LocalDailyCounter

    with pytest.raises(HTTPException) as caught:
        authorize_embed_request(
            _key(), method="POST", path="/api/v1/chat/stream", origin="https://ok.example",
            repository=_CountingRepository(10), limiter=_NoLimit(),
            daily_counter=LocalDailyCounter(),
        )
    assert caught.value.status_code == 429
