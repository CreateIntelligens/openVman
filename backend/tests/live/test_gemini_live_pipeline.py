import base64
import types

import pytest

from app.session_manager import Session


class FakeTransport:
    def __init__(self, messages: list[dict]):
        self._messages = list(messages)
        self.sent_messages: list[dict] = []
        self.closed = False

    async def connect(self) -> None:
        return None

    async def send_json(self, payload: dict) -> None:
        self.sent_messages.append(payload)

    async def recv_json(self) -> dict | None:
        if not self._messages:
            return None
        return self._messages.pop(0)

    async def close(self) -> None:
        self.closed = True


class FakeBrainClient:
    def __init__(self, search_payload: dict):
        self.search_payload = search_payload
        self.calls: list[tuple[str, dict]] = []

    async def post(self, url: str, json: dict):
        self.calls.append((url, json))
        return types.SimpleNamespace(
            status_code=200,
            raise_for_status=lambda: None,
            json=lambda: self.search_payload,
        )


@pytest.mark.asyncio
async def test_gemini_live_pipeline_emits_audio_chunks_from_server_content():
    from app.gateway.gemini_live import GeminiLivePipeline

    pcm_audio = base64.b64encode(b"\x00\x00\x00\x00").decode("ascii")
    transport = FakeTransport([
        {"setupComplete": {}},
        {
            "serverContent": {
                "modelTurn": {
                    "parts": [
                        {"text": "哈囉"},
                        {
                            "inlineData": {
                                "mimeType": "audio/pcm;rate=24000",
                                "data": pcm_audio,
                            }
                        },
                    ]
                }
            }
        },
        {"serverContent": {"turnComplete": True}},
    ])
    session = Session(client_id="client-1")
    cfg = types.SimpleNamespace(

        gemini_api_key="test-key",
        live_gemini_model="gemini-3.1-flash-live-preview",
        live_gemini_system_instruction="",
        live_gemini_output_audio_transcription=True,
        live_gemini_tools_enabled=True,
        live_gemini_thinking_level="minimal",
        brain_url="http://api:8100",
    )
    pipeline = GeminiLivePipeline(
        session,
        config=cfg,
        transport_factory=lambda _cfg: transport,
        brain_http_factory=lambda: FakeBrainClient({"results": []}),
    )

    events = [event async for event in pipeline.run("你好")]

    assert len(events) == 1
    assert events[0]["event"] == "server_stream_chunk"
    assert events[0]["session_id"] == session.session_id
    assert events[0]["text"] == "哈囉"
    decoded = base64.b64decode(events[0]["audio_base64"])
    assert decoded.startswith(b"RIFF")
    assert transport.sent_messages[0]["setup"]["model"] == "models/gemini-3.1-flash-live-preview"
    assert transport.sent_messages[1]["clientContent"]["turns"][0]["parts"][0]["text"] == "你好"


@pytest.mark.asyncio
async def test_gemini_live_pipeline_executes_search_tool_calls_and_returns_tool_response():
    from app.gateway.gemini_live import GeminiLivePipeline

    tool_call = {
        "toolCall": {
            "functionCalls": [
                {
                    "id": "call-1",
                    "name": "search_knowledge",
                    "args": {"query": "退款政策", "top_k": 2},
                }
            ]
        }
    }
    transport = FakeTransport([
        {"setupComplete": {}},
        tool_call,
        {"serverContent": {"turnComplete": True}},
    ])
    brain_client = FakeBrainClient(
        {
            "results": [
                {"text": "七天內可退款", "source": "policy.md", "date": "2026-04-07"},
            ]
        }
    )
    session = Session(client_id="client-2")
    cfg = types.SimpleNamespace(

        gemini_api_key="test-key",
        live_gemini_model="gemini-3.1-flash-live-preview",
        live_gemini_system_instruction="",
        live_gemini_output_audio_transcription=True,
        live_gemini_tools_enabled=True,
        live_gemini_thinking_level="minimal",
        brain_url="http://api:8100",
    )
    pipeline = GeminiLivePipeline(
        session,
        config=cfg,
        transport_factory=lambda _cfg: transport,
        brain_http_factory=lambda: brain_client,
    )

    events = [event async for event in pipeline.run("幫我查退款政策")]

    assert events == []
    assert brain_client.calls == [
        (
            "http://api:8100/brain/search",
            {
                "query": "退款政策",
                "table": "knowledge",
                "top_k": 2,
                "query_type": "vector",
                "persona_id": "default",
                "project_id": "default",
            },
        )
    ]
    assert transport.sent_messages[2] == {
        "toolResponse": {
            "functionResponses": [
                {
                    "id": "call-1",
                    "name": "search_knowledge",
                    "response": {
                        "results": [
                            {"text": "七天內可退款", "source": "policy.md", "date": "2026-04-07"},
                        ]
                    },
                }
            ]
        }
    }
