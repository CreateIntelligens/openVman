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
    def record_use(self, key_id):
        raise sqlite3.OperationalError("database is locked")


class _CountingRepository:
    def __init__(self, used):
        self.used = used

    def record_use(self, key_id):
        return self.used


class _NoLimit:
    def check(self, key, limit):
        return 0


def test_a_locked_database_lets_the_request_through():
    authorize_embed_request(
        _key(), method="POST", path="/api/v1/chat/stream", origin="https://ok.example",
        repository=_LockedRepository(), limiter=_NoLimit(),
    )


def test_the_daily_quota_still_applies_when_bookkeeping_succeeds():
    import pytest
    from fastapi import HTTPException

    with pytest.raises(HTTPException) as caught:
        authorize_embed_request(
            _key(), method="POST", path="/api/v1/chat/stream", origin="https://ok.example",
            repository=_CountingRepository(11), limiter=_NoLimit(),
        )
    assert caught.value.status_code == 429
