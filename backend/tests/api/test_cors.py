"""Third-party browser frontends may call the API; we record which site used which key."""

from __future__ import annotations

import sys
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from tests.api.test_main import _authenticated_client, _load_main  # noqa: E402

PARTNER = "https://partner.example"
EMBED_SITE = "https://embed-only.example"


def _set_origins(runtime, value: str) -> None:
    # 設定與 runtime 都是凍結的；測試直接換一份設定，結束時由 fixture 還原。
    object.__setattr__(
        runtime, "config", runtime.config.model_copy(update={"cors_allowed_origins": value}),
    )


@pytest.fixture
def cors_env(monkeypatch):
    module, _ = _load_main(monkeypatch)
    _authenticated_client(module, admin=False)
    from app.auth.runtime import get_auth_runtime

    runtime = get_auth_runtime()
    original = runtime.config
    _set_origins(runtime, PARTNER)
    user = runtime.users.get_by_username("test-user")
    record, secret = runtime.api_keys.create(actor_id=user.id, user_id=user.id, label="partner")
    client = TestClient(module.app, raise_server_exceptions=False)
    yield client, runtime, record, secret
    object.__setattr__(runtime, "config", original)


def _preflight(client: TestClient, origin: str, headers: str = "authorization,content-type"):
    return client.options(
        "/api/v1/projects",
        headers={
            "Origin": origin,
            "Access-Control-Request-Method": "GET",
            "Access-Control-Request-Headers": headers,
        },
    )


def test_listed_site_passes_preflight_without_a_key(cors_env) -> None:
    # 預檢請求不帶金鑰；2026-10-14 正式機在這裡回 401，外部前端整個打不進來。
    client, *_ = cors_env
    response = _preflight(client, PARTNER)
    assert response.status_code == 204
    assert response.headers["Access-Control-Allow-Origin"] == PARTNER
    assert "Authorization" in response.headers["Access-Control-Allow-Headers"]
    assert "access-control-allow-credentials" not in response.headers


def test_unlisted_site_gets_no_cors(cors_env) -> None:
    client, *_ = cors_env
    assert "access-control-allow-origin" not in _preflight(client, "https://evil.example").headers


def test_wildcard_allows_any_site(cors_env) -> None:
    client, runtime, *_ = cors_env
    _set_origins(runtime, "*")
    response = _preflight(client, "https://anyone.example")
    assert response.headers["Access-Control-Allow-Origin"] == "https://anyone.example"


def test_embed_key_sites_still_work_when_not_in_the_list(cors_env) -> None:
    # 部署清單只管 API key；Embed key 自己的網域白名單不能被它擋掉。
    client, runtime, *_ = cors_env
    runtime.embed_keys.create(
        label="Embed", project_id="default", allowed_origins=[EMBED_SITE],
        default_tts_provider="indextts", default_tts_voice="hayley",
    )
    response = client.options(
        "/api/v1/chat",
        headers={
            "Origin": EMBED_SITE,
            "Access-Control-Request-Method": "POST",
            "Access-Control-Request-Headers": "x-embed-key",
        },
    )
    assert response.status_code == 204
    assert response.headers["Access-Control-Allow-Origin"] == EMBED_SITE


def test_api_key_response_and_errors_are_readable_cross_origin(cors_env) -> None:
    client, _runtime, _record, secret = cors_env
    ok = client.get("/api/v1/auth/me", headers={"Origin": PARTNER, "Authorization": f"Bearer {secret}"})
    assert ok.status_code == 200
    assert ok.headers["Access-Control-Allow-Origin"] == PARTNER
    assert "X-TTS-Provider" in ok.headers["Access-Control-Expose-Headers"]
    # 金鑰錯也要帶 CORS，前端才讀得到 401 而不是一個看不出原因的網路錯誤。
    bad = client.get("/api/v1/auth/me", headers={"Origin": PARTNER, "Authorization": "Bearer ovk_wrong"})
    assert bad.status_code == 401
    assert bad.headers["Access-Control-Allow-Origin"] == PARTNER


def test_external_site_is_recorded_with_the_key_that_called(cors_env) -> None:
    client, runtime, record, secret = cors_env
    for _ in range(2):
        client.get("/api/v1/auth/me", headers={"Origin": PARTNER + "/", "Authorization": f"Bearer {secret}"})
    _preflight(client, PARTNER)  # 預檢不算一次
    rows = [r for r in runtime.request_origins.list_recent() if r.origin == PARTNER]
    assert len(rows) == 1
    assert rows[0].principal_type == "api_key"
    assert rows[0].principal_id == record.key_id
    assert rows[0].request_count == 2
    assert rows[0].last_path == "/api/v1/auth/me"


def test_own_site_and_server_calls_are_not_recorded(cors_env) -> None:
    client, runtime, _record, secret = cors_env
    client.get("/api/v1/auth/me", headers={"Origin": "http://testserver", "Authorization": f"Bearer {secret}"})
    client.get("/api/v1/auth/me", headers={"Authorization": f"Bearer {secret}"})
    assert runtime.request_origins.list_recent() == []


def test_unauthenticated_calls_are_recorded_as_anonymous(cors_env) -> None:
    client, runtime, *_ = cors_env
    client.get("/api/v1/auth/me", headers={"Origin": "https://scanner.example"})
    rows = runtime.request_origins.list_recent()
    assert rows[0].origin == "https://scanner.example"
    assert rows[0].principal_type == "anonymous"


def test_only_root_can_read_the_origin_record(cors_env) -> None:
    client, _runtime, _record, secret = cors_env
    response = client.get("/api/v1/admin/request-origins", headers={"Authorization": f"Bearer {secret}"})
    assert response.status_code == 403


def test_api_key_rate_limit_returns_429_readable_cross_origin(cors_env) -> None:
    from app.auth.attempt_limiter import FailedAttemptLimiter

    client, runtime, _record, secret = cors_env
    original = runtime.api_key_requests
    object.__setattr__(runtime, "api_key_requests", FailedAttemptLimiter(max_failures=2, window_seconds=60))
    try:
        headers = {"Origin": PARTNER, "Authorization": f"Bearer {secret}"}
        statuses = [client.get("/api/v1/auth/me", headers=headers).status_code for _ in range(3)]
        limited = client.get("/api/v1/auth/me", headers=headers)
    finally:
        object.__setattr__(runtime, "api_key_requests", original)

    assert statuses == [200, 200, 429]
    assert int(limited.headers["Retry-After"]) >= 1
    assert limited.headers["Access-Control-Allow-Origin"] == PARTNER


def test_rate_limit_is_on_by_default() -> None:
    from app.config import TTSRouterConfig

    assert TTSRouterConfig.model_fields["api_key_rate_limit_per_minute"].default == 300
