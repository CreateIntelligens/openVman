from __future__ import annotations

from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.auth.decision_provider_routes import router
from app.auth.models import AccountRole
from app.auth.passwords import hash_password
from app.auth.runtime import AuthRuntime, build_auth_runtime, get_auth_runtime
from app.auth.routes import auth_router
from app.config import TTSRouterConfig


def _runtime(tmp_path) -> AuthRuntime:
    return build_auth_runtime(TTSRouterConfig(
        _env_file=None,
        env="dev",
        session_jwt_secret="test-only-session-secret-for-tests-32",
        decision_provider_encryption_secret="provider-encryption-secret-for-test-32-bytes",
        auth_database_path=str(tmp_path / "accounts.db"),
        typesafe_api_key="env-jev-key",
        decision_openai_api_key="env-openai-key",
    ))


def _client(runtime: AuthRuntime) -> TestClient:
    app = FastAPI()
    app.include_router(auth_router)
    app.include_router(router)
    app.dependency_overrides[get_auth_runtime] = lambda: runtime
    return TestClient(app)


def _login(client: TestClient, runtime: AuthRuntime, role: AccountRole) -> str:
    if role is AccountRole.ROOT:
        account = runtime.users.create_root(
            username="ai360", password_hash=hash_password("test-password"),
        )
    else:
        account = runtime.users.create(
            username=f"{role.value}-user",
            password_hash=hash_password("test-password"),
            role=role,
        )
    response = client.post(
        "/api/v1/auth/login",
        json={"username": account.username, "password": "test-password"},
    )
    assert response.status_code == 200
    return response.json()["token"]


def test_admin_reads_default_order_and_only_credential_metadata(tmp_path):
    runtime = _runtime(tmp_path)
    client = _client(runtime)
    token = _login(client, runtime, AccountRole.ADMIN)

    response = client.get(
        "/api/v1/settings/decision-providers",
        headers={"Authorization": f"Bearer {token}"},
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["order"] == ["clef-primary", "clef-backup", "jev", "openai"]
    assert payload["providers"][2]["credential_configured"] is True
    assert payload["providers"][3]["credential_masked"] == "••••-key"
    assert "env-openai-key" not in response.text


def test_admin_reorders_hops_and_sets_key_without_echoing_it(tmp_path):
    runtime = _runtime(tmp_path)
    client = _client(runtime)
    token = _login(client, runtime, AccountRole.ROOT)
    key = "new-openai-provider-key"

    response = client.put(
        "/api/v1/settings/decision-providers",
        headers={"Authorization": f"Bearer {token}"},
        json={
            "order": ["openai", "jev", "clef-backup", "clef-primary"],
            "enabled": ["openai", "jev", "clef-primary"],
            "credentials": {"openai": key},
        },
    )

    assert response.status_code == 200
    assert response.json()["order"] == ["openai", "jev", "clef-backup", "clef-primary"]
    assert key not in response.text
    assert runtime.decision_providers.get_credential("openai", env_default="") == key


def test_non_admin_cannot_read_or_change_provider_settings(tmp_path):
    runtime = _runtime(tmp_path)
    client = _client(runtime)
    token = _login(client, runtime, AccountRole.USER)
    headers = {"Authorization": f"Bearer {token}"}

    response = client.get("/api/v1/settings/decision-providers", headers=headers)
    assert response.status_code == 403


def test_bad_order_and_overlapping_credential_actions_are_rejected(tmp_path):
    runtime = _runtime(tmp_path)
    client = _client(runtime)
    token = _login(client, runtime, AccountRole.ADMIN)
    headers = {"Authorization": f"Bearer {token}"}
    body = {
        "order": ["openai", "jev", "clef-backup", "clef-primary"],
        "enabled": ["openai", "jev"],
        "credentials": {"openai": "key"},
        "clear_credentials": ["openai"],
    }

    response = client.put("/api/v1/settings/decision-providers", headers=headers, json=body)
    assert response.status_code == 422
