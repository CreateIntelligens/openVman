"""Tests for AWS Polly adapter (TASK-14)."""

from __future__ import annotations

import io
import sys
import types
from unittest.mock import MagicMock

import pytest

# ---------------------------------------------------------------------------
# Stub boto3 before importing adapter
# ---------------------------------------------------------------------------

_fake_boto3 = types.ModuleType("boto3")
_fake_boto3.client = MagicMock()  # type: ignore[attr-defined]
sys.modules.setdefault("boto3", _fake_boto3)

from app.config import TTSRouterConfig
from app.providers.aws_adapter import AWSPollyAdapter
from app.providers.base import SynthesizeRequest
from app.providers.error_mapping import (
    REASON_AUTH_ERROR,
    REASON_BAD_REQUEST,
    REASON_NETWORK_ERROR,
    REASON_PROVIDER_UNAVAILABLE,
    REASON_RATE_LIMITED,
    classify_aws_error,
)


def _make_config(**overrides) -> TTSRouterConfig:
    defaults = {
        "tts_aws_enabled": True,
        "tts_aws_region": "ap-northeast-1",
        "tts_aws_access_key_id": "test-key",
        "tts_aws_secret_access_key": "test-secret",
        "tts_aws_polly_voice_id": "Zhiyu",
        "tts_aws_polly_engine": "neural",
        "tts_aws_output_format": "pcm",
        "tts_aws_sample_rate": 24000,
    }
    defaults.update(overrides)
    return TTSRouterConfig(**defaults)


def _make_polly_response(audio: bytes = b"\x00\x01\x02") -> dict:
    return {
        "AudioStream": io.BytesIO(audio),
        "ContentType": "audio/pcm",
        "RequestCharacters": 5,
    }


class TestAWSPollyAdapter:
    def test_synthesize_returns_normalized_result(self):
        config = _make_config()
        adapter = AWSPollyAdapter(config)
        mock_client = MagicMock()
        mock_client.synthesize_speech.return_value = _make_polly_response(b"\xaa\xbb")
        adapter._client = mock_client

        request = SynthesizeRequest(text="你好", locale="zh-TW")
        result = adapter.synthesize(request)

        assert result.audio_bytes == b"\xaa\xbb"
        assert result.provider == "aws"
        assert result.route_kind == "provider"
        assert result.route_target == "aws-polly"
        assert result.content_type == "audio/pcm"
        assert result.sample_rate == 24000
        assert result.latency_ms >= 0
        assert result.raw_metadata["voice_id"] == "Zhiyu"

    def test_synthesize_uses_voice_hint(self):
        config = _make_config()
        adapter = AWSPollyAdapter(config)
        mock_client = MagicMock()
        mock_client.synthesize_speech.return_value = _make_polly_response()
        adapter._client = mock_client

        request = SynthesizeRequest(text="hi", voice_hint="Mizuki")
        adapter.synthesize(request)

        call_kwargs = mock_client.synthesize_speech.call_args[1]
        assert call_kwargs["VoiceId"] == "Mizuki"

    def test_provider_name_and_enabled(self):
        adapter = AWSPollyAdapter(_make_config(tts_aws_enabled=True))
        assert adapter.provider_name == "aws"
        assert adapter.enabled is True

        adapter2 = AWSPollyAdapter(_make_config(tts_aws_enabled=False))
        assert adapter2.enabled is False

    def test_synthesize_propagates_exception(self):
        config = _make_config()
        adapter = AWSPollyAdapter(config)
        mock_client = MagicMock()
        mock_client.synthesize_speech.side_effect = RuntimeError("boom")
        adapter._client = mock_client

        with pytest.raises(RuntimeError, match="boom"):
            adapter.synthesize(SynthesizeRequest(text="test"))


class TestAWSErrorMapping:
    def test_no_credentials(self):
        exc = type("NoCredentialsError", (Exception,), {})()
        assert classify_aws_error(exc) == REASON_AUTH_ERROR

    def test_throttling(self):
        exc = type("ThrottlingException", (Exception,), {})()
        assert classify_aws_error(exc) == REASON_RATE_LIMITED

    def test_client_error_with_status_500(self):
        exc = Exception("server error")
        exc.response = {"ResponseMetadata": {"HTTPStatusCode": 500}, "Error": {}}  # type: ignore[attr-defined]
        assert classify_aws_error(exc) == REASON_PROVIDER_UNAVAILABLE

    def test_text_too_long(self):
        exc = Exception("text too long")
        exc.response = {"Error": {"Code": "TextTooLong"}}  # type: ignore[attr-defined]
        assert classify_aws_error(exc) == REASON_BAD_REQUEST

    def test_timeout_error(self):
        exc = type("ConnectTimeoutError", (Exception,), {})(
            "connect timeout"
        )
        assert classify_aws_error(exc) == REASON_NETWORK_ERROR

    def test_access_denied(self):
        exc = Exception("Access denied for this operation")
        assert classify_aws_error(exc) == REASON_AUTH_ERROR
