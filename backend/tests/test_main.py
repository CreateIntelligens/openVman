"""Tests for the FastAPI entrypoint."""

from __future__ import annotations

import importlib
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
    module, _ = _load_main(monkeypatch, max_upload_bytes=1024)
    module.app.openapi_schema = None
    monkeypatch.setattr(
        module,
        "_fetch_brain_openapi",
        lambda: {
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
        },
        raising=False,
    )
    client = TestClient(module.app)

    response = client.get("/openapi.json")

    assert response.status_code == 200
    operation = response.json()["paths"]["/api/chat"]["post"]
    assert operation["requestBody"]["required"] is True
    assert operation["requestBody"]["content"]["application/json"]["schema"] == {
        "$ref": "#/components/schemas/ChatRequest"
    }
