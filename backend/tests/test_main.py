"""Tests for the FastAPI entrypoint."""

from __future__ import annotations

import importlib
import json
import sys
import types
import warnings
from pathlib import Path

from fastapi.testclient import TestClient

API_ROOT = Path(__file__).resolve().parents[1]
if str(API_ROOT) not in sys.path:
    sys.path.insert(0, str(API_ROOT))


def _load_main(monkeypatch, *, max_upload_bytes: int = 1024):
    fake_markitdown_mod = types.ModuleType("markitdown")

    class FakeMarkItDown:
        init_count = 0
        convert_paths: list[str] = []

        def __init__(self) -> None:
            type(self).init_count += 1

        def convert(self, path: str):
            type(self).convert_paths.append(path)
            return types.SimpleNamespace(text_content="converted markdown")

    fake_markitdown_mod.MarkItDown = FakeMarkItDown
    monkeypatch.setitem(sys.modules, "markitdown", fake_markitdown_mod)

    sys.modules.pop("app.main", None)
    module = importlib.import_module("app.main")
    module._md_converter = None
    module.get_tts_config = lambda: types.SimpleNamespace(
        markitdown_max_upload_bytes=max_upload_bytes,
    )
    return module, FakeMarkItDown


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
    module.get_tts_config = lambda: fake_cfg

    module.run_server()

    assert captured["args"] == ("app.main:app",)
    assert captured["kwargs"] == {
        "host": "0.0.0.0",
        "port": 9999,
        "reload": True,
    }


def test_convert_rejects_oversized_upload(monkeypatch):
    module, fake_markitdown = _load_main(monkeypatch, max_upload_bytes=4)
    client = TestClient(module.app)

    response = client.post(
        "/documents/convert",
        files={"file": ("note.txt", b"abcdef", "text/plain")},
    )

    assert response.status_code == 413
    assert response.json()["error_code"] == "UPLOAD_FAILED"
    assert fake_markitdown.init_count == 0


def test_convert_returns_upload_failed_code_when_conversion_crashes(monkeypatch):
    module, _fake_markitdown = _load_main(monkeypatch, max_upload_bytes=1024)
    client = TestClient(module.app)

    class BrokenConverter:
        def convert(self, path: str):
            raise RuntimeError("boom")

    module._md_converter = BrokenConverter()

    response = client.post(
        "/documents/convert",
        files={"file": ("note.txt", b"hello", "text/plain")},
    )

    assert response.status_code == 500
    assert response.json()["error"] == "boom"
    assert response.json()["error_code"] == "UPLOAD_FAILED"
    assert response.json()["message"] == "檔案上傳失敗"


def test_convert_lazily_initializes_markitdown_once(monkeypatch):
    module, fake_markitdown = _load_main(monkeypatch, max_upload_bytes=1024)
    client = TestClient(module.app)

    assert fake_markitdown.init_count == 0

    first = client.post(
        "/documents/convert",
        files={"file": ("note.txt", b"hello", "text/plain")},
    )
    second = client.post(
        "/documents/convert",
        files={"file": ("note.txt", b"world", "text/plain")},
    )

    assert first.status_code == 200
    assert second.status_code == 200
    assert first.json()["markdown"] == "converted markdown"
    assert second.json()["markdown"] == "converted markdown"
    assert fake_markitdown.init_count == 1
    assert len(fake_markitdown.convert_paths) == 2


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
        async def get(self, url: str, timeout=None):
            assert url == "http://index-tts-vllm:8011/audio/voices"
            return FakeResponse()

    async def _fake_close() -> None:
        return None

    module._health_http = types.SimpleNamespace(
        get=lambda: FakeClient(),
        close=_fake_close,
    )
    module.get_tts_config = lambda: types.SimpleNamespace(
        markitdown_max_upload_bytes=1024,
        tts_indextts_url="http://index-tts-vllm:8011",
        tts_indextts_default_character="hayley",
        tts_vibevoice_url="",
        tts_gcp_enabled=False,
        tts_aws_enabled=False,
        edge_tts_enabled=True,
        edge_tts_voice="zh-TW-HsiaoChenNeural",
    )

    client = TestClient(module.app)
    response = client.get("/v1/tts/providers")

    assert response.status_code == 200
    assert response.json() == [
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
            "voices": ["zh-TW-HsiaoChenNeural"],
        },
    ]


def test_create_speech_uses_backend_tts_cache_when_hit(monkeypatch):
    module, _ = _load_main(monkeypatch, max_upload_bytes=1024)
    module.get_tts_config = lambda: types.SimpleNamespace(
        markitdown_max_upload_bytes=1024,
        tts_cache_enabled=True,
        tts_cache_ttl_seconds=86400,
    )
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

    client = TestClient(module.app)
    response = client.post(
        "/v1/audio/speech",
        json={"input": "你好", "voice": "hayley", "provider": "indextts"},
    )

    assert response.status_code == 200
    assert response.content == b"cached-audio"
    assert response.headers["X-TTS-Provider"] == "indextts"
    assert response.headers["X-TTS-Cache-Hit"] == "true"


class FakeRelay:
    instances: list["FakeRelay"] = []

    def __init__(self, session, *, event_sink=None):
        self.session = session
        self.event_sink = event_sink
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
    module.BrainLiveRelay = FakeRelay
    module.get_tts_config = lambda: types.SimpleNamespace(
        markitdown_max_upload_bytes=1024,
    )

    client = TestClient(module.app)
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
    module.BrainLiveRelay = FakeRelay
    module.get_tts_config = lambda: types.SimpleNamespace(
        markitdown_max_upload_bytes=1024,
    )

    client = TestClient(module.app)
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


def test_websocket_routes_user_speak_to_live_pipeline_when_no_relay(monkeypatch):
    module, _ = _load_main(monkeypatch, max_upload_bytes=1024)

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
                "text": user_text,
                "audio_base64": "YXVkaW8=",
                "is_final": True,
            }

    module.LiveVoicePipeline = FakePipeline
    module.get_tts_config = lambda: types.SimpleNamespace(
        markitdown_max_upload_bytes=1024,
    )

    client = TestClient(module.app)
    with client.websocket_connect("/ws/client-3") as websocket:
        websocket.send_text(json.dumps({"event": "client_init"}))
        ack = websocket.receive_json()
        assert ack["event"] == "server_init_ack"

        websocket.send_text(json.dumps({"event": "user_speak", "text": "走舊路"}))
        chunk = websocket.receive_json()
        assert chunk["event"] == "server_stream_chunk"
        assert chunk["text"] == "走舊路"

    assert len(FakePipeline.instances) == 1
    assert FakePipeline.instances[0].text_turns == ["走舊路"]
