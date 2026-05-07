"""Tests for public embed API key storage."""

from __future__ import annotations

import json

from app.gateway.embed_keys import EmbedKeyStore


class FakeClock:
    def __init__(self) -> None:
        self.current = 1_700_000_000.0

    def __call__(self) -> float:
        return self.current

    def advance(self, seconds: float) -> None:
        self.current += seconds


def test_create_persists_key_with_hashed_secret(tmp_path):
    store_path = tmp_path / "embed_keys.json"
    store = EmbedKeyStore(store_path)

    created = store.create(
        tenant_id="tenant-a",
        allowed_domains=["example.com"],
        note="demo key",
    )

    assert len(created.secret) >= 32
    assert created.record.tenant_id == "tenant-a"
    assert created.record.allowed_domains == ["example.com"]
    assert created.record.secret_hash != created.secret
    assert created.record.secret_hash.startswith("sha256:")

    raw_payload = json.loads(store_path.read_text(encoding="utf-8"))
    raw_text = store_path.read_text(encoding="utf-8")
    assert created.secret not in raw_text
    assert raw_payload["keys"][0]["secret_hash"] == created.record.secret_hash

    fetched = store.get(created.secret)
    assert fetched is not None
    assert fetched.key_id == created.record.key_id

    listed = store.list()
    assert [record.key_id for record in listed] == [created.record.key_id]
    assert all(not hasattr(record, "secret") for record in listed)


def test_disable_revokes_key_for_same_store(tmp_path):
    store = EmbedKeyStore(tmp_path / "embed_keys.json")
    created = store.create(
        tenant_id="tenant-a",
        allowed_domains=["example.com"],
    )

    assert store.disable(created.record.key_id) is not None

    assert store.get(created.secret) is None
    [disabled_record] = store.list()
    assert disabled_record.enabled is False
    assert disabled_record.disabled_at is not None


def test_external_disable_is_visible_after_cache_ttl(tmp_path):
    clock = FakeClock()
    store_path = tmp_path / "embed_keys.json"
    writer = EmbedKeyStore(store_path, time_fn=clock)
    reader = EmbedKeyStore(store_path, time_fn=clock)
    created = writer.create(
        tenant_id="tenant-a",
        allowed_domains=["example.com"],
    )

    assert reader.get(created.secret) is not None

    assert writer.disable(created.record.key_id) is not None
    clock.advance(59)
    assert reader.get(created.secret) is not None

    clock.advance(2)
    assert reader.get(created.secret) is None


def test_create_uses_lock_file(tmp_path):
    store_path = tmp_path / "embed_keys.json"
    store = EmbedKeyStore(store_path)

    store.create(tenant_id="tenant-a", allowed_domains=["example.com"])

    assert store_path.with_suffix(".json.lock").exists()
