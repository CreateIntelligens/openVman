"""Encrypted decision provider settings and ordering."""

from __future__ import annotations

import json

import pytest

from app.auth.database import AuthDatabase
from app.auth.models import AccountRole
from app.auth.passwords import hash_password
from app.auth.repositories import UserRepository
from app.auth.decision_provider_repository import (
    DEFAULT_DECISION_ORDER,
    DecisionProviderRepository,
    InvalidDecisionProviderSettings,
)


@pytest.fixture()
def provider_settings(tmp_path):
    database = AuthDatabase(tmp_path / "auth" / "accounts.db")
    database.initialize()
    root = UserRepository(database).create_root(
        username="ai360", password_hash=hash_password("root-password"),
    )
    return database, root, DecisionProviderRepository(
        database, encryption_secret="d" * 64,
    )


def test_defaults_use_the_documented_order(provider_settings):
    _, _, repository = provider_settings
    settings = repository.get_settings()

    assert settings.order == DEFAULT_DECISION_ORDER
    assert settings.enabled == DEFAULT_DECISION_ORDER


def test_order_and_enabled_hops_round_trip(provider_settings):
    _, root, repository = provider_settings
    order = ("openai", "jev", "clef-backup", "clef-primary")
    enabled = ("openai", "jev", "clef-primary")

    repository.set_settings(order, enabled, actor_id=root.id)

    settings = repository.get_settings()
    assert settings.order == order
    assert settings.enabled == enabled


def test_order_rejects_missing_or_duplicate_hops(provider_settings):
    _, root, repository = provider_settings

    with pytest.raises(InvalidDecisionProviderSettings):
        repository.set_settings(("jev", "jev"), ("jev",), actor_id=root.id)


def test_credentials_are_encrypted_and_audited_without_secret(provider_settings):
    database, root, repository = provider_settings
    key = "provider-secret-value"

    repository.set_credential("openai", key, actor_id=root.id)

    assert repository.get_credential("openai", env_default="") == key
    with database.transaction() as connection:
        row = connection.execute(
            "SELECT ciphertext FROM decision_provider_secrets WHERE provider_id = 'openai'",
        ).fetchone()
        audit = connection.execute(
            "SELECT metadata_json FROM auth_audit_events "
            "WHERE action = 'decision_provider_credential_updated'",
        ).fetchone()
    assert key not in row["ciphertext"]
    assert key not in audit["metadata_json"]
    assert json.loads(audit["metadata_json"]) == {"provider_id": "openai", "configured": True}


def test_admin_clear_overrides_environment_key(provider_settings):
    _, root, repository = provider_settings
    repository.set_credential("jev", "", actor_id=root.id)

    assert repository.get_credential("jev", env_default="deployment-key") == ""
    status = repository.get_credential_status("jev", env_default="deployment-key")
    assert status.configured is False
    assert status.source == "admin"


def test_reset_returns_to_environment_key(provider_settings):
    _, root, repository = provider_settings
    repository.set_credential("jev", "admin-key", actor_id=root.id)
    repository.update(
        repository.get_settings().order,
        repository.get_settings().enabled,
        credentials={},
        reset_credentials=["jev"],
        actor_id=root.id,
    )

    assert repository.get_credential("jev", env_default="deployment-key") == "deployment-key"
    assert repository.get_credential_status("jev", env_default="deployment-key").source == "environment"


def test_absent_override_uses_environment_key(provider_settings):
    _, _, repository = provider_settings

    assert repository.get_credential("jev", env_default="deployment-key") == "deployment-key"
    status = repository.get_credential_status("jev", env_default="deployment-key")
    assert status.configured is True
    assert status.source == "environment"
    assert status.masked.endswith("-key")


def test_wrong_encryption_secret_marks_saved_key_unavailable(provider_settings):
    database, root, repository = provider_settings
    repository.set_credential("openai", "provider-secret-value", actor_id=root.id)
    restarted = DecisionProviderRepository(database, encryption_secret="x" * 64)

    assert restarted.get_credential("openai", env_default="deployment-key") == ""
    assert restarted.get_credential_status("openai", env_default="deployment-key").configured is False
