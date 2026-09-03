"""Every scenario of the `embed-key-principal` spec.

The embed key is a public identifier, so each gate — origin, allowlist,
project binding, character restriction, rate limit, quota, CORS — is asserted
against a live app rather than against the helpers in isolation.
"""

from __future__ import annotations

import sys
import types
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

API_ROOT = Path(__file__).resolve().parents[1]
if str(API_ROOT) not in sys.path:
    sys.path.insert(0, str(API_ROOT))

from tests.api.test_main import _authenticated_client, _load_main  # noqa: E402

ALLOWED_ORIGIN = "https://partner.example"
OTHER_ORIGIN = "https://evil.example"


def _register_character(runtime, char_id: str) -> None:
    from app.auth.models import ResourceType, ResourceVisibility

    try:
        runtime.resources.register(
            resource_type=ResourceType.AVATAR_CHARACTER,
            resource_id=char_id,
            owner_user_id=None,
            visibility=ResourceVisibility.SYSTEM_PUBLIC,
        )
    except Exception:
        pass


@pytest.fixture
def embed_env(monkeypatch, tmp_path):
    """An app plus one enabled key bound to the `default` project."""
    module, _ = _load_main(monkeypatch)
    # 預設設定會把素材目錄指到 /data，測試環境沒有寫入權限。
    assets_dir = tmp_path / "characters"
    assets_dir.mkdir(parents=True, exist_ok=True)
    base_config = module.get_tts_config()
    monkeypatch.setattr(
        module,
        "get_tts_config",
        lambda: types.SimpleNamespace(
            **{**vars(base_config), "avatar_assets_dir": str(assets_dir)}
        ),
    )

    import app.routes.public_characters as public_characters

    monkeypatch.setattr(
        public_characters,
        "get_tts_config",
        module.get_tts_config,
    )
    public_characters.reset_store()

    # 建立 admin 會順便註冊 default 專案與 hayley 音色資源。
    _authenticated_client(module)

    from app.auth.embed import get_rate_limiter
    from app.auth.runtime import get_auth_runtime

    runtime = get_auth_runtime()
    _register_character(runtime, "aria")
    _register_character(runtime, "secret")
    get_rate_limiter().reset()

    key = runtime.embed_keys.create(
        label="Partner site",
        project_id="default",
        allowed_origins=[ALLOWED_ORIGIN],
        default_character_id="aria",
        default_tts_provider="indextts",
        default_tts_voice="hayley",
    )
    client = TestClient(module.app, raise_server_exceptions=False)
    return module, client, key, runtime


def _headers(key_id: str, origin: str = ALLOWED_ORIGIN) -> dict[str, str]:
    return {"X-Embed-Key": key_id, "Origin": origin}


# --- Requirement: Embed key authenticates as a restricted principal ---------


def test_valid_key_on_allowlisted_route_runs_as_embed_principal(embed_env):
    module, client, key, _runtime = embed_env
    seen: dict[str, object] = {}

    async def _fake_proxy(request, path, *, current, project_id=None):
        from fastapi.responses import JSONResponse

        seen["path"] = path
        seen["account_type"] = current.user.account_type.value
        seen["transport"] = current.transport.value
        seen["project_id"] = request.state.resolved_project_id
        seen["key_id"] = current.embed_key.key_id
        return JSONResponse(content={"reply": "hi"})

    module.brain_proxy_router.routes  # 確保 router 已掛載
    import app.brain_proxy as brain_proxy

    original = brain_proxy.proxy_to_brain
    brain_proxy.proxy_to_brain = _fake_proxy
    try:
        response = client.post(
            "/api/v1/chat",
            json={"message": "hello"},
            headers=_headers(key.key_id),
        )
    finally:
        brain_proxy.proxy_to_brain = original

    assert response.status_code == 200
    assert seen["account_type"] == "embed"
    assert seen["transport"] == "embed_key"
    assert seen["project_id"] == "default"
    assert seen["key_id"] == key.key_id


def test_unknown_key_is_unauthorized(embed_env):
    _module, client, _key, _runtime = embed_env

    response = client.get(
        "/api/v1/characters",
        headers=_headers("ovk_does_not_exist"),
    )

    assert response.status_code == 401


def test_disabled_key_is_unauthorized(embed_env):
    _module, client, key, runtime = embed_env
    runtime.embed_keys.update(key.key_id, disabled=True)

    response = client.get("/api/v1/characters", headers=_headers(key.key_id))

    assert response.status_code == 401


def test_embed_key_takes_precedence_over_a_session_cookie(embed_env):
    module, _client, key, runtime = embed_env
    authenticated, _token = _authenticated_client(module)

    # 帶著有效 cookie 與 bearer，再加上 embed key：主體必須是 embed key。
    response = authenticated.get(
        "/api/v1/users",
        headers=_headers(key.key_id),
    )

    # /api/v1/users 不在允許清單內，403 證明是 embed 主體在被裁決，
    # 而不是 cookie 的 admin 身分（那會回 200）。
    assert response.status_code == 403


# --- Requirement: Route allowlist for embed principals ---------------------


@pytest.mark.parametrize(
    ("method", "path"),
    [
        ("GET", "/api/v1/sessions"),
        ("GET", "/api/v1/knowledge/documents"),
        ("GET", "/api/v1/users"),
        ("GET", "/static/mascots/some-mascot/model.vrm"),
        ("POST", "/api/v1/projects"),
        ("GET", "/api/v1/usage/summary"),
    ],
)
def test_denied_paths_are_forbidden(embed_env, method, path):
    _module, client, key, _runtime = embed_env

    response = client.request(method, path, headers=_headers(key.key_id))

    assert response.status_code == 403


@pytest.mark.parametrize(
    ("method", "path"),
    [
        ("GET", "/api/v1/characters"),
        ("GET", "/api/v1/tts/providers"),
    ],
)
def test_allowlisted_read_paths_reach_their_handler(embed_env, method, path):
    _module, client, key, _runtime = embed_env

    response = client.request(method, path, headers=_headers(key.key_id))

    assert response.status_code == 200


def test_project_override_is_rejected(embed_env):
    _module, client, key, _runtime = embed_env

    response = client.post(
        "/api/v1/chat",
        json={"message": "hello", "project_id": "another-project"},
        headers=_headers(key.key_id),
    )

    assert response.status_code == 403


def test_matching_project_id_is_accepted(embed_env):
    """金鑰自己的 project_id 明寫在 body 裡不算覆寫。"""
    module, client, key, _runtime = embed_env
    import app.brain_proxy as brain_proxy

    async def _fake_proxy(request, path, *, current, project_id=None):
        from fastapi.responses import JSONResponse

        return JSONResponse(content={"reply": "ok"})

    original = brain_proxy.proxy_to_brain
    brain_proxy.proxy_to_brain = _fake_proxy
    try:
        response = client.post(
            "/api/v1/chat",
            json={"message": "hello", "project_id": "default"},
            headers=_headers(key.key_id),
        )
    finally:
        brain_proxy.proxy_to_brain = original

    assert response.status_code == 200


def test_character_restriction_blocks_other_characters(embed_env):
    _module, client, key, _runtime = embed_env

    denied = client.get(
        "/static/characters/secret/01.webm",
        headers=_headers(key.key_id),
    )

    assert denied.status_code == 403


def test_allowed_character_passes_the_middleware_gate(embed_env):
    _module, client, key, _runtime = embed_env

    allowed = client.get(
        "/static/characters/aria/01.webm",
        headers=_headers(key.key_id),
    )

    # 檔案不存在所以是 404；重點是沒有被 403 擋在 middleware。
    assert allowed.status_code == 404


def test_additional_allowed_character_ids_are_honoured(embed_env):
    _module, client, key, runtime = embed_env
    runtime.embed_keys.update(key.key_id, allowed_character_ids=["secret"])

    response = client.get(
        "/static/characters/secret/01.webm",
        headers=_headers(key.key_id),
    )

    assert response.status_code == 404


# --- Requirement: Origin allowlist ----------------------------------------


def test_missing_origin_is_forbidden(embed_env):
    _module, client, key, _runtime = embed_env

    response = client.get(
        "/api/v1/characters",
        headers={"X-Embed-Key": key.key_id},
    )

    assert response.status_code == 403


def test_unlisted_origin_is_forbidden_without_cors_headers(embed_env):
    _module, client, key, _runtime = embed_env

    response = client.get(
        "/api/v1/characters",
        headers=_headers(key.key_id, OTHER_ORIGIN),
    )

    assert response.status_code == 403
    assert "access-control-allow-origin" not in response.headers


# --- Requirement: Rate limit and daily quota ------------------------------


def test_per_minute_limit_returns_429_with_retry_after(embed_env):
    _module, client, key, runtime = embed_env
    runtime.embed_keys.update(key.key_id, rate_limit_per_minute=2)

    first = client.get("/api/v1/characters", headers=_headers(key.key_id))
    second = client.get("/api/v1/characters", headers=_headers(key.key_id))
    third = client.get("/api/v1/characters", headers=_headers(key.key_id))

    assert first.status_code == 200
    assert second.status_code == 200
    assert third.status_code == 429
    assert int(third.headers["Retry-After"]) >= 1


def test_daily_quota_returns_429_and_still_touches_last_used(embed_env):
    _module, client, key, runtime = embed_env
    runtime.embed_keys.update(key.key_id, daily_request_quota=1)

    first = client.get("/api/v1/characters", headers=_headers(key.key_id))
    second = client.get("/api/v1/characters", headers=_headers(key.key_id))

    assert first.status_code == 200
    assert second.status_code == 429
    assert int(second.headers["Retry-After"]) >= 1
    assert runtime.embed_keys.get(key.key_id).last_used_at is not None
    assert runtime.embed_keys.requests_today(key.key_id) == 2


# --- Requirement: CORS only for embed principals --------------------------


def test_preflight_returns_204_with_cors_headers(embed_env):
    _module, client, _key, _runtime = embed_env

    # 瀏覽器的 preflight 不帶自訂標頭，只能靠 Origin 對照金鑰白名單
    response = client.options(
        "/api/v1/chat",
        headers={
            "Origin": ALLOWED_ORIGIN,
            "Access-Control-Request-Method": "POST",
            "Access-Control-Request-Headers": "x-embed-key",
        },
    )

    assert response.status_code == 204
    assert response.headers["Access-Control-Allow-Origin"] == ALLOWED_ORIGIN
    assert response.headers["Vary"] == "Origin"
    assert "X-Embed-Key" in response.headers["Access-Control-Allow-Headers"]
    assert "POST" in response.headers["Access-Control-Allow-Methods"]
    assert "access-control-allow-credentials" not in response.headers


def test_preflight_on_a_denied_path_is_forbidden(embed_env):
    _module, client, key, _runtime = embed_env

    response = client.options(
        "/api/v1/users",
        headers={
            "X-Embed-Key": key.key_id,
            "Origin": ALLOWED_ORIGIN,
            "Access-Control-Request-Method": "GET",
        },
    )

    assert response.status_code == 403


def test_preflight_from_unlisted_origin_gets_no_cors(embed_env):
    _module, client, _key, _runtime = embed_env

    response = client.options(
        "/api/v1/chat",
        headers={
            "Origin": "https://evil.example",
            "Access-Control-Request-Method": "POST",
            "Access-Control-Request-Headers": "x-embed-key",
        },
    )

    assert response.status_code != 204
    assert "access-control-allow-origin" not in response.headers


def test_preflight_on_a_non_allowlisted_path_is_not_cors_approved(embed_env):
    _module, client, _key, _runtime = embed_env

    response = client.options(
        "/api/v1/users",
        headers={"Origin": ALLOWED_ORIGIN, "Access-Control-Request-Method": "GET"},
    )

    assert "access-control-allow-origin" not in response.headers


def test_embed_errors_carry_cors_headers_for_allowed_origins(embed_env):
    _module, client, key, runtime = embed_env
    runtime.embed_keys.update(key.key_id, rate_limit_per_minute=1)

    client.get("/api/v1/characters", headers=_headers(key.key_id))
    limited = client.get("/api/v1/characters", headers=_headers(key.key_id))
    assert limited.status_code == 429
    assert limited.headers["Access-Control-Allow-Origin"] == ALLOWED_ORIGIN

    runtime.embed_keys.update(key.key_id, disabled=True)
    disabled = client.get("/api/v1/characters", headers=_headers(key.key_id))
    assert disabled.status_code == 401
    assert disabled.headers["Access-Control-Allow-Origin"] == ALLOWED_ORIGIN

    unknown = client.get("/api/v1/characters", headers=_headers("ovk_unknown"))
    assert unknown.status_code == 401
    assert unknown.headers["Access-Control-Allow-Origin"] == ALLOWED_ORIGIN


def test_embed_response_carries_cors_headers(embed_env):
    _module, client, key, _runtime = embed_env

    response = client.get("/api/v1/characters", headers=_headers(key.key_id))

    assert response.status_code == 200
    assert response.headers["Access-Control-Allow-Origin"] == ALLOWED_ORIGIN


def test_session_request_gets_no_cors_headers(embed_env):
    module, _client, _key, _runtime = embed_env
    authenticated, _token = _authenticated_client(module)

    response = authenticated.get(
        "/api/v1/characters",
        headers={"Origin": OTHER_ORIGIN},
    )

    assert "access-control-allow-origin" not in response.headers


# --- Requirement: Usage attribution for embed keys ------------------------


def test_trusted_upstream_headers_carry_the_principal(embed_env):
    _module, _client, key, _runtime = embed_env

    from app.auth.dependencies import AuthTransport, CurrentAccount
    from app.auth.embed import embed_user_record
    from app.brain_proxy import _trusted_upstream_headers

    class _Request:
        headers = {"content-type": "application/json"}
        state = type("S", (), {})()

    current = CurrentAccount(
        user=embed_user_record(key),
        transport=AuthTransport.EMBED_KEY,
        embed_key=key,
    )
    headers = _trusted_upstream_headers(
        _Request(),
        current=current,
        project_id="default",
    )

    assert headers["X-Principal-Type"] == "embed_key"
    assert headers["X-Principal-Id"] == key.key_id
    assert headers["X-OpenVMan-Project-ID"] == "default"


def test_client_supplied_principal_headers_are_stripped(embed_env):
    _module, _client, key, _runtime = embed_env

    from app.auth.dependencies import AuthTransport, CurrentAccount
    from app.auth.embed import embed_user_record
    from app.brain_proxy import _trusted_upstream_headers

    class _Request:
        headers = {
            "x-principal-type": "user",
            "x-principal-id": "root",
            "content-type": "application/json",
        }
        state = type("S", (), {})()

    current = CurrentAccount(
        user=embed_user_record(key),
        transport=AuthTransport.EMBED_KEY,
        embed_key=key,
    )
    headers = _trusted_upstream_headers(_Request(), current=current, project_id="default")

    assert headers["X-Principal-Type"] == "embed_key"
    assert headers["X-Principal-Id"] == key.key_id


def test_session_principal_headers_identify_the_account(embed_env):
    module, _client, _key, _runtime = embed_env
    _authenticated_client(module)

    from app.auth.dependencies import AuthTransport, CurrentAccount
    from app.auth.runtime import get_auth_runtime
    from app.brain_proxy import _trusted_upstream_headers

    user = get_auth_runtime().users.get_by_username("test-admin")

    class _Request:
        headers = {"content-type": "application/json"}
        state = type("S", (), {})()

    current = CurrentAccount(user=user, transport=AuthTransport.COOKIE)
    headers = _trusted_upstream_headers(_Request(), current=current, project_id="default")

    assert headers["X-Principal-Type"] == "user"
    assert headers["X-Principal-Id"] == user.id
