import pytest
import asyncio
import json
import base64
from unittest.mock import AsyncMock, MagicMock, patch
from app.gateway.live_pipeline import LiveVoicePipeline
from app.providers.base import NormalizedTTSResult
from app.service import SynthesisOutput
from app.session_manager import Session

@pytest.fixture
def mock_session():
    session = Session(client_id="test-client")
    session.websocket = AsyncMock()
    return session

@pytest.mark.asyncio
async def test_live_pipeline_full_flow(mock_session):
    pipeline = LiveVoicePipeline(mock_session)
    
    # Mock Brain SSE stream
    mock_response = MagicMock()
    mock_response.status_code = 200
    
    async def mock_aiter_lines():
        yield 'data: {"token": "你好"}'
        yield 'data: {"token": "。"}'
        yield "data: [DONE]"
    
    mock_response.aiter_lines = mock_aiter_lines
    
    # Mock VibeVoice synthesis
    router_result = SynthesisOutput(
        result=NormalizedTTSResult(
            audio_bytes=b"fake-audio",
            content_type="audio/wav",
            sample_rate=16000,
            provider="indextts",
            route_kind="provider",
            route_target="indextts",
            latency_ms=8.2,
        )
    )

    with patch("httpx.AsyncClient.stream", return_value=AsyncMock(__aenter__=AsyncMock(return_value=mock_response))):
        with patch("app.gateway.live_pipeline.TTSRouterService.synthesize", return_value=router_result):
            events = []
            async for event in pipeline.run("hello"):
                events.append(event)
            
            assert len(events) > 0
            assert events[0]["event"] == "server_stream_chunk"
            assert events[0]["text"] == "你好。"
            assert events[0]["audio_base64"] == base64.b64encode(b"fake-audio").decode("utf-8")

@pytest.mark.asyncio
async def test_live_pipeline_interruption_cleanup(mock_session):
    # This test would verify that when session.interrupt_tasks is called,
    # the pipeline stops.
    pass


@pytest.mark.asyncio
async def test_live_pipeline_uses_tts_router_when_vibevoice_is_unavailable(mock_session):
    pipeline = LiveVoicePipeline(mock_session)

    mock_response = MagicMock()
    mock_response.status_code = 200

    async def mock_aiter_lines():
        yield 'data: {"token": "測試"}'
        yield 'data: {"token": "。"}'
        yield "data: [DONE]"

    mock_response.aiter_lines = mock_aiter_lines

    router_result = SynthesisOutput(
        result=NormalizedTTSResult(
            audio_bytes=b"router-audio",
            content_type="audio/wav",
            sample_rate=16000,
            provider="indextts",
            route_kind="provider",
            route_target="indextts",
            latency_ms=12.5,
        )
    )

    with patch("httpx.AsyncClient.stream", return_value=AsyncMock(__aenter__=AsyncMock(return_value=mock_response))):
        with patch("app.gateway.live_pipeline.TTSRouterService.synthesize", return_value=router_result) as synthesize:
            events = []
            async for event in pipeline.run("hello"):
                events.append(event)

            synthesize.assert_called()
            assert len(events) > 0
            assert events[0]["event"] == "server_stream_chunk"
            assert events[0]["text"] == "測試。"
            assert events[0]["audio_base64"] == base64.b64encode(b"router-audio").decode("utf-8")
