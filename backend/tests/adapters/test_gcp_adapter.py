"""Tests for GCP Cloud TTS adapter (TASK-15)."""

from __future__ import annotations

import sys
import types
from unittest.mock import MagicMock

import pytest

# ---------------------------------------------------------------------------
# Stub google.cloud.texttospeech before importing adapter
# ---------------------------------------------------------------------------

_fake_tts_mod = types.ModuleType("google.cloud.texttospeech")
_fake_tts_mod.TextToSpeechClient = MagicMock  # type: ignore[attr-defined]
_fake_tts_mod.SynthesisInput = MagicMock  # type: ignore[attr-defined]
_fake_tts_mod.VoiceSelectionParams = MagicMock  # type: ignore[attr-defined]
_fake_tts_mod.AudioConfig = MagicMock  # type: ignore[attr-defined]

_fake_encoding = types.SimpleNamespace(LINEAR16="LINEAR16", MP3="MP3", OGG_OPUS="OGG_OPUS")
_fake_tts_mod.AudioEncoding = _fake_encoding  # type: ignore[attr-defined]

sys.modules.setdefault("google", types.ModuleType("google"))
sys.modules.setdefault("google.cloud", types.ModuleType("google.cloud"))
sys.modules.setdefault("google.cloud.texttospeech", _fake_tts_mod)

from app.config import TTSRouterConfig
from app.providers.base import SynthesizeRequest
from app.providers.error_mapping import (
    REASON_AUTH_ERROR,
    REASON_BAD_REQUEST,
    REASON_PROVIDER_UNAVAILABLE,
    REASON_RATE_LIMITED,
    classify_gcp_error,
)
from app.providers.gcp_adapter import GCPTTSAdapter


def _make_config(**overrides) -> TTSRouterConfig:
    defaults = {
        "tts_gcp_enabled": True,
        "tts_gcp_project_id": "test-project",
        "tts_gcp_credentials_json": "",
        "tts_gcp_voice_name": "cmn-TW-Standard-A",
        "tts_gcp_audio_encoding": "LINEAR16",
        "tts_gcp_sample_rate": 24000,
    }
    defaults.update(overrides)
    return TTSRouterConfig(**defaults)


class TestGCPTTSAdapter:
    def test_synthesize_returns_normalized_result(self):
        config = _make_config()
        adapter = GCPTTSAdapter(config)
        mock_client = MagicMock()
        mock_response = MagicMock()
        mock_response.audio_content = b"\xcc\xdd"
        mock_client.synthesize_speech.return_value = mock_response
        adapter._client = mock_client

        request = SynthesizeRequest(text="你好", locale="zh-TW")
        result = adapter.synthesize(request)

        assert result.audio_bytes == b"\xcc\xdd"
        assert result.provider == "gcp"
        assert result.route_kind == "provider"
        assert result.route_target == "gcp-tts"
        assert result.content_type == "audio/l16"
        assert result.sample_rate == 24000
        assert result.latency_ms >= 0
        assert result.raw_metadata["voice_name"] == "cmn-TW-Standard-A"

    def test_synthesize_uses_voice_hint(self):
        config = _make_config()
        adapter = GCPTTSAdapter(config)
        mock_client = MagicMock()
        mock_response = MagicMock()
        mock_response.audio_content = b"\x00"
        mock_client.synthesize_speech.return_value = mock_response
        adapter._client = mock_client

        request = SynthesizeRequest(text="hi", voice_hint="cmn-TW-Wavenet-B")
        adapter.synthesize(request)

        # VoiceSelectionParams should be called with the hint
        call_kwargs = mock_client.synthesize_speech.call_args[1]
        voice_params = call_kwargs["voice"]
        assert voice_params is not None

    def test_provider_name_and_enabled(self):
        adapter = GCPTTSAdapter(_make_config(tts_gcp_enabled=True))
        assert adapter.provider_name == "gcp"
        assert adapter.enabled is True

        adapter2 = GCPTTSAdapter(_make_config(tts_gcp_enabled=False))
        assert adapter2.enabled is False

    def test_synthesize_propagates_exception(self):
        config = _make_config()
        adapter = GCPTTSAdapter(config)
        mock_client = MagicMock()
        mock_client.synthesize_speech.side_effect = RuntimeError("gcp boom")
        adapter._client = mock_client

        with pytest.raises(RuntimeError, match="gcp boom"):
            adapter.synthesize(SynthesizeRequest(text="test"))


class TestGCPErrorMapping:
    def test_unauthenticated(self):
        exc = type("Unauthenticated", (Exception,), {})("no creds")
        assert classify_gcp_error(exc) == REASON_AUTH_ERROR

    def test_permission_denied(self):
        exc = type("PermissionDenied", (Exception,), {})("forbidden")
        assert classify_gcp_error(exc) == REASON_AUTH_ERROR

    def test_resource_exhausted(self):
        exc = type("ResourceExhausted", (Exception,), {})("quota exceeded")
        assert classify_gcp_error(exc) == REASON_RATE_LIMITED

    def test_invalid_argument(self):
        exc = type("InvalidArgument", (Exception,), {})("bad input")
        assert classify_gcp_error(exc) == REASON_BAD_REQUEST

    def test_service_unavailable(self):
        exc = type("ServiceUnavailable", (Exception,), {})("down")
        assert classify_gcp_error(exc) == REASON_PROVIDER_UNAVAILABLE

    def test_deadline_exceeded(self):
        exc = type("DeadlineExceeded", (Exception,), {})("timeout")
        assert classify_gcp_error(exc) == REASON_PROVIDER_UNAVAILABLE

    def test_credentials_in_message(self):
        exc = Exception("Could not find default credentials")
        assert classify_gcp_error(exc) == REASON_AUTH_ERROR
