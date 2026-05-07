"""Tests for the embed API key CLI."""

from __future__ import annotations

import io
import json

from app.gateway.embed_keys import EmbedKeyStore
from scripts.embed_keys_cli import main


def _run_cli(tmp_path, *args: str) -> dict:
    stdout = io.StringIO()
    exit_code = main(["--store", str(tmp_path / "embed_keys.json"), *args], stdout=stdout)
    assert exit_code == 0
    return json.loads(stdout.getvalue())


def test_create_prints_plaintext_secret_once_and_list_hides_it(tmp_path):
    created = _run_cli(
        tmp_path,
        "create",
        "--tenant-id",
        "tenant-a",
        "--domain",
        "example.com",
        "--note",
        "demo",
    )

    assert created["key_id"]
    assert len(created["secret"]) >= 32
    assert created["tenant_id"] == "tenant-a"

    listed = _run_cli(tmp_path, "list")

    assert listed["keys"][0]["key_id"] == created["key_id"]
    assert "secret" not in listed["keys"][0]
    assert listed["keys"][0]["secret_hash"].startswith("sha256:")
    assert created["secret"] not in json.dumps(listed)


def test_disable_revokes_key(tmp_path):
    created = _run_cli(
        tmp_path,
        "create",
        "--tenant-id",
        "tenant-a",
        "--domain",
        "example.com",
    )
    disabled = _run_cli(tmp_path, "disable", created["key_id"])
    store = EmbedKeyStore(tmp_path / "embed_keys.json")

    assert disabled == {"key_id": created["key_id"], "disabled": True}
    assert store.get(created["secret"]) is None


def test_rotate_disables_old_key_and_prints_new_secret_once(tmp_path):
    created = _run_cli(
        tmp_path,
        "create",
        "--tenant-id",
        "tenant-a",
        "--domain",
        "example.com",
    )

    rotated = _run_cli(tmp_path, "rotate", created["key_id"])
    store = EmbedKeyStore(tmp_path / "embed_keys.json")

    assert rotated["old_key_id"] == created["key_id"]
    assert rotated["key_id"] != created["key_id"]
    assert rotated["secret"]
    assert store.get(created["secret"]) is None
    assert store.get(rotated["secret"]) is not None

    listed = _run_cli(tmp_path, "list")
    assert rotated["secret"] not in json.dumps(listed)
