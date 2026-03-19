"""Tests for the FastAPI entrypoint."""

from __future__ import annotations

import importlib
import sys
import types
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


def test_convert_rejects_oversized_upload(monkeypatch):
    module, fake_markitdown = _load_main(monkeypatch, max_upload_bytes=4)
    client = TestClient(module.app)

    response = client.post(
        "/convert",
        files={"file": ("note.txt", b"abcdef", "text/plain")},
    )

    assert response.status_code == 413
    assert response.json()["error"] == "uploaded file too large"
    assert fake_markitdown.init_count == 0
    assert fake_markitdown.convert_paths == []


def test_convert_lazily_initializes_markitdown_once(monkeypatch):
    module, fake_markitdown = _load_main(monkeypatch, max_upload_bytes=1024)
    client = TestClient(module.app)

    assert fake_markitdown.init_count == 0

    first = client.post(
        "/convert",
        files={"file": ("note.txt", b"hello", "text/plain")},
    )
    second = client.post(
        "/convert",
        files={"file": ("note.txt", b"world", "text/plain")},
    )

    assert first.status_code == 200
    assert second.status_code == 200
    assert first.json()["markdown"] == "converted markdown"
    assert second.json()["markdown"] == "converted markdown"
    assert fake_markitdown.init_count == 1
    assert len(fake_markitdown.convert_paths) == 2
