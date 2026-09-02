"""Tests for the FastAPI entrypoint."""

from __future__ import annotations

import asyncio
import importlib
import json
import sys
import types
import warnings
from pathlib import Path
from unittest.mock import AsyncMock

from fastapi.testclient import TestClient
from starlette.requests import Request

API_ROOT = Path(__file__).resolve().parents[1]
if str(API_ROOT) not in sys.path:
    sys.path.insert(0, str(API_ROOT))


def _make_test_config(*, max_upload_bytes: int = 1024, **overrides):
    base = {
        "document_max_upload_bytes": max_upload_bytes,
        "gateway_internal_token": "test-internal-token",
        "brain_url": "http://brain:8100",
        "tts_indextts_url": "http://index-tts-vllm:8011",
        "tts_indextts_default_character": "hayley",
        "tts_gcp_enabled": False,
        "tts_aws_enabled": False,
        "tts_gemini_url": "",
        "normalize_api_url": "",
        "edge_tts_enabled": True,
        "edge_tts_voice": "zh-TW-HsiaoChenNeural",
        "is_dev": False,
        "backend_port": 8000,
        "tts_cache_enabled": False,
        "tts_cache_ttl_seconds": 86400,
    }
    base.update(overrides)
    return types.SimpleNamespace(**base)


def _load_main(monkeypatch, *, max_upload_bytes: int = 1024):
    fake_anydoc_mod = types.ModuleType("anydoc")
    fake_anydoc_mod.convert_paths = []

    def _to_markdown(path: str) -> str:
        fake_anydoc_mod.convert_paths.append(path)
        return "converted markdown"

    fake_anydoc_mod.to_markdown = _to_markdown
    monkeypatch.setitem(sys.modules, "anydoc", fake_anydoc_mod)

    # Re-import app.main from scratch so the fake anydoc / config patches take.
    # Use monkeypatch.delitem so the original module objects (or their absence) are
    # restored on teardown — otherwise the freshly re-imported modules leak into
    # later tests and break patch("app.routes.admin...") targeting.
    for name in ("app.gateway.websocket", "app.routes.admin", "app.main"):
        monkeypatch.delitem(sys.modules, name, raising=False)
    module = importlib.import_module("app.main")
    _cfg = lambda: _make_test_config(max_upload_bytes=max_upload_bytes)
    monkeypatch.setattr(module, "get_tts_config", _cfg)

    # tts_text 綁定了自己的 get_tts_config，且會回退讀 NORMALIZE_API_URL。
    # 兩條路都要擋，否則正規化會另開一個 httpx client 干擾測試斷言。
    import app.tts_text
    monkeypatch.setattr(app.tts_text, "get_tts_config", _cfg)
    monkeypatch.delenv("NORMALIZE_API_URL", raising=False)

    return module, fake_anydoc_mod


def _authenticated_client(module, *, admin: bool = True) -> tuple[TestClient, str]:
    from app.auth.models import AccountRole, ResourceType, ResourceVisibility
    from app.auth.passwords import hash_password
    from app.auth.runtime import get_auth_runtime

    runtime = get_auth_runtime()
    username = "test-admin" if admin else "test-user"
    user = runtime.users.get_by_username(username)
    if not user:
        user = runtime.users.create(
            username=username,
            password_hash=hash_password("admin-password"),
            role=AccountRole.ADMIN if admin else AccountRole.USER,
        )
    try:
        runtime.resources.register(
            resource_type=ResourceType.CUSTOM_VOICE,
            resource_id="hayley",
            owner_user_id=None,
            visibility=ResourceVisibility.SYSTEM_PUBLIC,
            metadata={"provider": "indextts"},
        )
    except Exception:
        pass
    try:
        runtime.resources.register(
            resource_type=ResourceType.PROJECT,
            resource_id="default",
            owner_user_id=user.id,
            visibility=ResourceVisibility.PRIVATE,
        )
    except Exception:
        pass
    token = runtime.tokens.issue(user)
    client = TestClient(module.app, raise_server_exceptions=False)
    client.cookies.set("openvman_session", token)
    client.headers["Authorization"] = f"Bearer {token}"
    client.headers["Origin"] = "http://testserver"
    return client, token


def _get_tts_provider_payload(module) -> list[dict]:
    from app.auth.dependencies import AuthTransport, CurrentAccount
    from app.auth.models import AccountRole
    from app.auth.passwords import hash_password
    from app.auth.runtime import get_auth_runtime

    runtime = get_auth_runtime()
    admin = runtime.users.get_by_username("test-admin")
    if not admin:
        admin = runtime.users.create(
            username="test-admin",
            password_hash=hash_password("admin-password"),
            role=AccountRole.ADMIN,
        )
    current = CurrentAccount(user=admin, transport=AuthTransport.BEARER)
    response = asyncio.run(module.admin_routes.get_tts_providers(current=current, runtime=runtime))
    assert response.status_code == 200
    return json.loads(response.body)


def test_app_import_avoids_on_event_deprecation(monkeypatch):
    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        _load_main(monkeypatch, max_upload_bytes=1024)

    deprecations = [
        str(item.message)
        for item in caught
        if issubclass(item.category, DeprecationWarning) and "on_event is deprecated" in str(item.message)
    ]

    assert deprecations == []


def test_run_server_uses_configured_dev_mode(monkeypatch):
    module, _ = _load_main(monkeypatch, max_upload_bytes=1024)
    fake_cfg = types.SimpleNamespace(backend_port=9999, is_dev=True)
    captured: dict[str, object] = {}

    def _fake_run(*args, **kwargs):
        captured["args"] = args
        captured["kwargs"] = kwargs

    monkeypatch.setitem(sys.modules, "uvicorn", types.SimpleNamespace(run=_fake_run))
    monkeypatch.setattr(module, "get_tts_config", lambda: fake_cfg)

    module.run_server()

    assert captured["args"] == ("app.main:app",)
    assert captured["kwargs"] == {
        "host": "0.0.0.0",
        "port": 9999,
        "reload": True,
        "log_config": module._UVICORN_LOG_CONFIG,
    }


def test_convert_rejects_oversized_upload(monkeypatch):
    module, fake_anydoc = _load_main(monkeypatch, max_upload_bytes=4)
    client, _ = _authenticated_client(module)

    response = client.post(
        "/documents/convert",
        files={"file": ("note.txt", b"abcdef", "text/plain")},
    )

    assert response.status_code == 413
    assert response.json()["error_code"] == "UPLOAD_FAILED"
    assert fake_anydoc.convert_paths == []


def test_convert_returns_upload_failed_code_when_conversion_crashes(monkeypatch):
    module, fake_anydoc = _load_main(monkeypatch, max_upload_bytes=1024)
    client, _ = _authenticated_client(module)

    def _raise_conversion_error(_path: str) -> str:
        raise RuntimeError("boom")

    fake_anydoc.to_markdown = _raise_conversion_error

    response = client.post(
        "/documents/convert",
        files={"file": ("data.csv", b"name\nhello\n", "text/csv")},
    )

    assert response.status_code == 500
    assert response.json()["error"] == "boom"
    assert response.json()["error_code"] == "UPLOAD_FAILED"
    assert response.json()["message"] == "檔案上傳失敗"


def test_convert_uses_anydoc_for_each_upload(monkeypatch):
    module, fake_anydoc = _load_main(monkeypatch, max_upload_bytes=1024)
    client, _ = _authenticated_client(module)

    first = client.post(
        "/documents/convert",
        files={"file": ("first.csv", b"name\nhello\n", "text/csv")},
    )
    second = client.post(
        "/documents/convert",
        files={"file": ("second.csv", b"name\nworld\n", "text/csv")},
    )

    assert first.status_code == 200
    assert second.status_code == 200
    assert first.json()["markdown"] == "converted markdown"
    assert second.json()["markdown"] == "converted markdown"
    assert len(fake_anydoc.convert_paths) == 2


def test_convert_preserves_plaintext_without_anydoc(monkeypatch):
    module, fake_anydoc = _load_main(monkeypatch, max_upload_bytes=1024)
    client, _ = _authenticated_client(module)

    response = client.post(
        "/documents/convert",
        files={"file": ("note.txt", b"plain text", "text/plain")},
    )

    assert response.status_code == 200
    assert response.json()["markdown"] == "plain text"
    assert fake_anydoc.convert_paths == []


def test_openapi_merges_brain_request_schema(monkeypatch):
    import asyncio

    module, _ = _load_main(monkeypatch, max_upload_bytes=1024)
    module.app.openapi_schema = None
    module._openapi_built = False

    async def _fake_fetch():
        return {
            "paths": {
                "/brain/chat": {
                    "post": {
                        "tags": ["Chat"],
                        "summary": "Chat",
                        "requestBody": {
                            "required": True,
                            "content": {
                                "application/json": {
                                    "schema": {"$ref": "#/components/schemas/ChatRequest"}
                                }
                            },
                        },
                        "responses": {"200": {"description": "Successful Response"}},
                    }
                }
            },
            "components": {
                "schemas": {
                    "ChatRequest": {
                        "title": "ChatRequest",
                        "type": "object",
                        "properties": {"message": {"type": "string"}},
                        "required": ["message"],
                    }
                }
            },
            "tags": [{"name": "Chat", "description": "Chat endpoints."}],
        }

    monkeypatch.setattr(module, "_fetch_brain_openapi", _fake_fetch)
    schema = asyncio.run(module._build_openapi_schema())

    operation = schema["paths"]["/api/chat"]["post"]
    assert operation["requestBody"]["required"] is True
    assert operation["requestBody"]["content"]["application/json"]["schema"] == {
        "$ref": "#/components/schemas/ChatRequest"
    }


def test_openapi_keeps_local_route_when_brain_remap_collides(monkeypatch):
    module, _ = _load_main(monkeypatch, max_upload_bytes=1024)
    local_schema = {
        "paths": {
            "/api/knowledge/upload": {
                "post": {
                    "summary": "Backend knowledge upload",
                    "description": "AnyDoc fallback",
                }
            }
        }
    }
    brain_schema = {
        "paths": {
            "/brain/knowledge/upload": {
                "post": {"summary": "Brain knowledge upload"}
            }
        }
    }

    schema = module._merge_brain_openapi(local_schema, brain_schema)

    operation = schema["paths"]["/api/knowledge/upload"]["post"]
    assert operation["summary"] == "Backend knowledge upload"
    assert operation["description"] == "AnyDoc fallback"


def test_tts_providers_include_indextts_when_configured(monkeypatch):
    module, _ = _load_main(monkeypatch, max_upload_bytes=1024)

    class FakeResponse:
        def raise_for_status(self) -> None:
            return None

        def json(self) -> dict[str, list[str]]:
            return {
                "jay": ["assets/jay_promptvn.wav"],
                "hayley": ["assets/tts_references/Hayley.wav"],
            }

    class FakeClient:
        async def get(self, url: str, timeout=None, headers=None, follow_redirects=None):
            assert url == "http://index-tts-vllm:8011/audio/voices"
            assert headers == {"X-Internal-Token": "test-internal-token"}
            return FakeResponse()

    async def _fake_close() -> None:
        return None

    module.admin_routes._health_http = types.SimpleNamespace(
        get=lambda: FakeClient(),
        close=_fake_close,
    )
    monkeypatch.setattr(module.admin_routes, "get_tts_config", lambda: types.SimpleNamespace(
        document_max_upload_bytes=1024,
        tts_indextts_url="http://index-tts-vllm:8011",
        tts_indextts_default_character="hayley",
        gateway_internal_token="test-internal-token",
        tts_gcp_enabled=False,
        tts_aws_enabled=False,
        tts_gemini_url="",
        tts_voxcpm_url="",
        edge_tts_enabled=True,
        edge_tts_voice="zh-TW-HsiaoChenNeural",
    ))

    assert _get_tts_provider_payload(module) == [
        {"id": "auto", "name": "自動", "default_voice": "", "voices": []},
        {
            "id": "indextts",
            "name": "IndexTTS",
            "default_voice": "hayley",
            "voices": ["jay", "hayley"],
        },
        {
            "id": "edge-tts",
            "name": "Edge TTS",
            "default_voice": "zh-TW-HsiaoChenNeural",
            "voices": ["zh-TW-HsiaoChenNeural", "zh-TW-YunJheNeural", "zh-CN-XiaoyiNeural"],
        },
    ]


def test_tts_providers_excludes_indextts_when_unreachable(monkeypatch):
    """IndexTTS 不可達（抓不到 voices）時，provider list 不應顯示 indextts。"""
    module, _ = _load_main(monkeypatch, max_upload_bytes=1024)

    class FakeClient:
        async def get(self, url: str, timeout=None, headers=None, follow_redirects=None):
            raise ConnectionError("index-tts-vllm unreachable")

    async def _fake_close() -> None:
        return None

    module.admin_routes._health_http = types.SimpleNamespace(
        get=lambda: FakeClient(),
        close=_fake_close,
    )
    monkeypatch.setattr(module.admin_routes, "get_tts_config", lambda: types.SimpleNamespace(
        document_max_upload_bytes=1024,
        tts_indextts_url="http://index-tts-vllm:8011",
        tts_indextts_default_character="hayley",
        gateway_internal_token="test-internal-token",
        tts_gcp_enabled=False,
        tts_aws_enabled=False,
        tts_gemini_url="",
        tts_voxcpm_url="",
        edge_tts_enabled=True,
        edge_tts_voice="zh-TW-HsiaoChenNeural",
    ))

    ids = [p["id"] for p in _get_tts_provider_payload(module)]
    assert "indextts" not in ids
    assert ids == ["auto", "edge-tts"]


def test_tts_providers_includes_gemini_when_configured(monkeypatch):
    module, _ = _load_main(monkeypatch, max_upload_bytes=1024)

    class FakeClient:
        def get(self):
            class FakeAsyncClient:
                async def get(self, url: str, timeout=None, follow_redirects=None):
                    class FakeResponse:
                        def raise_for_status(self):
                            pass

                        def json(self):
                            return {"voices": [{"name": "Zephyr"}, {"name": "Kore"}]}

                    return FakeResponse()

            return FakeAsyncClient()

        async def close(self):
            pass

    module.admin_routes._health_http = FakeClient()
    monkeypatch.setattr(module.admin_routes, "get_tts_config", lambda: types.SimpleNamespace(
        document_max_upload_bytes=1024,
        tts_indextts_url="",
        tts_gcp_enabled=False,
        tts_aws_enabled=False,
        tts_gemini_url="http://nurse.5gao.ai:8206",
        tts_voxcpm_url="",
        edge_tts_enabled=False,
    ))

    assert _get_tts_provider_payload(module) == [
        {"id": "auto", "name": "自動", "default_voice": "", "voices": []},
        {
            "id": "gemini-tts",
            "name": "Gemini TTS",
            "default_voice": "Kore",
            "voices": ["Zephyr", "Kore"],
        },
    ]


def test_create_speech_uses_backend_tts_cache_when_hit(monkeypatch):
    module, _ = _load_main(monkeypatch, max_upload_bytes=1024)
    monkeypatch.setattr(module, "get_tts_config", lambda: types.SimpleNamespace(
        document_max_upload_bytes=1024,
        tts_cache_enabled=True,
        tts_cache_ttl_seconds=86400,
    ))
    module.make_cache_key = lambda text, voice_hint, provider: "tts:v1:test"

    async def _fake_cache_get(key: str):
        assert key == "tts:v1:test"
        return types.SimpleNamespace(
            audio_bytes=b"cached-audio",
            content_type="audio/wav",
            provider="indextts",
        )

    async def _fake_cache_put(*args, **kwargs):
        raise AssertionError("cache_put should not be called on cache hit")

    class BrokenService:
        def synthesize(self, request, provider=""):
            raise AssertionError("synthesize should not run on cache hit")

    module.cache_get = _fake_cache_get
    module.cache_put = _fake_cache_put
    module._get_service = lambda: BrokenService()

    client, _ = _authenticated_client(module)
    response = client.post(
        "/v1/audio/speech",
        json={"input": "你好", "voice": "hayley", "provider": "indextts"},
    )

    assert response.status_code == 200
    assert response.content == b"cached-audio"
    assert response.headers["X-TTS-Provider"] == "indextts"
    assert response.headers["X-TTS-Cache-Hit"] == "true"


def test_tts_stream_falls_back_to_service_when_indextts_stream_errors(monkeypatch):
    module, _ = _load_main(monkeypatch, max_upload_bytes=1024)
    error_response = types.SimpleNamespace(
        status_code=503,
        headers={"content-type": "text/plain"},
        closed=False,
    )

    async def _read_error_body():
        return b"stream unavailable"

    async def _close_error_response():
        error_response.closed = True

    error_response.aread = _read_error_body
    error_response.aclose = _close_error_response

    class FakeAsyncClient:
        instances: list["FakeAsyncClient"] = []

        def __init__(self, *args, **kwargs):
            self.closed = False
            self.requests: list[object] = []
            type(self).instances.append(self)

        def build_request(self, method: str, url: str, *, json: dict[str, str], **kwargs):
            request = types.SimpleNamespace(method=method, url=url, json=json, **kwargs)
            self.requests.append(request)
            return request

        async def send(self, request, *, stream: bool = False):
            assert request.method == "POST"
            assert request.url == "http://index-tts-vllm:8011/tts_stream"
            assert request.json == {"text": "你好", "character": "hayley"}
            assert stream is True
            return error_response

        async def aclose(self):
            self.closed = True

    class FakeService:
        def __init__(self):
            self.requests: list[object] = []
            # Edge disabled → fallback 走 buffered service chain（本測試的情境）。
            self.edge_adapter = types.SimpleNamespace(enabled=False)

        def synthesize(self, request, provider=""):
            self.requests.append(request)
            return types.SimpleNamespace(
                result=types.SimpleNamespace(
                    audio_bytes=b"fallback-wav",
                    content_type="audio/wav",
                )
            )

    fake_service = FakeService()
    monkeypatch.setattr(module.httpx, "AsyncClient", FakeAsyncClient)
    monkeypatch.setattr(module, "_get_service", lambda: fake_service)
    monkeypatch.setattr(module, "get_tts_config", lambda: _make_test_config(
        document_max_upload_bytes=1024,
        tts_indextts_url="http://index-tts-vllm:8011",
        tts_indextts_default_character="hayley",
    ))

    client, _ = _authenticated_client(module)
    response = client.post("/tts/stream", json={"text": "你好", "character": "hayley"})

    assert response.status_code == 200
    assert response.content == b"fallback-wav"
    assert response.headers["content-type"].startswith("audio/wav")
    assert len(FakeAsyncClient.instances) == 1
    assert FakeAsyncClient.instances[0].closed is True
    assert error_response.closed is True
    assert len(fake_service.requests) == 1
    assert fake_service.requests[0].text == "你好"
    assert fake_service.requests[0].voice_hint == "hayley"


def test_tts_stream_uses_edge_streaming_fallback_when_enabled(monkeypatch):
    module, _ = _load_main(monkeypatch, max_upload_bytes=1024)

    async def _edge_stream(request):
        yield b"edge-1"
        yield b"edge-2"

    captured: dict[str, object] = {}

    class FakeService:
        def __init__(self):
            self.synthesize_called = False
            self.edge_adapter = types.SimpleNamespace(
                enabled=True,
                synthesize_stream=lambda request: (
                    captured.setdefault("request", request),
                    _edge_stream(request),
                )[1],
            )

        def synthesize(self, request, provider=""):
            self.synthesize_called = True
            raise AssertionError("buffered synthesize 不應被呼叫")

    fake_service = FakeService()
    monkeypatch.setattr(module, "_get_service", lambda: fake_service)
    # 無 IndexTTS → 直接進 fallback；Edge enabled → 走 streaming。
    monkeypatch.setattr(module, "get_tts_config", lambda: _make_test_config(
        document_max_upload_bytes=1024,
        tts_indextts_url="",
        tts_indextts_default_character="hayley",
    ))

    client, _ = _authenticated_client(module)
    response = client.post("/tts/stream", json={"text": "你好", "character": "hayley"})

    assert response.status_code == 200
    assert response.content == b"edge-1edge-2"
    assert response.headers["content-type"].startswith("audio/mpeg")
    assert fake_service.synthesize_called is False


class FakeRelay:
    instances: list["FakeRelay"] = []

    def __init__(self, session, *, event_sink=None, voice_source="gemini", **_kwargs):
        self.session = session
        self.event_sink = event_sink
        self.voice_source = voice_source
        self.sent_events: list[dict[str, object]] = []
        self.closed = False
        type(self).instances.append(self)

    async def send_event(self, payload: dict[str, object]) -> None:
        self.sent_events.append(payload)

    async def close(self) -> None:
        self.closed = True


def test_websocket_routes_user_speak_to_brain_relay_when_relay_is_active(monkeypatch):
    module, _ = _load_main(monkeypatch, max_upload_bytes=1024)
    FakeRelay.instances.clear()
    module.websocket_routes.BrainLiveRelay = FakeRelay
    monkeypatch.setattr(module, "get_tts_config", lambda: _make_test_config(
        document_max_upload_bytes=1024,
    ))

    client, _ = _authenticated_client(module)
    with client.websocket_connect("/ws/client-1") as websocket:
        websocket.send_text(json.dumps({"event": "client_init"}))
        ack = websocket.receive_json()
        assert ack["event"] == "server_init_ack"

        # Send audio event first to establish the Brain relay
        websocket.send_text(
            json.dumps({
                "event": "client_audio_chunk",
                "audio_base64": "YWJj",
                "sample_rate": 16000,
                "mime_type": "audio/pcm;rate=16000",
                "timestamp": 100,
            })
        )
        # Now user_speak should route through the active relay
        websocket.send_text(json.dumps({"event": "user_speak", "text": "你好"}))

    assert len(FakeRelay.instances) == 1
    events = [e["event"] for e in FakeRelay.instances[0].sent_events]
    assert "client_audio_chunk" in events
    assert "user_speak" in events


def test_websocket_routes_audio_events_to_brain_live_relay(monkeypatch):
    module, _ = _load_main(monkeypatch, max_upload_bytes=1024)
    FakeRelay.instances.clear()
    module.websocket_routes.BrainLiveRelay = FakeRelay
    monkeypatch.setattr(module, "get_tts_config", lambda: _make_test_config(
        document_max_upload_bytes=1024,
    ))

    client, _ = _authenticated_client(module)
    with client.websocket_connect("/ws/client-2") as websocket:
        websocket.send_text(json.dumps({"event": "client_init"}))
        ack = websocket.receive_json()
        assert ack["event"] == "server_init_ack"

        websocket.send_text(
            json.dumps(
                {
                    "event": "client_audio_chunk",
                    "audio_base64": "YWJj",
                    "sample_rate": 16000,
                    "mime_type": "audio/pcm;rate=16000",
                    "timestamp": 123,
                }
            )
        )
        websocket.send_text(json.dumps({"event": "client_audio_end", "timestamp": 124}))

    assert len(FakeRelay.instances) == 1
    assert [event["event"] for event in FakeRelay.instances[0].sent_events] == [
        "client_audio_chunk",
        "client_audio_end",
    ]
    assert FakeRelay.instances[0].sent_events[0]["audio_base64"] == "YWJj"
    assert FakeRelay.instances[0].sent_events[1]["timestamp"] == 124


def test_websocket_drops_audio_before_client_init_and_uses_initialized_voice_source(monkeypatch):
    module, _ = _load_main(monkeypatch, max_upload_bytes=1024)
    FakeRelay.instances.clear()
    module.websocket_routes.BrainLiveRelay = FakeRelay
    monkeypatch.setattr(module, "get_tts_config", lambda: _make_test_config(
        document_max_upload_bytes=1024,
    ))

    client, _ = _authenticated_client(module)
    with client.websocket_connect("/ws/client-preinit") as websocket:
        websocket.send_text(
            json.dumps(
                {
                    "event": "client_audio_chunk",
                    "audio_base64": "YWJj",
                    "sample_rate": 16000,
                    "mime_type": "audio/pcm;rate=16000",
                    "timestamp": 99,
                }
            )
        )
        websocket.send_text(
            json.dumps(
                {
                    "event": "client_init",
                    "client_id": "client-preinit",
                    "capabilities": {
                        "voice_source": "custom",
                        "session_id": "chat-123",
                    },
                }
            )
        )
        ack = websocket.receive_json()
        assert ack["event"] == "server_init_ack"
        websocket.send_text(
            json.dumps(
                {
                    "event": "client_audio_chunk",
                    "audio_base64": "ZGVm",
                    "sample_rate": 16000,
                    "mime_type": "audio/pcm;rate=16000",
                    "timestamp": 100,
                }
            )
        )

    assert len(FakeRelay.instances) == 1
    relay = FakeRelay.instances[0]
    # Backend no longer forwards voice_source to the relay — it's recorded on
    # the session only, since TTS is handled by the frontend via /tts_stream.
    assert relay.session.metadata["voice_source"] == "custom"
    assert relay.session.metadata["chat_session_id"] == "chat-123"
    assert [event["event"] for event in relay.sent_events] == ["client_audio_chunk"]
    assert relay.sent_events[0]["audio_base64"] == "ZGVm"


def test_handle_client_init_stores_voice_source_from_capabilities(monkeypatch):
    import asyncio
    from app.auth.dependencies import AuthTransport, CurrentAccount
    from app.auth.models import AccountRole, ResourceType, ResourceVisibility
    from app.auth.passwords import hash_password
    from app.auth.runtime import get_auth_runtime

    runtime = get_auth_runtime()
    admin = runtime.users.get_by_username("test-admin")
    if not admin:
        admin = runtime.users.create(
            username="test-admin",
            password_hash=hash_password("admin-password"),
            role=AccountRole.ADMIN,
        )
    try:
        runtime.resources.register(
            resource_type=ResourceType.PROJECT,
            resource_id="default",
            owner_user_id=admin.id,
            visibility=ResourceVisibility.PRIVATE,
        )
    except Exception:
        pass
    current = CurrentAccount(user=admin, transport=AuthTransport.BEARER)

    module, _ = _load_main(monkeypatch, max_upload_bytes=1024)
    session = types.SimpleNamespace(
        session_id="session-1",
        metadata={"_current_account": current},
    )
    websocket = types.SimpleNamespace(send_json=AsyncMock(), close=AsyncMock())

    asyncio.run(
        module.websocket_routes._handle_client_init(
            {
                "event": "client_init",
                "client_id": "client-voice",
                "capabilities": {
                    "voice_source": "custom",
                },
            },
            session,
            websocket,
        )
    )

    websocket.send_json.assert_awaited_once()
    assert session.metadata["client_id"] == "client-voice"
    assert session.metadata["voice_source"] == "custom"


def test_websocket_routes_user_speak_to_brain_relay_even_without_prior_audio(monkeypatch):
    module, _ = _load_main(monkeypatch, max_upload_bytes=1024)
    FakeRelay.instances.clear()
    module.websocket_routes.BrainLiveRelay = FakeRelay

    class FakePipeline:
        instances: list["FakePipeline"] = []

        def __init__(self, session):
            self.session = session
            self.text_turns: list[str] = []
            type(self).instances.append(self)

        async def run(self, user_text: str):
            self.text_turns.append(user_text)
            yield {
                "event": "server_stream_chunk",
                "chunk_id": "chunk-1",
                "session_id": self.session.session_id,
                "text": user_text,
                "audio_base64": "YXVkaW8=",
                "is_final": True,
            }

    monkeypatch.setattr(module, "get_tts_config", lambda: _make_test_config(
        document_max_upload_bytes=1024,
    ))

    client, _ = _authenticated_client(module)
    with client.websocket_connect("/ws/client-3") as websocket:
        websocket.send_text(json.dumps({"event": "client_init"}))
        ack = websocket.receive_json()
        assert ack["event"] == "server_init_ack"

        websocket.send_text(json.dumps({"event": "user_speak", "text": "走新路"}))

    assert len(FakeRelay.instances) == 1
    assert [event["event"] for event in FakeRelay.instances[0].sent_events] == ["user_speak"]
    assert FakeRelay.instances[0].sent_events[0]["text"] == "走新路"
    assert FakePipeline.instances == []


def test_tts_providers_includes_voxcpm_when_configured(monkeypatch):
    module, _ = _load_main(monkeypatch, max_upload_bytes=1024)

    class FakeResponse:
        def raise_for_status(self) -> None:
            return None

        def json(self) -> dict:
            return {
                "model_version": "voxcpm360-castvoice-test",
                "voices": [
                    {"voice_id": "barbet-hung-yi-lee", "label": "李宏毅老師"},
                    {
                        "voice_id": "voxcpm2-cosy-young-female-01",
                        "label": "青年女聲 01",
                    },
                ],
            }

    class FakeClient:
        async def get(self, url: str, timeout=None, follow_redirects=None):
            assert url == "http://10.9.0.37:8800/api/v1/tts/voices"
            return FakeResponse()

    async def _fake_close() -> None:
        return None

    module.admin_routes._health_http = types.SimpleNamespace(
        get=lambda: FakeClient(),
        close=_fake_close,
    )
    monkeypatch.setattr(module.admin_routes, "get_tts_config", lambda: types.SimpleNamespace(
        document_max_upload_bytes=1024,
        tts_indextts_url="",
        tts_gcp_enabled=False,
        tts_aws_enabled=False,
        tts_gemini_url="",
        tts_voxcpm_url="http://10.9.0.37:8800",
        tts_voxcpm_default_voice="",
        edge_tts_enabled=False,
    ))

    assert _get_tts_provider_payload(module) == [
        {"id": "auto", "name": "自動", "default_voice": "", "voices": []},
        {
            "id": "voxcpm",
            "name": "VoxCPM",
            "default_voice": "voxcpm2-cosy-young-female-01",
            "voices": ["barbet-hung-yi-lee", "voxcpm2-cosy-young-female-01"],
        },
    ]


def _usage_account(module, *, admin: bool):
    from app.auth.dependencies import AuthTransport, CurrentAccount
    from app.auth.models import AccountRole
    from app.auth.passwords import hash_password
    from app.auth.runtime import get_auth_runtime

    runtime = get_auth_runtime()
    username = "usage-admin" if admin else "usage-user"
    user = runtime.users.get_by_username(username)
    if not user:
        user = runtime.users.create(
            username=username,
            password_hash=hash_password("password"),
            role=AccountRole.ADMIN if admin else AccountRole.USER,
        )
    return CurrentAccount(user=user, transport=AuthTransport.BEARER)


def _install_fake_brain_usage(module, captured: dict[str, object], monkeypatch):
    class FakeResponse:
        status_code = 200

        def json(self) -> dict[str, dict[str, int]]:
            return {"totals": {"total_tokens": 42}}

    class FakeAsyncClient:
        async def get(self, url: str, params=None, headers=None, timeout=None):
            captured["url"] = url
            captured["params"] = dict(params or {})
            captured["headers"] = dict(headers or {})
            return FakeResponse()

    class FakeClient:
        def get(self) -> FakeAsyncClient:
            return FakeAsyncClient()

        async def close(self) -> None:
            return None

    monkey_cfg = types.SimpleNamespace(
        brain_url="http://brain:8100/",
        gateway_internal_token="internal-secret",
    )
    monkeypatch.setattr(module.admin_routes, "_health_http", FakeClient())
    monkeypatch.setattr(module.admin_routes, "get_tts_config", lambda: monkey_cfg)


def _usage_request(query: str) -> Request:
    scope = {
        "type": "http",
        "method": "GET",
        "path": "/v1/usage/summary",
        "query_string": query.encode(),
        "headers": [],
    }
    return Request(scope)


def test_usage_summary_admin_forwards_filters(monkeypatch):
    module, _ = _load_main(monkeypatch, max_upload_bytes=1024)
    captured: dict[str, object] = {}
    _install_fake_brain_usage(module, captured, monkeypatch)

    response = asyncio.run(
        module.admin_routes.get_usage_summary(
            _usage_request("group_by=user&user_id=someone&project_id=p1&bogus=1"),
            current=_usage_account(module, admin=True),
        )
    )

    assert response.status_code == 200
    assert json.loads(response.body) == {"totals": {"total_tokens": 42}}
    assert captured["url"] == "http://brain:8100/brain/usage/summary"
    assert captured["params"] == {
        "group_by": "user",
        "user_id": "someone",
        "project_id": "p1",
    }
    assert captured["headers"] == {"X-Internal-Token": "internal-secret"}


def test_usage_events_non_admin_is_scoped_to_self(monkeypatch):
    module, _ = _load_main(monkeypatch, max_upload_bytes=1024)
    captured: dict[str, object] = {}
    _install_fake_brain_usage(module, captured, monkeypatch)
    current = _usage_account(module, admin=False)

    response = asyncio.run(
        module.admin_routes.get_usage_events(
            _usage_request("user_id=someone-else&limit=5"),
            current=current,
        )
    )

    assert response.status_code == 200
    assert captured["url"] == "http://brain:8100/brain/usage/events"
    assert captured["params"] == {"user_id": current.user.id, "limit": "5"}


def test_usage_routes_only_forward_endpoint_parameters(monkeypatch):
    module, _ = _load_main(monkeypatch, max_upload_bytes=1024)
    captured: dict[str, object] = {}
    _install_fake_brain_usage(module, captured, monkeypatch)
    current = _usage_account(module, admin=True)

    asyncio.run(
        module.admin_routes.get_usage_summary(
            _usage_request("group_by=model&limit=5&trace_id=t1"),
            current=current,
        )
    )
    assert captured["params"] == {"group_by": "model"}

    asyncio.run(
        module.admin_routes.get_usage_events(
            _usage_request("limit=5&group_by=user"),
            current=current,
        )
    )
    assert captured["params"] == {"limit": "5"}
