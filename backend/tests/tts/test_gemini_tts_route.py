"""Gemini TTS goes straight to Google or through the relay, as chosen in the Admin."""

from __future__ import annotations

import asyncio
import base64
import json

import httpx
import pytest
from pydantic import ValidationError

from app.auth import gemini_tts_route
from app.auth.models import ResourceType
from app.auth.project_gemini_credentials import (
    GeminiCredential,
    ProjectCredentialUnavailable,
)
from app.auth.runtime import build_auth_runtime, get_auth_runtime
from app.config import TTSRouterConfig
from app.providers import gemini_tts_adapter, project_gemini_tts, voice_catalog
from app.providers.base import SynthesizeRequest
from app import system_resources
from app.upstream_probe import probe_targets

RELAY = "http://relay.invalid:8206"
SHARED = GeminiCredential("shared-test-key", "shared", "gemini", True)
NO_SHARED = GeminiCredential("", "shared", "gemini", False)
PROJECT = GeminiCredential("project-test-key", "project", "pgc_a", True)
PCM = b"\x00\x00\x01\x00" * 8


def _config(**overrides) -> TTSRouterConfig:
    values = {"_env_file": None, "tts_gemini_url": RELAY}
    values.update(overrides)
    return TTSRouterConfig(**values)


def _keys(monkeypatch, *, shared=SHARED, project=None):
    """Patch the resolver: ``project`` answers for project ids, ``shared`` otherwise."""
    calls: list[str | None] = []

    def resolve(project_id, *_args):
        calls.append(project_id)
        if project_id is not None and project is not None:
            if isinstance(project, Exception):
                raise project
            return project
        return shared

    monkeypatch.setattr(gemini_tts_adapter, "resolve_gemini_credential", resolve)
    return calls


def _root_id(runtime) -> str:
    existing = runtime.users.get_by_username("ai360")
    if existing is not None:
        return existing.id
    return runtime.users.create_root(username="ai360", password_hash="unused").id


def _save_route(route: str) -> None:
    runtime = get_auth_runtime()
    runtime.settings.set("tts_gemini_route", route, actor_id=_root_id(runtime))
    gemini_tts_route.clear_gemini_route_cache()


def _request(project: str | None = None) -> SynthesizeRequest:
    scope = {"project_id": project} if project else {}
    return SynthesizeRequest("你好", voice_hint="Puck", usage_scope=scope)


def _audio_json() -> dict:
    return {"candidates": [{"content": {"parts": [{"inlineData": {
        "data": base64.b64encode(PCM).decode(), "mimeType": "audio/L16;rate=24000",
    }}]}}]}


def _sync_adapter(monkeypatch, config):
    sent: list[httpx.Request] = []

    def respond(upstream: httpx.Request) -> httpx.Response:
        sent.append(upstream)
        if upstream.url.host == "generativelanguage.googleapis.com":
            return httpx.Response(200, json=_audio_json())
        return httpx.Response(200, content=b"relay-wav", headers={"content-type": "audio/wav"})

    adapter = gemini_tts_adapter.GeminiTTSAdapter(config)
    adapter._client.close()
    adapter._client = httpx.Client(transport=httpx.MockTransport(respond))
    return adapter, sent


def _stream_clients(monkeypatch):
    """Route every AsyncClient (Google and relay) to one mock transport."""
    sent: list[httpx.Request] = []
    client_type = httpx.AsyncClient

    def respond(upstream: httpx.Request) -> httpx.Response:
        sent.append(upstream)
        if upstream.url.host == "generativelanguage.googleapis.com":
            body = "data: " + json.dumps(_audio_json()) + "\n\n"
            return httpx.Response(200, content=body.encode())
        return httpx.Response(200, content=PCM)

    def factory(**kwargs):
        return client_type(transport=httpx.MockTransport(respond), **kwargs)

    monkeypatch.setattr(project_gemini_tts.httpx, "AsyncClient", factory)
    monkeypatch.setattr(gemini_tts_adapter.httpx, "AsyncClient", factory)
    return sent


async def _drain(stream) -> bytes:
    return b"".join([chunk async for chunk in stream])


# --- configuration ---------------------------------------------------------


def test_route_defaults_to_direct_and_rejects_unknown_values(monkeypatch):
    monkeypatch.delenv("TTS_GEMINI_ROUTE", raising=False)
    assert TTSRouterConfig(_env_file=None).tts_gemini_route == "direct"

    monkeypatch.setenv("TTS_GEMINI_ROUTE", "relay")
    assert TTSRouterConfig(_env_file=None).tts_gemini_route == "relay"

    monkeypatch.setenv("TTS_GEMINI_ROUTE", "google")
    with pytest.raises(ValidationError):
        TTSRouterConfig(_env_file=None)


# --- non-streaming ---------------------------------------------------------


def test_direct_route_calls_google_with_the_shared_key(monkeypatch):
    calls = _keys(monkeypatch)
    adapter, sent = _sync_adapter(monkeypatch, _config())

    result = adapter.synthesize(_request())

    assert [r.url.host for r in sent] == ["generativelanguage.googleapis.com"]
    assert sent[0].headers["x-goog-api-key"] == "shared-test-key"
    assert result.raw_metadata["credential_source"] == "shared"
    assert result.content_type == "audio/wav"
    assert calls == [None]


def test_relay_route_posts_to_the_relay(monkeypatch):
    _keys(monkeypatch)
    _save_route("relay")
    adapter, sent = _sync_adapter(monkeypatch, _config())

    result = adapter.synthesize(_request())

    assert [str(r.url) for r in sent] == [f"{RELAY}/api/tts"]
    assert json.loads(sent[0].content) == {"text": "你好", "voice": "Puck"}
    assert result.audio_bytes == b"relay-wav"


@pytest.mark.parametrize("route", ["direct", "relay"])
def test_project_key_goes_to_google_on_either_route(monkeypatch, route):
    _keys(monkeypatch, project=PROJECT)
    _save_route(route)
    adapter, sent = _sync_adapter(monkeypatch, _config())

    result = adapter.synthesize(_request("proj-a"))

    assert [r.url.host for r in sent] == ["generativelanguage.googleapis.com"]
    assert sent[0].headers["x-goog-api-key"] == "project-test-key"
    assert result.raw_metadata["credential_source"] == "project"


def test_direct_route_without_any_key_fails_without_calling_anyone(monkeypatch):
    _keys(monkeypatch, shared=NO_SHARED)
    adapter, sent = _sync_adapter(monkeypatch, _config())

    with pytest.raises(RuntimeError):
        adapter.synthesize(_request())
    assert sent == []


def test_broken_project_key_is_still_refused_on_the_direct_route(monkeypatch):
    _keys(monkeypatch, project=ProjectCredentialUnavailable())
    adapter, sent = _sync_adapter(monkeypatch, _config())

    with pytest.raises(ProjectCredentialUnavailable):
        adapter.synthesize(_request("proj-a"))
    with pytest.raises(ProjectCredentialUnavailable):
        asyncio.run(adapter.open_stream(_request("proj-a")))
    assert sent == []


# --- streaming -------------------------------------------------------------


@pytest.mark.asyncio
async def test_direct_stream_uses_google_with_the_shared_key(monkeypatch):
    _keys(monkeypatch)
    sent = _stream_clients(monkeypatch)
    adapter = gemini_tts_adapter.GeminiTTSAdapter(_config())

    assert await _drain(await adapter.open_stream(_request())) == PCM
    assert [r.url.host for r in sent] == ["generativelanguage.googleapis.com"]
    assert sent[0].url.params["alt"] == "sse"
    assert sent[0].headers["x-goog-api-key"] == "shared-test-key"


@pytest.mark.asyncio
async def test_relay_stream_uses_the_relay(monkeypatch):
    _keys(monkeypatch)
    _save_route("relay")
    sent = _stream_clients(monkeypatch)
    adapter = gemini_tts_adapter.GeminiTTSAdapter(_config())

    assert await _drain(await adapter.open_stream(_request())) == PCM
    assert [str(r.url) for r in sent] == [f"{RELAY}/api/tts"]
    assert json.loads(sent[0].content)["stream"] is True


@pytest.mark.asyncio
async def test_project_key_stream_goes_to_google_on_the_relay_route(monkeypatch):
    _keys(monkeypatch, project=PROJECT)
    _save_route("relay")
    sent = _stream_clients(monkeypatch)
    adapter = gemini_tts_adapter.GeminiTTSAdapter(_config())

    assert await _drain(await adapter.open_stream(_request("proj-a"))) == PCM
    assert [r.url.host for r in sent] == ["generativelanguage.googleapis.com"]
    assert sent[0].headers["x-goog-api-key"] == "project-test-key"


# --- enabled flags and host label -----------------------------------------


@pytest.mark.parametrize("route,url,shared,enabled,host", [
    ("direct", RELAY, SHARED, True, "generativelanguage.googleapis.com"),
    ("direct", RELAY, NO_SHARED, False, "generativelanguage.googleapis.com"),
    ("direct", "", SHARED, True, "generativelanguage.googleapis.com"),
    ("relay", RELAY, NO_SHARED, True, "relay.invalid:8206"),
    ("relay", "", SHARED, False, ""),
])
def test_enabled_and_host_follow_the_route(monkeypatch, route, url, shared, enabled, host):
    _keys(monkeypatch, shared=shared)
    _save_route(route)
    adapter = gemini_tts_adapter.GeminiTTSAdapter(_config(tts_gemini_url=url))

    assert adapter.enabled is enabled
    assert adapter.enabled_for(_request()) is enabled
    assert adapter.host == host


def test_project_key_enables_gemini_even_when_the_route_cannot_run(monkeypatch):
    _keys(monkeypatch, shared=NO_SHARED, project=PROJECT)
    adapter = gemini_tts_adapter.GeminiTTSAdapter(_config(tts_gemini_url=""))

    assert adapter.enabled is False
    assert adapter.enabled_for(_request("proj-a")) is True


# --- the setting itself ----------------------------------------------------


def test_saved_route_overrides_the_deployment_default(monkeypatch):
    _keys(monkeypatch)
    adapter = gemini_tts_adapter.GeminiTTSAdapter(_config(tts_gemini_route="relay"))
    assert adapter.route == "relay"

    _save_route("direct")
    assert adapter.route == "direct"


def test_other_workers_see_a_saved_route_once_their_cache_expires(monkeypatch):
    now = [1000.0]
    monkeypatch.setattr(gemini_tts_route, "monotonic", lambda: now[0])
    adapter = gemini_tts_adapter.GeminiTTSAdapter(_config())
    assert adapter.route == "direct"

    # 另一個 worker：自己的 runtime 與資料庫連線，存檔不會清掉這個 worker 的快取。
    other_worker = build_auth_runtime(get_auth_runtime().config)
    other_worker.settings.set(
        "tts_gemini_route", "relay", actor_id=_root_id(other_worker),
    )

    now[0] += gemini_tts_route.ROUTE_CACHE_SECONDS / 2
    assert adapter.route == "direct"
    now[0] += gemini_tts_route.ROUTE_CACHE_SECONDS
    assert adapter.route == "relay"


def test_route_is_read_per_request_without_rebuilding_the_adapter(monkeypatch):
    _keys(monkeypatch)
    adapter, sent = _sync_adapter(monkeypatch, _config())

    adapter.synthesize(_request())
    _save_route("relay")
    adapter.synthesize(_request())

    assert [r.url.host for r in sent] == [
        "generativelanguage.googleapis.com", "relay.invalid",
    ]


# --- voices and probes -----------------------------------------------------


def _registered(runtime) -> set[str]:
    return {
        voice_id for voice_id in gemini_tts_adapter.GEMINI_PREBUILT_VOICES
        if runtime.resources.get(ResourceType.CUSTOM_VOICE, voice_id) is not None
    }


def _resource_config(**overrides) -> TTSRouterConfig:
    return _config(
        tts_indextts_url="", tts_voxcpm_url="", tts_cosyvoice_url="",
        edge_tts_enabled=False, **overrides,
    )


@pytest.mark.parametrize("url,shared,route,registered", [
    ("", SHARED, "direct", True),
    ("", SHARED, "relay", True),
    (RELAY, NO_SHARED, "direct", True),
    (RELAY, NO_SHARED, "relay", True),
    ("", NO_SHARED, "direct", False),
])
def test_google_voices_are_registered_whenever_either_route_can_run(
    monkeypatch, url, shared, route, registered,
):
    _keys(monkeypatch, shared=shared)
    _save_route(route)
    runtime = get_auth_runtime()
    cfg = _resource_config(tts_gemini_url=url)

    asyncio.run(system_resources.sync_system_resources(runtime, cfg))
    catalog = asyncio.run(voice_catalog.build_tts_provider_catalog(cfg))

    expected = set(gemini_tts_adapter.GEMINI_PREBUILT_VOICES) if registered else set()
    assert _registered(runtime) == expected
    gemini = [p for p in catalog if p["id"] == "gemini-tts"]
    if registered:
        assert len(gemini_tts_adapter.GEMINI_PREBUILT_VOICES) == 30
        assert set(gemini[0]["voices"]) == expected
        assert gemini[0]["default_voice"] == "Kore"
    else:
        assert gemini == []


@pytest.mark.parametrize("route", ["direct", "relay"])
def test_relay_is_probed_whenever_its_url_is_set(monkeypatch, route):
    _save_route(route)

    with_relay = [t.node for t in probe_targets(_config(tts_gemini_route=route))]
    without = [t.node for t in probe_targets(_config(tts_gemini_url=""))]

    assert with_relay.count("gemini-tts") == 1
    assert "gemini-tts" not in without
