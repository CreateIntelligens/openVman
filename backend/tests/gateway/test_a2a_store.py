"""Unit tests for A2A credential persistence store, encryption at rest, and key rotation."""

import json
import os
from pathlib import Path
import stat
import pytest

from app.gateway.a2a_store import (
    A2ACredentialStore,
    A2ACredentials,
    compute_key_fingerprint,
)


def test_compute_key_fingerprint():
    f1 = compute_key_fingerprint("test-private-circle")
    f2 = compute_key_fingerprint("test-private-circle")
    f3 = compute_key_fingerprint("other-key")
    f_empty = compute_key_fingerprint("")
    assert f1 == f2
    assert f1 != f3
    assert f1.startswith("hmac-sha256:")
    assert f_empty == "none"


def test_save_and_load_credentials_encrypted(tmp_path: Path):
    store_file = tmp_path / "credentials.json"
    encryption_key = "test-secret-key-12345"
    store = A2ACredentialStore(store_file, encryption_key=encryption_key)

    hub_url = "https://a2a.david888.com"
    hub_key = "test-private-circle"

    # Initially empty
    assert store.load(hub_url, hub_key) is None

    creds = A2ACredentials(
        agentId="agent-12345",
        agentToken="token-secret-abc",
        circleId="ai360",
        hubUrl=hub_url,
        hubKeyFingerprint=compute_key_fingerprint(hub_key, encryption_key),
        displayName="openVman",
    )
    store.save(creds)

    assert store_file.exists()
    # Check permissions 0600 (owner read/write only)
    file_stat = os.stat(store_file)
    file_perm = stat.S_IMODE(file_stat.st_mode)
    assert file_perm == 0o600

    # Ensure plaintext token NEVER appears in the file on disk
    raw_disk_content = store_file.read_text(encoding="utf-8")
    assert "token-secret-abc" not in raw_disk_content
    assert "encryptedAgentToken" in raw_disk_content

    # Load matching
    loaded = store.load(hub_url, hub_key)
    assert loaded is not None
    assert loaded.agent_id == "agent-12345"
    assert loaded.agent_token == "token-secret-abc"
    assert loaded.circle_id == "ai360"


def test_key_rotation_invalidates_credentials(tmp_path: Path):
    store_file = tmp_path / "credentials.json"
    encryption_key = "test-encryption-key-12345"
    store = A2ACredentialStore(store_file, encryption_key=encryption_key)

    hub_url = "https://a2a.david888.com"
    old_key = "test-private-circle"
    new_key = "team-new-circle"

    creds = A2ACredentials(
        agentId="agent-12345",
        agentToken="token-secret-abc",
        circleId="ai360",
        hubUrl=hub_url,
        hubKeyFingerprint=compute_key_fingerprint(old_key, encryption_key),
    )
    store.save(creds)

    # Old key loads fine
    assert store.load(hub_url, old_key) is not None

    # Rotated key triggers mismatch -> returns None (triggers re-registration)
    assert store.load(hub_url, new_key) is None


def test_corrupt_credentials_fails_closed(tmp_path: Path):
    store_file = tmp_path / "credentials.json"
    store = A2ACredentialStore(store_file, encryption_key="test-encryption-key-12345")

    store_file.write_text("{corrupt json", encoding="utf-8")
    assert store.load("https://a2a.david888.com", "ai360") is None
