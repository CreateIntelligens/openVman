import pytest
import asyncio
import json
import base64
from unittest.mock import AsyncMock, MagicMock, patch
from app.gateway.live_pipeline import LiveVoicePipeline
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
    mock_result = MagicMock()
    mock_result.audio_bytes = b"fake-audio"
    
    with patch("httpx.AsyncClient.stream", return_value=AsyncMock(__aenter__=AsyncMock(return_value=mock_response))):
        with patch("app.providers.vibevoice_adapter.VibeVoiceAdapter.synthesize", return_value=mock_result):
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
