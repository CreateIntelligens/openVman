"""Project Gemini credentials stay encrypted and fail closed when bound."""

from __future__ import annotations

import sqlite3
from dataclasses import replace
from types import SimpleNamespace

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app import internal_routes
from app.auth import model_provider_routes
from app.auth import runtime as runtime_module
from app.auth.dependencies import AuthTransport, CurrentAccount, require_root
from app.auth.model_provider_repository import CategoryUpdate
from app.auth.model_provider_routes import internal_runtime_configuration
from app.auth.models import AccountRole, ResourceType, ResourceVisibility
from app.auth.project_gemini_credential_routes import router
from app.auth.project_gemini_credentials import (
    ProjectCredentialUnavailable,
    project_gemini_repository,
    resolve_gemini_credential,
)
from app.auth.runtime import build_auth_runtime, get_auth_runtime
from app.config import TTSRouterConfig

PATH = "/api/v1/projects/project-a/gemini-credential"
KEY = "project-a-secret-value"


@pytest.fixture()
def context(tmp_path, monkeypatch):
    runtime = build_auth_runtime(TTSRouterConfig(
        _env_file=None,
        env="dev",
        session_jwt_secret="test-session-secret-with-at-least-32-bytes",
        model_provider_encryption_secret="test-provider-secret-with-at-least-32-bytes",
        auth_database_path=str(tmp_path / "accounts.db"),
        gemini_api_key="environment-shared-key",
    ))
    root = runtime.users.create_root(username="ai360", password_hash="hash")
    for project in ("project-a", "project-b"):
        runtime.resources.register(
            resource_type=ResourceType.PROJECT,
            resource_id=project,
            visibility=ResourceVisibility.PRIVATE,
            owner_user_id=root.id,
        )
    calls = []
    monkeypatch.setattr(
        model_provider_routes, "_brain_post",
        lambda _runtime, path, body=None: calls.append(path) or {},
    )
    # The management module imports the same helper explicitly.
    monkeypatch.setattr(
        "app.auth.project_gemini_credential_routes._brain_post",
        lambda _runtime, path, body=None: calls.append(path) or {},
    )
    app = FastAPI()
    app.include_router(router)
    app.include_router(internal_routes.router)
    app.dependency_overrides[get_auth_runtime] = lambda: runtime
    app.dependency_overrides[require_root] = lambda: CurrentAccount(
        root, AuthTransport.BEARER,
    )
    monkeypatch.setattr(runtime_module, "get_auth_runtime", lambda: runtime)
    monkeypatch.setattr(
        internal_routes, "get_tts_config",
        lambda: SimpleNamespace(gateway_internal_token="internal-token"),
    )
    with TestClient(app) as client:
        yield runtime, root, app, client, calls


def _bind(runtime, root, project="project-a", key=KEY):
    project_gemini_repository(runtime).put(
        project, label="Customer key", api_key=key, actor_id=root.id,
    )


def test_root_manages_only_metadata_with_encryption_and_safe_audit(context):
    runtime, _, _, client, calls = context
    initial = client.get(PATH)
    assert initial.status_code == 200
    assert initial.json()["source"] == "shared"
    assert "environment-shared-key" not in initial.text

    response = client.put(
        PATH, json={"label": "  Customer A  ", "api_key": f"  {KEY}  "},
    )
    assert response.status_code == 200
    assert KEY not in response.text
    metadata = response.json()
    assert metadata["source"] == "project"
    assert metadata["label"] == "Customer A"
    assert metadata["configured"] is True
    assert metadata["masked"] == "••••alue"
    assert metadata["credential_id"].startswith("pgc_")
    assert metadata["updated_at"]
    assert metadata["runtime_refreshed"] is True
    assert calls == ["/brain/internal/model-providers/refresh"]
    assert KEY not in client.get(PATH).text
    assert KEY not in repr(resolve_gemini_credential("project-a", runtime))
    with runtime.database.transaction() as connection:
        row = connection.execute(
            "SELECT ciphertext FROM project_gemini_credentials",
        ).fetchone()
        audit = connection.execute(
            "SELECT metadata_json FROM auth_audit_events "
            "WHERE action = 'project_gemini_credential_updated'",
        ).fetchone()
    assert KEY not in row["ciphertext"]
    assert KEY not in audit["metadata_json"]


@pytest.mark.parametrize("role", [AccountRole.ADMIN, AccountRole.USER])
def test_non_root_cannot_manage_keys(context, role):
    runtime, _, app, client, _ = context
    user = runtime.users.create(
        username=role.value, password_hash="hash", role=role,
    )
    app.dependency_overrides.clear()
    app.dependency_overrides[get_auth_runtime] = lambda: runtime
    headers = {"Authorization": f"Bearer {runtime.tokens.issue(user)}"}
    for method in ("get", "put", "delete"):
        response = getattr(client, method)(
            PATH, headers=headers,
            **({"json": {"label": "Customer", "api_key": KEY}}
               if method == "put" else {}),
        )
        assert response.status_code == 403
        assert KEY not in response.text


@pytest.mark.parametrize("method", ["get", "put", "delete"])
def test_management_requires_existing_project(context, method):
    _, _, _, client, _ = context
    response = getattr(client, method)(
        PATH.replace("project-a", "missing"),
        **({"json": {"label": "Customer", "api_key": KEY}}
           if method == "put" else {}),
    )
    assert response.status_code == 404


@pytest.mark.parametrize("api_key", ["", "  ", "s" * 4097])
def test_invalid_secret_does_not_leak_in_validation(context, api_key):
    _, _, _, client, _ = context
    response = client.put(PATH, json={"label": "Customer", "api_key": api_key})
    assert response.status_code == 422
    if api_key.strip():
        assert api_key not in response.text


@pytest.mark.parametrize("body", [
    {"api_key": KEY},
    {"label": {"api_key": KEY}, "api_key": KEY},
    {"label": "Customer", "api_key": KEY, "unexpected": KEY},
    [{"api_key": KEY}],
])
def test_malformed_body_does_not_echo_secrets(context, body):
    _, _, _, client, _ = context
    response = client.put(PATH, json=body)
    assert response.status_code == 422
    assert KEY not in response.text


def test_project_keys_and_shared_admin_key_are_isolated(context):
    runtime, root, _, client, _ = context
    runtime.model_providers.update(
        {}, credentials={"gemini": "admin-shared-key"}, actor_id=root.id,
    )
    _bind(runtime, root)
    _bind(runtime, root, "project-b", "project-b-secret-value")
    assert resolve_gemini_credential("project-a", runtime).api_key == KEY
    assert resolve_gemini_credential("project-b", runtime).api_key == "project-b-secret-value"
    assert resolve_gemini_credential(None, runtime).api_key == "admin-shared-key"
    assert resolve_gemini_credential("default", runtime).api_key == "admin-shared-key"
    response = client.delete(PATH)
    assert response.status_code == 200
    assert response.json()["source"] == "shared"
    assert response.json()["credential_id"] == "gemini"
    assert resolve_gemini_credential("project-a", runtime).api_key == "admin-shared-key"
    assert resolve_gemini_credential("project-b", runtime).source == "project"


def test_update_keeps_id_and_project_delete_removes_binding(context):
    runtime, root, _, _, _ = context
    _bind(runtime, root)
    first = resolve_gemini_credential("project-a", runtime)
    _bind(runtime, root, key="replacement-project-key")
    assert resolve_gemini_credential("project-a", runtime).credential_id == first.credential_id
    runtime.resources.unregister(ResourceType.PROJECT, "project-a")
    assert project_gemini_repository(runtime).get("project-a") is None
    runtime.resources.register(
        resource_type=ResourceType.PROJECT,
        resource_id="project-a",
        visibility=ResourceVisibility.PRIVATE,
        owner_user_id=root.id,
    )
    recreated = resolve_gemini_credential("project-a", runtime)
    assert recreated.source == "shared"
    assert recreated.api_key == "environment-shared-key"


@pytest.mark.parametrize("failure", [
    "ciphertext", "encryption-secret", "missing-encryption-secret", "empty",
])
def test_bound_key_decryption_failure_never_uses_shared(context, failure):
    runtime, root, _, client, _ = context
    _bind(runtime, root)
    if failure in {"encryption-secret", "missing-encryption-secret"}:
        runtime = replace(
            runtime, config=runtime.config.model_copy(
                update={"model_provider_encryption_secret": (
                    "changed" * 10 if failure == "encryption-secret" else ""
                )},
            ),
        )
    else:
        repository = project_gemini_repository(runtime)
        ciphertext = (
            repository.cipher.encrypt("gemini", "")
            if failure == "empty" else "not-fernet-ciphertext"
        )
        with runtime.database.transaction(write=True) as connection:
            connection.execute(
                "UPDATE project_gemini_credentials SET ciphertext = ?",
                (ciphertext,),
            )
    with pytest.raises(ProjectCredentialUnavailable) as error:
        resolve_gemini_credential("project-a", runtime)
    assert error.value.status_code == 503
    assert error.value.detail == "project_gemini_credential_unavailable"
    if failure not in {"encryption-secret", "missing-encryption-secret"}:
        response = client.get(PATH)
        assert response.status_code == 200
        assert response.json()["source"] == "project"
        assert response.json()["masked"] == "••••"
        assert KEY not in response.text
        assert client.delete(PATH).json()["source"] == "shared"


def test_unknown_binding_state_fails_closed(context, monkeypatch):
    runtime, _, _, _, _ = context
    monkeypatch.setattr(
        "app.auth.project_gemini_credentials.ProjectGeminiCredentialRepository.get",
        lambda *_: (_ for _ in ()).throw(sqlite3.OperationalError("offline")),
    )
    with pytest.raises(ProjectCredentialUnavailable):
        resolve_gemini_credential("project-a", runtime)
    assert resolve_gemini_credential(None, runtime).source == "shared"


def test_internal_project_runtime_uses_bound_key_only_with_internal_auth(context):
    runtime, root, _, client, _ = context
    _bind(runtime, root)
    url = "/api/v1/internal/model-providers?project_id=project-a"
    rejected = client.get(url)
    assert rejected.status_code == 403
    assert KEY not in rejected.text
    response = client.get(url, headers={"X-Internal-Token": "internal-token"})
    assert response.status_code == 200
    assert response.json()["gemini_credential"]["api_key"] == KEY
    assert response.json()["gemini_credential"]["source"] == "project"
    assert response.json()["chat_llm"] == {
        "configured": False, "credential_overrides": {"gemini": KEY},
    }
    runtime.model_providers.update(
        {"chat_llm": CategoryUpdate(
            ("gemini", "openai", "groq", "nen"), ("gemini", "openai"),
        )},
        credentials={"openai": "shared-openai-key"}, actor_id=root.id,
    )
    chat = internal_runtime_configuration(
        runtime, project_id="project-a",
    )["chat_llm"]
    providers = chat["providers"]
    assert chat["credential_overrides"] == {"gemini": KEY}
    assert providers[0]["api_key"] == KEY
    assert providers[0]["credential_source"] == "project"
    assert providers[1]["api_key"] == "shared-openai-key"
    assert providers[1]["credential_source"] == "admin"


def test_internal_bound_failure_returns_explicit_code(context):
    runtime, root, _, client, _ = context
    _bind(runtime, root)
    with runtime.database.transaction(write=True) as connection:
        connection.execute(
            "UPDATE project_gemini_credentials SET ciphertext = 'corrupt'",
        )
    response = client.get(
        "/api/v1/internal/model-providers?project_id=project-a",
        headers={"X-Internal-Token": "internal-token"},
    )
    assert response.status_code == 503
    assert response.json() == {"detail": "project_gemini_credential_unavailable"}


def test_migration_is_idempotent(context):
    runtime, root, _, _, _ = context
    _bind(runtime, root)
    runtime.database.initialize()
    assert resolve_gemini_credential("project-a", runtime).api_key == KEY
    with runtime.database.transaction() as connection:
        assert connection.execute("PRAGMA foreign_key_check").fetchall() == []


def test_root_token_is_required_and_can_manage_keys(context):
    runtime, root, app, client, _ = context
    app.dependency_overrides.clear()
    app.dependency_overrides[get_auth_runtime] = lambda: runtime
    assert client.get(PATH).status_code == 401
    headers = {"Authorization": f"Bearer {runtime.tokens.issue(root)}"}
    assert client.put(
        PATH, headers=headers, json={"label": "Customer", "api_key": KEY},
    ).status_code == 200
    assert client.get(PATH, headers=headers).json()["source"] == "project"
    assert client.delete(PATH, headers=headers).json()["source"] == "shared"


def test_v23_upgrade_preserves_existing_resources_and_shared_key(context):
    runtime, root, _, _, _ = context
    runtime.model_providers.update(
        {}, credentials={"gemini": "saved-shared-key"}, actor_id=root.id,
    )
    with runtime.database.transaction(write=True) as connection:
        connection.execute("DROP TABLE project_gemini_credentials")
        connection.execute("DELETE FROM schema_migrations WHERE version = 24")
    runtime.database.initialize()
    assert runtime.resources.get(ResourceType.PROJECT, "project-a") is not None
    assert resolve_gemini_credential("project-a", runtime).api_key == "saved-shared-key"
    _bind(runtime, root)
    assert resolve_gemini_credential("project-a", runtime).api_key == KEY
