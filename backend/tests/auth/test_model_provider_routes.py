from __future__ import annotations

import hashlib

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.auth import model_provider_routes
from app.auth.model_provider_routes import internal_runtime_configuration, router
from app.auth.models import AccountRole
from app.auth.passwords import hash_password
from app.auth.routes import auth_router
from app.auth.runtime import AuthRuntime, build_auth_runtime, get_auth_runtime
from app.config import TTSRouterConfig

PATH = "/api/v1/settings/model-providers"
DECISION_ORDER = ["clef-primary", "clef-backup", "jev", "openai"]


@pytest.fixture(autouse=True)
def brain_health(monkeypatch):
    """Brain 不在測試環境裡；預設回「沒有失敗紀錄」，個別測試再換。"""
    hops: list[dict] = []
    monkeypatch.setattr(model_provider_routes, "_brain_provider_health", lambda _runtime: hops)
    return hops


def _runtime(tmp_path, **overrides) -> AuthRuntime:
    return build_auth_runtime(TTSRouterConfig(
        _env_file=None,
        env="dev",
        session_jwt_secret="test-only-session-secret-for-tests-32",
        model_provider_encryption_secret="provider-encryption-secret-for-test-32-bytes",
        auth_database_path=str(tmp_path / "accounts.db"),
        typesafe_api_key="env-jev-key",
        openai_api_key="env-openai-key",
        gemini_api_key="env-gemini-key",
        llm_fallback_chain="gemini:gemini-3.5-flash-lite,openai:gpt-4.1-mini",
        nen_base_url="https://nen.example/v1",
        **overrides,
    ))


def _client(runtime: AuthRuntime) -> TestClient:
    app = FastAPI()
    app.include_router(auth_router)
    app.include_router(router)
    app.dependency_overrides[get_auth_runtime] = lambda: runtime
    return TestClient(app)


def _login(client: TestClient, runtime: AuthRuntime, role: AccountRole) -> dict[str, str]:
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
    return {"Authorization": f"Bearer {response.json()['token']}"}


def _category(payload: dict, category_id: str) -> dict:
    return next(item for item in payload["categories"] if item["id"] == category_id)


def _save_body(**chat_overrides) -> dict:
    chat = {
        "order": ["gemini", "openai", "groq", "nen"],
        "enabled": ["gemini", "openai"],
        "models": {},
    }
    chat.update(chat_overrides)
    return {"categories": {
        "decision": {"order": DECISION_ORDER, "enabled": DECISION_ORDER},
        "chat_llm": chat,
    }}


def test_root_reads_deployment_defaults_and_only_credential_metadata(tmp_path):
    runtime = _runtime(tmp_path)
    client = _client(runtime)
    headers = _login(client, runtime, AccountRole.ROOT)

    response = client.get(PATH, headers=headers)

    assert response.status_code == 200
    payload = response.json()
    decision = _category(payload, "decision")
    chat = _category(payload, "chat_llm")
    assert decision["order"] == DECISION_ORDER
    assert decision["configured"] is False
    # 主對話預設順序與模型來自 LLM_FALLBACK_CHAIN，沒列在鏈上的供應商預設停用。
    assert chat["order"] == ["gemini", "openai", "groq", "nen"]
    assert chat["enabled"] == ["gemini", "openai"]
    assert chat["providers"][3]["endpoint"] == "https://nen.example/v1"
    openai = next(item for item in payload["credentials"] if item["id"] == "openai")
    assert openai["used_by"] == ["決策模型", "主對話模型"]
    assert openai["source"] == "environment"
    assert openai["masked"] == "••••-key"
    assert "env-openai-key" not in response.text


def test_root_saves_order_models_and_shared_key_without_echoing_it(tmp_path):
    runtime = _runtime(tmp_path)
    client = _client(runtime)
    headers = _login(client, runtime, AccountRole.ROOT)
    key = "new-openai-provider-key"
    body = _save_body(
        order=["openai", "gemini", "groq", "nen"],
        models={"openai": "gpt-4.1", "gemini": "  "},
    )
    body["credentials"] = {"openai": key}

    response = client.put(PATH, headers=headers, json=body)

    assert response.status_code == 200
    assert key not in response.text
    chat = _category(response.json(), "chat_llm")
    assert chat["configured"] is True
    assert chat["order"][0] == "openai"
    assert chat["providers"][0]["model"] == "gpt-4.1"
    # 空白模型名稱＝沿用部署預設，不另存。
    assert chat["providers"][1]["model_override"] == ""
    assert chat["providers"][1]["model"] == "gemini-3.5-flash-lite"
    runtime_view = internal_runtime_configuration(runtime)
    assert runtime_view["chat_llm"]["order"] == ["openai", "gemini"]
    assert runtime_view["chat_llm"]["providers"][0]["api_key"] == key
    assert runtime_view["chat_llm"]["providers"][0]["credential_source"] == "admin"
    assert runtime_view["chat_llm"]["providers"][1]["api_key"] == "env-gemini-key"
    # 同一把 OpenAI 金鑰也給決策用。
    decision_openai = runtime_view["decision"]["providers"][-1]
    assert decision_openai["id"] == "openai" and decision_openai["api_key"] == key


def test_chat_llm_runtime_stays_on_brain_environment_until_saved(tmp_path):
    runtime = _runtime(tmp_path)

    assert internal_runtime_configuration(runtime)["chat_llm"] == {
        "configured": False, "credential_overrides": {},
    }


def test_admin_and_user_cannot_read_or_change_provider_settings(tmp_path):
    runtime = _runtime(tmp_path)
    client = _client(runtime)
    for role in (AccountRole.ADMIN, AccountRole.USER):
        headers = _login(client, runtime, role)
        assert client.get(PATH, headers=headers).status_code == 403
        assert client.put(PATH, headers=headers, json=_save_body()).status_code == 403


def test_saving_only_decisions_leaves_chat_on_env_but_shares_the_new_key(tmp_path):
    runtime = _runtime(tmp_path)
    client = _client(runtime)
    headers = _login(client, runtime, AccountRole.ROOT)
    body = {
        "categories": {"decision": {"order": DECISION_ORDER[::-1], "enabled": DECISION_ORDER}},
        "credentials": {"openai": "admin-openai"},
    }

    response = client.put(PATH, headers=headers, json=body)

    assert response.status_code == 200
    assert _category(response.json(), "decision")["configured"] is True
    assert _category(response.json(), "chat_llm")["configured"] is False
    assert internal_runtime_configuration(runtime)["chat_llm"] == {
        "configured": False, "credential_overrides": {"openai": "admin-openai"},
    }


def test_reset_category_returns_it_to_deployment_settings(tmp_path):
    runtime = _runtime(tmp_path)
    client = _client(runtime)
    headers = _login(client, runtime, AccountRole.ROOT)
    assert client.put(PATH, headers=headers, json=_save_body()).status_code == 200

    response = client.put(PATH, headers=headers, json={"reset_categories": ["chat_llm"]})

    assert response.status_code == 200
    assert _category(response.json(), "chat_llm")["configured"] is False
    assert _category(response.json(), "decision")["configured"] is True
    assert internal_runtime_configuration(runtime)["chat_llm"]["configured"] is False


def test_bad_categories_and_conflicting_actions_are_rejected(tmp_path):
    runtime = _runtime(tmp_path)
    client = _client(runtime)
    headers = _login(client, runtime, AccountRole.ROOT)
    conflicting = _save_body()
    conflicting["credentials"] = {"openai": "key"}
    conflicting["clear_credentials"] = ["openai"]
    save_and_reset = _save_body()
    save_and_reset["reset_categories"] = ["chat_llm"]

    assert client.put(PATH, headers=headers, json=conflicting).status_code == 422
    assert client.put(PATH, headers=headers, json=save_and_reset).status_code == 422
    assert client.put(PATH, headers=headers, json={"reset_categories": ["vision"]}).status_code == 422
    assert client.put(
        PATH, headers=headers, json=_save_body(order=["gemini", "gemini", "groq", "nen"]),
    ).status_code == 422


def test_hop_shows_brain_circuit_state_only_for_the_key_in_use(tmp_path, brain_health):
    runtime = _runtime(tmp_path)
    client = _client(runtime)
    headers = _login(client, runtime, AccountRole.ROOT)
    fingerprint = hashlib.sha256(b"env-gemini-key").hexdigest()[:12]
    brain_health.extend([
        {"category": "chat_llm", "hop": "gemini", "model": "gemini-3.5-flash-lite",
         "key_fingerprint": fingerprint, "status": "blocked", "reason": "auth_invalid",
         "retry_in_seconds": None},
        # 舊 key 的失敗紀錄，換 key 後不該再顯示。
        {"category": "chat_llm", "hop": "openai", "model": "gpt-4.1-mini",
         "key_fingerprint": "000000000000", "status": "blocked", "reason": "auth_invalid",
         "retry_in_seconds": None},
    ])

    chat = _category(client.get(PATH, headers=headers).json(), "chat_llm")

    by_id = {provider["id"]: provider["health"] for provider in chat["providers"]}
    assert by_id["gemini"] == {"status": "blocked", "reason": "auth_invalid", "retry_in_seconds": None}
    assert by_id["openai"] == {"status": "ok"}


def test_settings_page_still_loads_when_brain_cannot_report_health(tmp_path, monkeypatch):
    monkeypatch.setattr(model_provider_routes, "_brain_provider_health", lambda _runtime: None)
    runtime = _runtime(tmp_path)
    client = _client(runtime)
    headers = _login(client, runtime, AccountRole.ROOT)

    response = client.get(PATH, headers=headers)

    assert response.status_code == 200
    assert _category(response.json(), "decision")["providers"][0]["health"] == {"status": "unknown"}
