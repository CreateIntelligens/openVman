"""Tests for edge-tts worker service."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi.testclient import TestClient

from app.config import TTSWorkerConfig


@pytest.fixture(autouse=True)
def _reset_config():
    """Reset the cached config before each test."""
    import app.main as m
    m._config = None
    yield
    m._config = None


@pytest.fixture()
def client():
    from app.main import app
    return TestClient(app)


# ---- healthz ----

class TestHealthz:
    def test_healthz_returns_ok(self, client: TestClient):
        resp = client.get("/healthz")
        assert resp.status_code == 200
        body = resp.json()
        assert body["status"] == "ok"
        assert body["service"] == "edge-tts"
        assert body["engine"] == "edge-tts"
        assert body["device"] == "cpu"
        assert body["speaker_default"] == "zh-TW-HsiaoChenNeural"

    def test_healthz_reflects_custom_voice(self, client: TestClient):
        import app.main as m
        m._config = TTSWorkerConfig(voice="zh-TW-YunJheNeural")
        resp = client.get("/healthz")
        assert resp.json()["speaker_default"] == "zh-TW-YunJheNeural"


# ---- synthesize ----

def _make_audio_chunks(data: bytes = b"\xff\xfb\x90\x00" * 100):
    """Create mock edge-tts stream chunks."""
    async def stream():
        yield {"type": "audio", "data": data[:len(data) // 2]}
        yield {"type": "WordBoundary", "data": None}
        yield {"type": "audio", "data": data[len(data) // 2:]}
    return stream


class TestSynthesize:
    @patch("app.main.edge_tts.Communicate")
    def test_synthesize_returns_audio(self, mock_cls, client: TestClient):
        mock_instance = MagicMock()
        mock_instance.stream = _make_audio_chunks(b"\xaa" * 200)
        mock_cls.return_value = mock_instance

        resp = client.post(
            "/v1/synthesize",
            json={"text": "你好世界"},
        )
        assert resp.status_code == 200
        assert resp.headers["content-type"] == "audio/mpeg"
        assert "X-Request-Id" in resp.headers
        assert "X-TTS-Latency-Ms" in resp.headers
        assert "X-Sample-Rate" in resp.headers
        assert len(resp.content) == 200

    @patch("app.main.edge_tts.Communicate")
    def test_synthesize_uses_speaker_id(self, mock_cls, client: TestClient):
        mock_instance = MagicMock()
        mock_instance.stream = _make_audio_chunks()
        mock_cls.return_value = mock_instance

        client.post(
            "/v1/synthesize",
            json={"text": "test", "speaker_id": "en-US-GuyNeural"},
        )
        mock_cls.assert_called_once_with("test", "en-US-GuyNeural")

    @patch("app.main.edge_tts.Communicate")
    def test_synthesize_preserves_request_id(self, mock_cls, client: TestClient):
        mock_instance = MagicMock()
        mock_instance.stream = _make_audio_chunks()
        mock_cls.return_value = mock_instance

        resp = client.post(
            "/v1/synthesize",
            json={"text": "test", "request_id": "req-abc-123"},
        )
        assert resp.headers["X-Request-Id"] == "req-abc-123"

    def test_synthesize_rejects_empty_text(self, client: TestClient):
        resp = client.post("/v1/synthesize", json={"text": ""})
        assert resp.status_code == 422

    def test_synthesize_rejects_whitespace_text(self, client: TestClient):
        resp = client.post("/v1/synthesize", json={"text": "   "})
        assert resp.status_code == 422

    def test_synthesize_rejects_too_long_text(self, client: TestClient):
        import app.main as m
        m._config = TTSWorkerConfig(max_text_length=10)
        resp = client.post("/v1/synthesize", json={"text": "a" * 20})
        assert resp.status_code == 422
        assert "max length" in resp.json()["error"]
