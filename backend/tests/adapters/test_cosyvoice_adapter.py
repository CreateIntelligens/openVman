from unittest.mock import MagicMock

import httpx
import pytest

from app.config import TTSRouterConfig
from app.providers.base import SynthesizeRequest
from app.providers.cosyvoice_adapter import (
    COSYVOICE_DEFAULT_VOICE,
    CosyVoiceAdapter,
    CosyVoiceHTTPError,
)
from app.providers.error_mapping import (
    REASON_AUTH_ERROR,
    REASON_BAD_REQUEST,
    REASON_NETWORK_ERROR,
    REASON_PROVIDER_UNAVAILABLE,
    REASON_RATE_LIMITED,
    classify_cosyvoice_error,
)

_COSYVOICE_URL = "http://cosyvoice:50010/v1"


def test_cosyvoice_adapter_disabled_by_default():
    config = TTSRouterConfig(_env_file=None, tts_cosyvoice_url="")
    adapter = CosyVoiceAdapter(config)
    assert adapter.enabled is False
    assert adapter.provider_name == "cosyvoice"


def test_cosyvoice_adapter_synthesis_success(monkeypatch):
    config = TTSRouterConfig(
        _env_file=None,
        tts_cosyvoice_url="http://10.9.0.35:50010/v1/",
        tts_cosyvoice_api_key="secret",
    )
    adapter = CosyVoiceAdapter(config)

    mock_response = httpx.Response(
        status_code=200,
        content=b"mock-mp3-bytes",
        headers={
            "content-type": "audio/mpeg",
            "X-Model-Version": "taigi-2026.08",
            # 服務端把非 ASCII 標頭值 percent-encode 後才送出。
            "X-Spoken-Text": "%E5%92%B1%E4%BE%86",
            "X-Unfixable": "%F0%A8%91%A8",
        },
    )
    mock_post = MagicMock(return_value=mock_response)
    monkeypatch.setattr(adapter._client, "post", mock_post)

    res = adapter.synthesize(
        SynthesizeRequest(text="你好", voice_hint="teen-female-01")
    )

    assert res.audio_bytes == b"mock-mp3-bytes"
    assert res.content_type == "audio/mpeg"
    assert res.provider == "cosyvoice"
    assert res.route_target == "cosyvoice"
    assert res.raw_metadata["model_version"] == "taigi-2026.08"
    assert res.raw_metadata["spoken_text"] == "咱來"
    assert res.raw_metadata["unfixable"] == "𨑨"

    mock_post.assert_called_once_with(
        "http://10.9.0.35:50010/v1/synthesize",
        json={
            "text": "你好",
            "voice_id": "teen-female-01",
            "format": "mp3",
        },
        headers={"Authorization": "Bearer secret"},
    )


def test_cosyvoice_adapter_default_voice_and_no_auth_header(monkeypatch):
    config = TTSRouterConfig(
        _env_file=None,
        tts_cosyvoice_url=_COSYVOICE_URL,
        tts_cosyvoice_api_key="",
    )
    adapter = CosyVoiceAdapter(config)
    mock_post = MagicMock(
        return_value=httpx.Response(status_code=200, content=b"x"),
    )
    monkeypatch.setattr(adapter._client, "post", mock_post)

    adapter.synthesize(SynthesizeRequest(text="你好"))

    assert mock_post.call_args.kwargs["json"]["voice_id"] == COSYVOICE_DEFAULT_VOICE
    assert mock_post.call_args.kwargs["headers"] == {}


def test_cosyvoice_adapter_env_default_voice(monkeypatch):
    config = TTSRouterConfig(
        _env_file=None,
        tts_cosyvoice_url=_COSYVOICE_URL,
        tts_cosyvoice_default_voice="senior-male-01",
    )
    adapter = CosyVoiceAdapter(config)
    mock_post = MagicMock(
        return_value=httpx.Response(status_code=200, content=b"x"),
    )
    monkeypatch.setattr(adapter._client, "post", mock_post)

    adapter.synthesize(SynthesizeRequest(text="你好"))

    assert mock_post.call_args.kwargs["json"]["voice_id"] == "senior-male-01"


def test_cosyvoice_adapter_synthesis_http_error(monkeypatch):
    config = TTSRouterConfig(_env_file=None, tts_cosyvoice_url=_COSYVOICE_URL)
    adapter = CosyVoiceAdapter(config)

    mock_response = httpx.Response(
        status_code=400,
        json={"error": "voice_not_found", "message": "找不到語音 nope"},
    )
    monkeypatch.setattr(
        adapter._client, "post", MagicMock(return_value=mock_response),
    )

    with pytest.raises(CosyVoiceHTTPError) as exc_info:
        adapter.synthesize(SynthesizeRequest(text="你好", voice_hint="nope"))

    assert exc_info.value.status_code == 400
    assert "voice_not_found" in exc_info.value.detail


def test_cosyvoice_adapter_request_error_maps_to_503(monkeypatch):
    config = TTSRouterConfig(_env_file=None, tts_cosyvoice_url=_COSYVOICE_URL)
    adapter = CosyVoiceAdapter(config)
    monkeypatch.setattr(
        adapter._client,
        "post",
        MagicMock(side_effect=httpx.ConnectError("refused")),
    )

    with pytest.raises(CosyVoiceHTTPError) as exc_info:
        adapter.synthesize(SynthesizeRequest(text="你好"))

    assert exc_info.value.status_code == 503


@pytest.mark.parametrize(
    ("status_code", "expected"),
    [
        (400, REASON_BAD_REQUEST),
        (401, REASON_AUTH_ERROR),
        (429, REASON_RATE_LIMITED),
        (503, REASON_PROVIDER_UNAVAILABLE),
    ],
)
def test_classify_cosyvoice_error_by_status(status_code, expected):
    assert classify_cosyvoice_error(CosyVoiceHTTPError(status_code, "x")) == expected


def test_classify_cosyvoice_error_network():
    assert (
        classify_cosyvoice_error(httpx.ConnectError("refused"))
        == REASON_NETWORK_ERROR
    )
