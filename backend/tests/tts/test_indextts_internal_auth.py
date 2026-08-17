from __future__ import annotations

import importlib.util
from pathlib import Path
import sys
import types
from uuid import uuid4

from fastapi.testclient import TestClient


def _load_api_server(monkeypatch):
    infer_module = types.ModuleType("indextts.infer_vllm")
    infer_module.IndexTTS = object
    soundfile_module = types.ModuleType("soundfile")
    soundfile_module.write = lambda *_args, **_kwargs: None
    monkeypatch.setitem(sys.modules, "indextts", types.ModuleType("indextts"))
    monkeypatch.setitem(sys.modules, "indextts.infer_vllm", infer_module)
    monkeypatch.setitem(sys.modules, "soundfile", soundfile_module)

    path = (
        Path(__file__).resolve().parents[2]
        / "index-tts-vllm"
        / "api_server.py"
    )
    spec = importlib.util.spec_from_file_location(
        f"indextts_api_server_{uuid4().hex}",
        path,
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_health_is_public_but_other_routes_require_internal_token(monkeypatch) -> None:
    monkeypatch.setenv("INTERNAL_API_TOKEN", "test-internal-token")
    module = _load_api_server(monkeypatch)
    client = TestClient(module.app)

    assert client.get("/health").status_code == 200
    assert client.get("/audio/voices").status_code == 403
    assert client.get(
        "/audio/voices",
        headers={"X-Internal-Token": "wrong"},
    ).status_code == 403
    assert client.get(
        "/audio/voices",
        headers={"X-Internal-Token": "test-internal-token"},
    ).status_code == 200


def test_protected_routes_fail_closed_without_configured_secret(monkeypatch) -> None:
    monkeypatch.delenv("INTERNAL_API_TOKEN", raising=False)
    module = _load_api_server(monkeypatch)
    client = TestClient(module.app)

    response = client.get(
        "/audio/voices",
        headers={"X-Internal-Token": "any-value"},
    )

    assert response.status_code == 503
    assert response.json() == {
        "detail": "internal API token is not configured",
    }
