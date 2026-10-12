"""Encrypted model provider credentials and per-category ordering."""

from __future__ import annotations

import json
import sqlite3

import pytest

from app.auth.database import AuthDatabase
from app.auth.model_provider_repository import (
    CategoryUpdate,
    InvalidModelProviderSettings,
    ModelProviderCipher,
    ModelProviderRepository,
)
from app.auth.passwords import hash_password
from app.auth.user_repository import UserRepository

SECRET = "d" * 64


@pytest.fixture()
def provider_settings(tmp_path):
    database = AuthDatabase(tmp_path / "auth" / "accounts.db")
    database.initialize()
    root = UserRepository(database).create_root(
        username="ai360", password_hash=hash_password("root-password"),
    )
    return database, root, ModelProviderRepository(database, encryption_secret=SECRET)


def test_unsaved_category_reports_none_so_callers_use_deployment_defaults(provider_settings):
    _, _, repository = provider_settings

    assert repository.get_settings("decision") is None
    assert repository.get_settings("chat_llm") is None


def test_order_enabled_and_models_round_trip_per_category(provider_settings):
    _, root, repository = provider_settings

    repository.update(
        {
            "decision": CategoryUpdate(
                ("openai", "jev", "clef-backup", "clef-primary"), ("openai", "jev"),
            ),
            "chat_llm": CategoryUpdate(
                ("groq", "gemini", "openai", "nen"), ("groq", "gemini"),
                {"groq": "openai/gpt-oss-20b"},
            ),
        },
        credentials={},
        actor_id=root.id,
    )

    decision = repository.get_settings("decision")
    chat = repository.get_settings("chat_llm")
    assert decision is not None and decision.order[0] == "openai"
    assert chat is not None
    assert chat.enabled == ("groq", "gemini")
    assert chat.models == {"groq": "openai/gpt-oss-20b"}


@pytest.mark.parametrize("change", [
    CategoryUpdate(("jev", "jev"), ("jev",)),
    CategoryUpdate(("openai", "jev", "clef-backup", "clef-primary"), ("ghost",)),
    # 決策的模型跟端點綁死，不能從後台換。
    CategoryUpdate(
        ("openai", "jev", "clef-backup", "clef-primary"), (), {"openai": "gpt-4.1"},
    ),
])
def test_decision_rejects_bad_hops_and_model_changes(provider_settings, change):
    _, root, repository = provider_settings

    with pytest.raises(InvalidModelProviderSettings):
        repository.update({"decision": change}, credentials={}, actor_id=root.id)


@pytest.mark.parametrize("model", ["", "has space", "x" * 200, "../etc"])
def test_chat_model_names_are_validated(provider_settings, model):
    _, root, repository = provider_settings
    change = CategoryUpdate(("gemini", "openai", "groq", "nen"), ("gemini",), {"gemini": model})

    with pytest.raises(InvalidModelProviderSettings):
        repository.update({"chat_llm": change}, credentials={}, actor_id=root.id)


def test_unknown_category_is_rejected(provider_settings):
    _, root, repository = provider_settings

    with pytest.raises(InvalidModelProviderSettings):
        repository.update(
            {"vision": CategoryUpdate((), ())}, credentials={}, actor_id=root.id,
        )


def test_credentials_are_encrypted_and_audited_without_secret(provider_settings):
    database, root, repository = provider_settings
    key = "provider-secret-value"

    repository.update({}, credentials={"gemini": key}, actor_id=root.id)

    assert repository.get_credential("gemini", env_default="") == key
    with database.transaction() as connection:
        row = connection.execute(
            "SELECT ciphertext FROM model_provider_secrets WHERE credential_id = 'gemini'",
        ).fetchone()
        audit = connection.execute(
            "SELECT metadata_json FROM auth_audit_events "
            "WHERE action = 'model_provider_credential_updated'",
        ).fetchone()
    assert key not in row["ciphertext"]
    assert key not in audit["metadata_json"]
    assert json.loads(audit["metadata_json"]) == {"credential_id": "gemini", "configured": True}


def test_admin_clear_overrides_environment_key(provider_settings):
    _, root, repository = provider_settings
    repository.update({}, credentials={"jev": ""}, actor_id=root.id)

    assert repository.get_credential("jev", env_default="deployment-key") == ""
    status = repository.get_credential_status("jev", env_default="deployment-key")
    assert status.configured is False
    assert status.source == "admin"


def test_reset_returns_to_environment_key(provider_settings):
    _, root, repository = provider_settings
    repository.update({}, credentials={"jev": "admin-key"}, actor_id=root.id)
    repository.update({}, credentials={}, reset_credentials=["jev"], actor_id=root.id)

    assert repository.get_credential("jev", env_default="deployment-key") == "deployment-key"
    assert repository.get_credential_status("jev", env_default="deployment-key").source == "environment"


def test_absent_override_uses_environment_key(provider_settings):
    _, _, repository = provider_settings

    status = repository.get_credential_status("jev", env_default="deployment-key")
    assert repository.get_credential("jev", env_default="deployment-key") == "deployment-key"
    assert status.configured is True
    assert status.source == "environment"
    assert status.masked.endswith("-key")


def test_unreadable_saved_key_falls_back_to_environment_and_is_flagged(provider_settings):
    """換掉加密 secret 不能讓聊天停掉：解不開的 key 退回 .env，並標示要重新輸入。"""
    database, root, repository = provider_settings
    repository.update({}, credentials={"openai": "provider-secret-value"}, actor_id=root.id)
    restarted = ModelProviderRepository(database, encryption_secret="x" * 64)

    assert restarted.get_credential("openai", env_default="deployment-key") == "deployment-key"
    status = restarted.get_credential_status("openai", env_default="deployment-key")
    assert status.source == "unreadable"
    assert status.configured is True
    assert restarted.get_credential_status("openai", env_default="").configured is False
    assert restarted.unreadable_credentials() == ["openai"]
    assert repository.unreadable_credentials() == []


def test_migration_carries_decision_settings_and_keys_over(tmp_path):
    """Keys saved on the old decision page must still decrypt after the upgrade."""
    path = tmp_path / "accounts.db"
    AuthDatabase(path).initialize()
    # 退回到 v17 的樣子：只有決策兩張表，v19 還沒跑。
    connection = sqlite3.connect(path)
    connection.executescript(
        """
        DROP TABLE model_provider_settings;
        DROP TABLE model_provider_secrets;
        DELETE FROM schema_migrations WHERE version = 19;
        """,
    )
    order = ["jev", "openai", "clef-primary", "clef-backup"]
    connection.execute(
        "INSERT INTO decision_provider_settings VALUES (1, ?, ?, NULL, 'then')",
        (json.dumps(order), json.dumps(["jev"])),
    )
    connection.execute(
        "INSERT INTO decision_provider_secrets VALUES ('clef', ?, NULL, 'then')",
        (ModelProviderCipher(SECRET).encrypt("clef", "old-clef-key"),),
    )
    connection.commit()
    connection.close()
    database = AuthDatabase(path)
    database.initialize()
    repository = ModelProviderRepository(database, encryption_secret=SECRET)

    settings = repository.get_settings("decision")
    assert settings is not None
    assert list(settings.order) == order
    assert settings.enabled == ("jev",)
    assert repository.get_credential("clef", env_default="") == "old-clef-key"
    with database.transaction() as connection:
        tables = {
            row["name"] for row in connection.execute(
                "SELECT name FROM sqlite_master WHERE type = 'table'",
            )
        }
    # 舊表保留，退回舊版程式時還讀得到升級當下的設定。
    assert {"decision_provider_settings", "decision_provider_secrets"} <= tables
