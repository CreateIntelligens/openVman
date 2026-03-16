"""Tests for the Index TTS provider adapter."""

from unittest.mock import MagicMock, patch
import pytest
from app.config import TTSRouterConfig
from app.providers.base import SynthesizeRequest
from app.providers.index_tts_adapter import IndexTTSAdapter, IndexTTSHTTPError
from app.providers.error_mapping import classify_index_error


@pytest.fixture
def index_config():
    return TTSRouterConfig(
        tts_index_url="http://mock-index:8001",
        tts_index_character="hayley",
        node_timeout_ms=5000,
    )


def test_index_adapter_enabled(index_config):
    adapter = IndexTTSAdapter(index_config)
    assert adapter.enabled is True
    assert adapter.provider_name == "index"


def test_index_adapter_disabled():
    config = TTSRouterConfig(tts_index_url="")
    adapter = IndexTTSAdapter(config)
    assert adapter.enabled is False


def test_index_adapter_synthesize_success(index_config):
    adapter = IndexTTSAdapter(index_config)
    request = SynthesizeRequest(text="Hello", voice_hint="hayley")

    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.content = b"fake-audio"
    mock_resp.headers = {"Content-Type": "audio/mpeg"}

    with patch("app.providers.index_tts_adapter.httpx.Client") as mock_client_cls:
        mock_client = MagicMock()
        mock_client.__enter__ = MagicMock(return_value=mock_client)
        mock_client.__exit__ = MagicMock(return_value=False)
        mock_client.post.return_value = mock_resp
        mock_client_cls.return_value = mock_client

        result = adapter.synthesize(request)

    assert result.audio_bytes == b"fake-audio"
    assert result.content_type == "audio/mpeg"
    assert result.provider == "index"
    assert result.route_target == "index-tts"
    assert result.raw_metadata["character"] == "hayley"


def test_index_adapter_http_error(index_config):
    adapter = IndexTTSAdapter(index_config)
    request = SynthesizeRequest(text="Hello")

    mock_resp = MagicMock()
    mock_resp.status_code = 500
    mock_resp.text = "Internal Server Error"

    with patch("app.providers.index_tts_adapter.httpx.Client") as mock_client_cls:
        mock_client = MagicMock()
        mock_client.__enter__ = MagicMock(return_value=mock_client)
        mock_client.__exit__ = MagicMock(return_value=False)
        mock_client.post.return_value = mock_resp
        mock_client_cls.return_value = mock_client

        with pytest.raises(IndexTTSHTTPError) as exc:
            adapter.synthesize(request)

    assert exc.value.status_code == 500
    assert "Internal Server Error" in str(exc.value)


class TestIndexErrorClassification:
    def test_timeout_exception(self):
        exc = type("TimeoutException", (Exception,), {})()
        assert classify_index_error(exc) == "network_error"

    def test_http_500(self):
        exc = IndexTTSHTTPError(status_code=500, detail="Internal Server Error")
        assert classify_index_error(exc) == "provider_unavailable"

    def test_http_422(self):
        exc = IndexTTSHTTPError(status_code=422, detail="Validation error")
        assert classify_index_error(exc) == "bad_request"
