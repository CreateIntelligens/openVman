"""One Gemini client per API key: building one loads CA certificates, which is costly per turn."""

from __future__ import annotations

import sys
import types

import pytest

from core import gemini_client, llm_client


@pytest.fixture
def fake_genai(monkeypatch):
    built: list[str] = []

    class Client:
        def __init__(self, api_key: str) -> None:
            built.append(api_key)
            self.api_key = api_key

    google = types.ModuleType("google")
    google.genai = types.SimpleNamespace(Client=Client)
    monkeypatch.setitem(sys.modules, "google", google)
    monkeypatch.setattr(llm_client, "current_model_project", lambda *a: None)
    gemini_client.clear_gemini_clients()
    yield built
    gemini_client.clear_gemini_clients()


def _use_key(monkeypatch, key: str) -> None:
    settings = types.SimpleNamespace(resolve_api_key_for_provider=lambda provider: key)
    monkeypatch.setattr(llm_client, "get_settings", lambda: settings)


def test_same_key_reuses_one_client(fake_genai, monkeypatch):
    _use_key(monkeypatch, "key-a")

    first = llm_client._get_gemini_client()
    second = llm_client._get_gemini_client()

    assert first is second
    assert fake_genai == ["key-a"]


def test_a_different_key_gets_its_own_client(fake_genai, monkeypatch):
    _use_key(monkeypatch, "key-a")
    first = llm_client._get_gemini_client()
    _use_key(monkeypatch, "key-b")
    second = llm_client._get_gemini_client()

    assert first is not second
    assert second.api_key == "key-b"


def test_no_key_builds_nothing(fake_genai, monkeypatch):
    _use_key(monkeypatch, "")

    assert llm_client._get_gemini_client() is None
    assert fake_genai == []
