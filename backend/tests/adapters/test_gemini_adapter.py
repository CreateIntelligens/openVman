from unittest.mock import MagicMock

import httpx
import pytest

from app.config import TTSRouterConfig
from app.providers.base import SynthesizeRequest
from app.providers.gemini_tts_adapter import GeminiTTSAdapter, GeminiTTSHTTPError


def test_gemini_adapter_disabled_by_default():
    config = TTSRouterConfig(_env_file=None, tts_gemini_url="")
    adapter = GeminiTTSAdapter(config)
    assert adapter.enabled is False
    assert adapter.provider_name == "gemini-tts"


def test_gemini_adapter_synthesis_success(monkeypatch):
    config = TTSRouterConfig(_env_file=None, tts_gemini_url="http://localhost:8206")
    adapter = GeminiTTSAdapter(config)

    mock_response = httpx.Response(
        status_code=200,
        content=b"mock-wav-bytes",
        headers={"content-type": "audio/wav", "X-Seed": "42"},
    )

    mock_post = MagicMock(return_value=mock_response)
    monkeypatch.setattr(adapter._client, "post", mock_post)

    req = SynthesizeRequest(text="你好", voice_hint="Zephyr")
    res = adapter.synthesize(req)

    assert res.audio_bytes == b"mock-wav-bytes"
    assert res.content_type == "audio/wav"
    assert res.provider == "gemini-tts"
    assert res.raw_metadata["seed"] == "42"

    mock_post.assert_called_once_with(
        "http://localhost:8206/api/tts",
        json={"text": "你好", "voice": "Zephyr"},
    )


def test_gemini_adapter_synthesis_http_error(monkeypatch):
    config = TTSRouterConfig(_env_file=None, tts_gemini_url="http://localhost:8206")
    adapter = GeminiTTSAdapter(config)

    mock_response = httpx.Response(status_code=400, text="Unknown voice")
    monkeypatch.setattr(adapter._client, "post", MagicMock(return_value=mock_response))

    req = SynthesizeRequest(text="你好")
    with pytest.raises(GeminiTTSHTTPError) as exc_info:
        adapter.synthesize(req)

    assert exc_info.value.status_code == 400
    assert "Unknown voice" in exc_info.value.detail
