"""Project Gemini TTS uses its own key and owns its upstream resources."""

from __future__ import annotations

import base64
import io
import json
import wave

import httpx
import pytest

from app.auth.project_gemini_credentials import (
    GeminiCredential,
    ProjectCredentialUnavailable,
)
from app.config import TTSRouterConfig
from app.providers import gemini_tts_adapter, project_gemini_tts
from app.providers.base import SynthesizeRequest

KEY = "project-a-test-secret"
PCM = b"\x00\x00\x01\x00" * 16


def credential(key=KEY, project="a"):
    return GeminiCredential(key, "project", f"pgc_{project}", True)


def audio_payload(pcm=PCM, mime="audio/l16;rate=24000;channels=1"):
    return {"candidates": [{"content": {"parts": [{"inlineData": {
        "data": base64.b64encode(pcm).decode(), "mimeType": mime,
    }}]}}]}


def event(payload):
    return "data: " + json.dumps(payload) + "\n\n"


def request(project="a"):
    return SynthesizeRequest(
        "你好", voice_hint="Kore", usage_scope={"project_id": project},
    )


def test_project_a_b_keys_go_only_to_google_and_unary_audio_is_wav(monkeypatch):
    sent = []

    def respond(upstream):
        sent.append(upstream)
        return httpx.Response(200, json=audio_payload())

    monkeypatch.setattr(
        gemini_tts_adapter, "resolve_gemini_credential",
        lambda project: credential(f"project-{project}-test-secret", project),
    )
    adapter = gemini_tts_adapter.GeminiTTSAdapter(TTSRouterConfig(
        _env_file=None, tts_gemini_url="https://console.invalid",
    ))
    adapter._client.close()
    adapter._client = httpx.Client(transport=httpx.MockTransport(respond))
    try:
        for project in ("a", "b"):
            result = adapter.synthesize(request(project))
            assert result.content_type == "audio/wav"
            assert result.raw_metadata["credential_id"] == f"pgc_{project}"
            assert result.raw_metadata["credential_source"] == "project"
            with wave.open(io.BytesIO(result.audio_bytes)) as wav:
                assert wav.getframerate() == 24000
                assert wav.getnchannels() == 1
                assert wav.getsampwidth() == 2
                assert wav.readframes(wav.getnframes()) == PCM
        assert [r.headers["x-goog-api-key"] for r in sent] == [
            "project-a-test-secret", "project-b-test-secret",
        ]
        for upstream in sent:
            assert upstream.url.host == "generativelanguage.googleapis.com"
            assert upstream.url.path.endswith(":generateContent")
            assert "key" not in upstream.url.params
            assert "secret" not in upstream.content.decode()
    finally:
        adapter._client.close()


def test_project_key_enables_native_tts_without_console(monkeypatch):
    monkeypatch.setattr(
        gemini_tts_adapter, "resolve_gemini_credential",
        lambda project: credential(),
    )
    adapter = gemini_tts_adapter.GeminiTTSAdapter(TTSRouterConfig(_env_file=None))
    try:
        assert adapter.enabled_for(request()) is True
    finally:
        adapter._client.close()


def test_broken_project_binding_cannot_call_console(monkeypatch):
    def unavailable(project):
        raise ProjectCredentialUnavailable()

    monkeypatch.setattr(
        gemini_tts_adapter, "resolve_gemini_credential", unavailable,
    )
    adapter = gemini_tts_adapter.GeminiTTSAdapter(TTSRouterConfig(
        _env_file=None, tts_gemini_url="https://console.invalid",
    ))
    calls = []
    monkeypatch.setattr(adapter._client, "post", lambda *a, **kw: calls.append(kw))
    try:
        with pytest.raises(ProjectCredentialUnavailable):
            adapter.synthesize(request())
        assert calls == []
    finally:
        adapter._client.close()


@pytest.mark.parametrize("status", [400, 401, 403, 429, 503])
def test_google_error_body_never_leaks_secret_or_calls_console(monkeypatch, status):
    sent = []

    def reject(upstream):
        sent.append(upstream.url.host)
        return httpx.Response(status, json={"error": {"message": KEY}})

    monkeypatch.setattr(
        gemini_tts_adapter, "resolve_gemini_credential",
        lambda project: credential(),
    )
    adapter = gemini_tts_adapter.GeminiTTSAdapter(TTSRouterConfig(
        _env_file=None, tts_gemini_url="https://console.invalid",
    ))
    adapter._client.close()
    adapter._client = httpx.Client(transport=httpx.MockTransport(reject))
    try:
        with pytest.raises(RuntimeError) as error:
            adapter.synthesize(request())
        assert KEY not in str(error.value)
        assert sent == ["generativelanguage.googleapis.com"]
    finally:
        adapter._client.close()


def test_native_sync_transport_error_is_sanitized():
    def reject(upstream):
        raise httpx.ConnectError(f"transport echoed {KEY}", request=upstream)

    with httpx.Client(transport=httpx.MockTransport(reject)) as client:
        with pytest.raises(Exception) as error:
            project_gemini_tts.synthesize(request(), credential(), "tts-model", client)
    assert KEY not in str(error.value)
    assert KEY not in repr(credential())


def test_pcm_media_type_is_case_insensitive():
    assert project_gemini_tts.audio_chunks(audio_payload(mime="audio/L16;rate=24000")) == [PCM]


class TrackedStream(httpx.AsyncByteStream):
    def __init__(self, content):
        self.content = content.encode()
        self.closed = False

    async def __aiter__(self):
        yield self.content

    async def aclose(self):
        self.closed = True


def mock_stream(monkeypatch, content, status=200, transport_error=None):
    sent = []
    clients = []
    stream = TrackedStream(content)
    client_type = httpx.AsyncClient

    def respond(upstream):
        sent.append(upstream)
        if transport_error:
            raise httpx.ConnectError(transport_error, request=upstream)
        return httpx.Response(status, stream=stream)

    def factory(**kwargs):
        client = client_type(transport=httpx.MockTransport(respond), **kwargs)
        clients.append(client)
        return client

    monkeypatch.setattr(project_gemini_tts.httpx, "AsyncClient", factory)
    return sent, clients, stream


@pytest.mark.asyncio
async def test_sse_returns_pcm_with_project_header_and_closes_resources(monkeypatch):
    sent, clients, upstream = mock_stream(
        monkeypatch,
        event(audio_payload(PCM[:16])) + event(audio_payload(PCM[16:])) + "data: [DONE]\n\n",
    )
    stream = await project_gemini_tts.open_stream(request(), credential(), "tts-model")
    assert b"".join([chunk async for chunk in stream]) == PCM
    assert sent[0].headers["x-goog-api-key"] == KEY
    assert sent[0].url.params["alt"] == "sse"
    assert sent[0].url.path.endswith(":streamGenerateContent")
    assert KEY not in str(sent[0].url)
    assert clients[0].is_closed
    assert upstream.closed


@pytest.mark.asyncio
@pytest.mark.parametrize("content,status", [
    (event({"candidates": []}), 200),
    (event({"error": {"message": KEY}}), 200),
    (event(audio_payload(mime="audio/wav")), 200),
    (KEY, 401),
])
async def test_stream_setup_failure_closes_resources_without_secret(monkeypatch, content, status):
    _, clients, upstream = mock_stream(monkeypatch, content, status)
    with pytest.raises(RuntimeError) as error:
        await project_gemini_tts.open_stream(request(), credential(), "tts-model")
    assert KEY not in str(error.value)
    assert clients[0].is_closed
    assert upstream.closed


@pytest.mark.asyncio
async def test_native_stream_transport_error_is_sanitized_and_client_closed(monkeypatch):
    _, clients, _ = mock_stream(monkeypatch, "", transport_error=f"echo {KEY}")
    with pytest.raises(Exception) as error:
        await project_gemini_tts.open_stream(request(), credential(), "tts-model")
    assert KEY not in str(error.value)
    assert clients[0].is_closed


@pytest.mark.asyncio
async def test_stream_consumer_early_close_releases_upstream(monkeypatch):
    _, clients, upstream = mock_stream(monkeypatch, event(audio_payload()))
    stream = await project_gemini_tts.open_stream(request(), credential(), "tts-model")
    assert await anext(stream) == PCM
    await stream.aclose()
    assert clients[0].is_closed
    assert upstream.closed


@pytest.mark.asyncio
async def test_stream_closed_before_iteration_releases_upstream(monkeypatch):
    _, clients, upstream = mock_stream(monkeypatch, event(audio_payload()))
    stream = await project_gemini_tts.open_stream(request(), credential(), "tts-model")
    await stream.aclose()
    assert clients[0].is_closed
    assert upstream.closed


@pytest.mark.asyncio
async def test_trailing_sse_error_after_audio_is_not_silently_accepted(monkeypatch):
    _, clients, upstream = mock_stream(
        monkeypatch,
        event(audio_payload()) + 'data: {"error":{"message":"upstream failure"}}',
    )
    stream = await project_gemini_tts.open_stream(request(), credential(), "tts-model")
    with pytest.raises(RuntimeError):
        _ = [chunk async for chunk in stream]
    assert clients[0].is_closed
    assert upstream.closed
