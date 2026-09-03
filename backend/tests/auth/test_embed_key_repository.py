"""Storage-level behaviour of embed keys: schema, key ids, and daily counting."""

from __future__ import annotations

from pathlib import Path

import pytest

from app.auth.database import AuthDatabase
from app.auth.embed import SlidingWindowRateLimiter
from app.auth.repositories import (
    EmbedKeyNotFoundError,
    EmbedKeyRepository,
    generate_embed_key_id,
    utc_day,
)


@pytest.fixture
def repository(tmp_path: Path) -> EmbedKeyRepository:
    database = AuthDatabase(tmp_path / "accounts.db")
    database.initialize()
    return EmbedKeyRepository(database)


def _create(repository: EmbedKeyRepository, **overrides):
    payload = {
        "label": "Partner",
        "project_id": "default",
        "allowed_origins": ["https://partner.example"],
    }
    payload.update(overrides)
    return repository.create(**payload)


def test_generated_key_id_shape_is_prefix_plus_24_base32_chars():
    key_id = generate_embed_key_id()

    assert key_id.startswith("ovk_")
    random_part = key_id[len("ovk_") :]
    assert len(random_part) == 24
    assert set(random_part) <= set("abcdefghijklmnopqrstuvwxyz234567")


def test_generated_key_ids_do_not_repeat():
    assert len({generate_embed_key_id() for _ in range(200)}) == 200


def test_create_persists_every_field(repository):
    record = _create(
        repository,
        default_character_id="aria",
        allowed_character_ids=["nova", "sol"],
        default_persona_id="host",
        default_tts_provider="indextts",
        default_tts_voice="hayley",
        rate_limit_per_minute=30,
        daily_request_quota=300,
        created_by="user-1",
    )

    reloaded = repository.get(record.key_id)
    assert reloaded == record
    assert reloaded.allowed_origins == ("https://partner.example",)
    assert reloaded.allowed_character_ids == ("nova", "sol")
    assert reloaded.rate_limit_per_minute == 30
    assert reloaded.daily_request_quota == 300
    assert reloaded.disabled is False
    assert reloaded.last_used_at is None


def test_create_rejects_an_empty_origin_list(repository):
    with pytest.raises(ValueError):
        _create(repository, allowed_origins=[])


@pytest.mark.parametrize(
    ("field", "value"),
    [("rate_limit_per_minute", 0), ("daily_request_quota", 0)],
)
def test_create_rejects_limits_below_one(repository, field, value):
    with pytest.raises(ValueError):
        _create(repository, **{field: value})


def test_update_rejects_an_unknown_field(repository):
    record = _create(repository)

    with pytest.raises(ValueError):
        repository.update(record.key_id, project_id="other")


def test_update_of_a_missing_key_raises(repository):
    with pytest.raises(EmbedKeyNotFoundError):
        repository.update("ovk_missing", label="x")


def test_delete_removes_the_key_and_its_daily_rows(repository):
    record = _create(repository)
    repository.increment_daily(record.key_id)

    repository.delete(record.key_id)

    assert repository.get(record.key_id) is None
    assert repository.requests_today(record.key_id) == 0
    with pytest.raises(EmbedKeyNotFoundError):
        repository.delete(record.key_id)


def test_touch_records_last_used_at(repository):
    record = _create(repository)

    repository.touch(record.key_id)

    assert repository.get(record.key_id).last_used_at is not None


def test_daily_counter_is_per_key_and_per_day(repository):
    first = _create(repository)
    second = _create(repository)

    assert repository.increment_daily(first.key_id) == 1
    assert repository.increment_daily(first.key_id) == 2
    assert repository.increment_daily(second.key_id) == 1

    assert repository.requests_today(first.key_id) == 2
    assert repository.requests_today(second.key_id) == 1
    # 換一天就重新從零開始計數。
    assert repository.requests_today(first.key_id, day="2000-01-01") == 0
    assert repository.increment_daily(first.key_id, day="2000-01-01") == 1


def test_list_all_returns_every_key(repository):
    created = {_create(repository).key_id for _ in range(3)}

    assert {record.key_id for record in repository.list_all()} == created


def test_utc_day_is_an_iso_date():
    assert len(utc_day()) == len("2026-01-01")
    assert utc_day().count("-") == 2


# --- Sliding window limiter -----------------------------------------------


def test_limiter_allows_up_to_the_limit_then_reports_retry_after():
    limiter = SlidingWindowRateLimiter(window_seconds=60.0)

    assert limiter.check("k", 2, now=0.0) == 0
    assert limiter.check("k", 2, now=1.0) == 0
    retry_after = limiter.check("k", 2, now=2.0)

    assert retry_after >= 1


def test_limiter_frees_the_window_as_time_passes():
    limiter = SlidingWindowRateLimiter(window_seconds=60.0)
    limiter.check("k", 1, now=0.0)

    assert limiter.check("k", 1, now=30.0) > 0
    assert limiter.check("k", 1, now=61.0) == 0


def test_limiter_counts_each_key_separately():
    limiter = SlidingWindowRateLimiter(window_seconds=60.0)

    assert limiter.check("a", 1, now=0.0) == 0
    assert limiter.check("b", 1, now=0.0) == 0
    assert limiter.check("a", 1, now=0.0) > 0
