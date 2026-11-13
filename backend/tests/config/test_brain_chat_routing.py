"""Chat traffic must split without sending administrative writes to chat workers."""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock
from urllib.parse import urlsplit

import httpx
import pytest

from app import (
    asr_glossary,
    brain_proxy,
    internal_routes,
    jev_client,
    language_routes,
)
from app.auth.models import AccountRole
from app.config import TTSRouterConfig
from app.gateway import asr_stream, routes_vision
from app.gateway.a2a_bridge import A2ABridgeDaemon
from app.gateway.brain_live_relay import BrainLiveRelay
from app.gateway.gemini_live import GeminiLivePipeline
from app.session_manager import Session


@pytest.fixture(params=["", "https://chat.example/proxy/"])
def routing_config(request):
    return TTSRouterConfig(
        _env_file=None,
        brain_url="http://admin:8100/",
        brain_chat_url=request.param,
        gateway_internal_token="internal-test-token",
    )


def test_chat_base_uses_environment_and_follows_copied_configuration(monkeypatch):
    monkeypatch.setenv("BRAIN_CHAT_URL", "https://chat.example/prefix/")
    cfg = TTSRouterConfig(_env_file=None, brain_url="http://admin:8100")
    assert cfg.resolved_brain_chat_url == "https://chat.example/prefix/"
    assert cfg.model_copy(update={"brain_chat_url": " "}).resolved_brain_chat_url == (
        "http://admin:8100"
    )
    assert cfg.model_copy(update={
        "brain_chat_url": "", "brain_url": "http://new-admin:8100",
    }).resolved_brain_chat_url == "http://new-admin:8100"


@pytest.mark.parametrize("method,path,chat", [
    ("POST", "chat", True),
    ("POST", "chat/stream", True),
    ("POST", "chat/accept", True),
    ("GET", "chat/history", True),
    ("GET", "chat/modes", True),
    ("POST", "search", True),
    ("DELETE", "chat/history", False),
    ("POST", "chat/history", False),
    ("POST", "chat/stream/extra", False),
    ("POST", "chat/acceptance", False),
    ("PUT", "knowledge/settings", False),
    ("GET", "knowledge/settings", False),
    ("POST", "usage/events", False),
    ("POST", "knowledge/upload", False),
    ("POST", "tools/skills/demo/toggle", False),
])
def test_proxy_routes_exact_operations_and_preserves_query(
    routing_config, monkeypatch, method, path, chat,
):
    monkeypatch.setattr(brain_proxy, "get_tts_config", lambda: routing_config)
    base = (
        routing_config.resolved_brain_chat_url if chat else routing_config.brain_url
    ).rstrip("/")
    assert brain_proxy._target_url(path, "project_id=test&limit=5", method) == (
        f"{base}/brain/{path}?project_id=test&limit=5"
    )
    assert brain_proxy._brain_host(path, method) == urlsplit(base).netloc


def _client(payload):
    response = httpx.Response(
        200, json=payload, request=httpx.Request("POST", "http://test"),
    )
    return SimpleNamespace(
        post=AsyncMock(return_value=response),
        get=AsyncMock(return_value=response),
    )


@pytest.mark.asyncio
async def test_jev_decision_uses_chat_target(routing_config, monkeypatch):
    client = _client({"answers": {"q": {"choice": "IGNORE"}}})
    monkeypatch.setattr(jev_client, "get_tts_config", lambda: routing_config)
    monkeypatch.setattr(jev_client, "_shared_client", lambda: client)
    assert jev_client.jev_available()
    assert (await jev_client.jev_answer({}, {}, timeout=0.6))["choice"] == "IGNORE"
    assert client.post.await_args.args[0] == (
        f"{routing_config.resolved_brain_chat_url.rstrip('/')}/internal/decision"
    )


@pytest.mark.asyncio
async def test_asr_judgement_uses_chat_target(routing_config, monkeypatch):
    client = _client({"text": "final"})
    monkeypatch.setattr(asr_stream, "get_tts_config", lambda: routing_config)
    monkeypatch.setattr(asr_stream._http, "get", lambda: client)
    monkeypatch.setattr(asr_stream, "_append_judge_log", lambda _: None)
    assert await asr_stream._judge_final("test", ["zh"], "interim", "final") == "final"
    assert client.post.await_args.args[0] == (
        f"{routing_config.resolved_brain_chat_url.rstrip('/')}/brain/internal/asr-judge"
    )


@pytest.mark.asyncio
async def test_language_settings_and_audio_check_use_chat_target(
    routing_config, monkeypatch,
):
    client = _client({"language_routes": ["zh", "nan"], "language": "nan"})
    monkeypatch.setattr(language_routes, "get_tts_config", lambda: routing_config)
    monkeypatch.setattr(language_routes._http, "get", lambda: client)
    monkeypatch.setattr(language_routes, "_cache", {})
    monkeypatch.setattr(language_routes, "_to_wav_bytes", lambda _: b"wav")
    assert await language_routes.admin_routes("test") == ["zh", "nan"]
    assert client.get.await_args.args[0] == (
        f"{routing_config.resolved_brain_chat_url.rstrip('/')}/brain/knowledge/settings"
    )
    assert await language_routes._ask_brain_language(
        "test.wav", routing_config, project_id="test",
    ) == "nan"
    assert client.post.await_args.args[0] == (
        f"{routing_config.resolved_brain_chat_url.rstrip('/')}/brain/internal/audio-language"
    )
    assert client.post.await_args.kwargs["params"] == {"project_id": "test"}


@pytest.mark.asyncio
async def test_asr_glossary_uses_chat_target(routing_config, monkeypatch):
    client = _client({"terms": "example"})
    monkeypatch.setattr(asr_glossary, "get_tts_config", lambda: routing_config)
    monkeypatch.setattr(asr_glossary._http, "get", lambda: client)
    monkeypatch.setattr(asr_glossary, "_cache", {})
    monkeypatch.setattr(asr_glossary, "resolve_project", lambda *_: "test")
    assert await asr_glossary.project_asr_prompt(None, "test") == "example"
    assert client.get.await_args.args[0] == (
        f"{routing_config.resolved_brain_chat_url.rstrip('/')}/brain/internal/asr-glossary"
    )


@pytest.mark.asyncio
async def test_enrich_uses_chat_target_and_preserves_internal_auth(
    routing_config, monkeypatch,
):
    client = _client({"stored_count": 1})
    monkeypatch.setattr(internal_routes, "get_tts_config", lambda: routing_config)
    monkeypatch.setattr(internal_routes._http, "get", lambda: client)
    result = await internal_routes.internal_enrich(
        internal_routes.InternalEnrichRequest(project_id="test"),
        x_internal_token=routing_config.gateway_internal_token,
    )
    assert result == {"stored_count": 1}
    assert client.post.await_args.args[0] == (
        f"{routing_config.resolved_brain_chat_url.rstrip('/')}/internal/enrich"
    )
    assert client.post.await_args.kwargs["headers"] == {
        "X-Internal-Token": routing_config.gateway_internal_token,
    }


@pytest.mark.asyncio
async def test_vision_reply_uses_chat_target_and_preserves_identity(
    routing_config, monkeypatch,
):
    client = _client({"reply": "hello"})
    monkeypatch.setattr(routes_vision, "get_tts_config", lambda: routing_config)
    monkeypatch.setattr(routes_vision._http, "get", lambda: client)
    current = SimpleNamespace(user=SimpleNamespace(id="caller", role=AccountRole.USER))
    result = await routes_vision._generate_reply(
        routes_vision.VisionDescribeRequest(frame_base64="AA==", project_id="test"),
        "context", "session", current,
    )
    assert result == "hello"
    assert client.post.await_args.args[0] == (
        f"{routing_config.resolved_brain_chat_url.rstrip('/')}/brain/chat"
    )
    assert client.post.await_args.kwargs["headers"]["X-OpenVMan-User-ID"] == "caller"
    assert client.post.await_args.kwargs["headers"]["X-OpenVMan-Project-ID"] == "test"


@pytest.mark.asyncio
async def test_a2a_reply_uses_chat_target(routing_config):
    # Bypass daemon setup: only this request path is under test, with no queue files.
    daemon = A2ABridgeDaemon.__new__(A2ABridgeDaemon)
    daemon.config = routing_config
    client = _client({"reply": "hello"})
    daemon._http_client = client
    assert await daemon._query_brain("hello", "peer", "task", None) == "hello"
    assert client.post.await_args.args[0] == (
        f"{routing_config.resolved_brain_chat_url.rstrip('/')}/brain/chat"
    )


@pytest.mark.asyncio
async def test_live_search_uses_chat_target(routing_config):
    pipeline = GeminiLivePipeline(Session(client_id="test"), config=routing_config)
    client = _client({"results": [{"text": "example"}]})
    assert await pipeline._search_brain("knowledge", {"query": "test"}, client) == {
        "results": [{"text": "example"}],
    }
    assert client.post.await_args.args[0] == (
        f"{routing_config.resolved_brain_chat_url.rstrip('/')}/brain/search"
    )


@pytest.mark.asyncio
async def test_live_websocket_uses_chat_target_and_matching_scheme(routing_config):
    socket = SimpleNamespace(send=AsyncMock(), close=AsyncMock())
    connect = AsyncMock(return_value=socket)
    session = Session(client_id="test")
    relay = BrainLiveRelay(session, config=routing_config, websocket_factory=connect)
    await relay.ensure_connected()
    await relay.close()
    base = routing_config.resolved_brain_chat_url.rstrip("/")
    expected = base.replace("https://", "wss://").replace("http://", "ws://")
    assert connect.await_args.args[0] == (
        f"{expected}/brain/internal/live/{session.session_id}"
    )
    assert connect.await_args.kwargs["additional_headers"]["X-Internal-Token"] == (
        routing_config.gateway_internal_token
    )


@pytest.mark.asyncio
async def test_health_probes_each_configured_brain_target(
    routing_config, monkeypatch,
):
    from app import health_payloads
    from app.gateway import vision_clef, vlm_client

    client = _client({"status": "ok"})
    monkeypatch.setattr(health_payloads, "get_tts_config", lambda: routing_config)
    monkeypatch.setattr(vlm_client, "probe_vlm_health", AsyncMock(return_value={}))
    monkeypatch.setattr(vision_clef, "probe_clef_health", AsyncMock(return_value={}))
    probes = await health_payloads._probe_downstream_services(client)
    urls = {call.args[0] for call in client.get.await_args_list}
    assert "http://admin:8100/brain/health/ready" in urls
    if routing_config.brain_chat_url:
        assert "https://chat.example/proxy/brain/health/ready" in urls
        assert "brain-chat" in probes
        assert health_payloads._overall_status(
            redis_ok=True, quota_ok=True,
            downstream={"brain-chat": {"status": "unreachable"}},
        ) == "degraded"
    else:
        assert "brain-chat" not in probes


@pytest.mark.asyncio
@pytest.mark.parametrize("method,path,base", [
    ("POST", "chat", "https://chat.example/proxy"),
    ("GET", "chat/history", "https://chat.example/proxy"),
    ("DELETE", "chat/history", "http://admin:8100"),
])
async def test_proxy_request_uses_method_when_selecting_upstream(
    monkeypatch, method, path, base,
):
    from starlette.requests import Request

    cfg = TTSRouterConfig(
        _env_file=None,
        brain_url="http://admin:8100/",
        brain_chat_url="https://chat.example/proxy/",
    )
    requests = []

    def handler(request):
        requests.append(request)
        return httpx.Response(200, json={"reply": "hello"})

    async def receive():
        return {"type": "http.request", "body": b"{}", "more_body": False}

    async def complete(_request, task):
        return await task

    request = Request({
        "type": "http", "method": method, "path": f"/api/v1/{path}",
        "query_string": b"project_id=test", "headers": [],
    }, receive=receive)
    monkeypatch.setattr(brain_proxy, "get_tts_config", lambda: cfg)
    monkeypatch.setattr(brain_proxy, "_unless_client_gone", complete)
    monkeypatch.setattr(
        brain_proxy, "_authorize_project_context", AsyncMock(return_value="test"),
    )
    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        monkeypatch.setattr(brain_proxy._http, "get", lambda: client)
        result = await brain_proxy.proxy_to_brain(request, path, current=None)
    assert result.status_code == 200
    assert requests[0].method == method
    assert str(requests[0].url) == f"{base}/brain/{path}?project_id=test"
