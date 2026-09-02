from unittest.mock import MagicMock

import httpx
import pytest

from app.config import TTSRouterConfig
from app.providers.base import SynthesizeRequest
from app.providers.error_mapping import (
    REASON_AUTH_ERROR,
    REASON_BAD_REQUEST,
    REASON_NETWORK_ERROR,
    REASON_PROVIDER_UNAVAILABLE,
    REASON_RATE_LIMITED,
    classify_voxcpm_error,
)
from app.providers.voxcpm_adapter import (
    VOXCPM_DEFAULT_VOICE,
    VoxCPMAdapter,
    VoxCPMHTTPError,
)

_VOXCPM_URL = "http://voxcpm:8800"


def test_voxcpm_adapter_disabled_by_default():
    config = TTSRouterConfig(_env_file=None, tts_voxcpm_url="")
    adapter = VoxCPMAdapter(config)
    assert adapter.enabled is False
    assert adapter.provider_name == "voxcpm"


def test_voxcpm_adapter_synthesis_success(monkeypatch):
    config = TTSRouterConfig(
        _env_file=None,
        tts_voxcpm_url="http://10.9.0.37:8800/",
        tts_voxcpm_api_key="secret",
    )
    adapter = VoxCPMAdapter(config)

    mock_response = httpx.Response(
        status_code=200,
        content=b"mock-mp3-bytes",
        headers={"content-type": "audio/mpeg", "X-Request-ID": "abc"},
    )
    mock_post = MagicMock(return_value=mock_response)
    monkeypatch.setattr(adapter._client, "post", mock_post)

    res = adapter.synthesize(
        SynthesizeRequest(text="你好", voice_hint="voxcpm2-cosy-teen-female-01")
    )

    assert res.audio_bytes == b"mock-mp3-bytes"
    assert res.content_type == "audio/mpeg"
    assert res.provider == "voxcpm"
    assert res.route_target == "voxcpm"
    assert res.raw_metadata["request_id"] == "abc"

    mock_post.assert_called_once_with(
        "http://10.9.0.37:8800/api/v1/tts/synthesize",
        json={
            "text": "你好",
            "voice_id": "voxcpm2-cosy-teen-female-01",
            "format": "mp3",
        },
        headers={"Authorization": "Bearer secret"},
    )


def test_voxcpm_adapter_default_voice_and_no_auth_header(monkeypatch):
    config = TTSRouterConfig(
        _env_file=None,
        tts_voxcpm_url=_VOXCPM_URL,
        tts_voxcpm_api_key="",
    )
    adapter = VoxCPMAdapter(config)
    mock_post = MagicMock(
        return_value=httpx.Response(status_code=200, content=b"x"),
    )
    monkeypatch.setattr(adapter._client, "post", mock_post)

    adapter.synthesize(SynthesizeRequest(text="你好"))

    assert mock_post.call_args.kwargs["json"]["voice_id"] == VOXCPM_DEFAULT_VOICE
    assert mock_post.call_args.kwargs["headers"] == {}


def test_voxcpm_adapter_env_default_voice(monkeypatch):
    config = TTSRouterConfig(
        _env_file=None,
        tts_voxcpm_url=_VOXCPM_URL,
        tts_voxcpm_default_voice="barbet-hung-yi-lee",
    )
    adapter = VoxCPMAdapter(config)
    mock_post = MagicMock(
        return_value=httpx.Response(status_code=200, content=b"x"),
    )
    monkeypatch.setattr(adapter._client, "post", mock_post)

    adapter.synthesize(SynthesizeRequest(text="你好"))

    assert mock_post.call_args.kwargs["json"]["voice_id"] == "barbet-hung-yi-lee"


def test_voxcpm_adapter_synthesis_http_error(monkeypatch):
    config = TTSRouterConfig(_env_file=None, tts_voxcpm_url=_VOXCPM_URL)
    adapter = VoxCPMAdapter(config)

    mock_response = httpx.Response(
        status_code=400,
        json={"error": "voice_not_found", "message": "找不到語音 nope"},
    )
    monkeypatch.setattr(adapter._client, "post", MagicMock(return_value=mock_response))

    with pytest.raises(VoxCPMHTTPError) as exc_info:
        adapter.synthesize(SynthesizeRequest(text="你好", voice_hint="nope"))

    assert exc_info.value.status_code == 400
    assert "voice_not_found" in exc_info.value.detail


def test_voxcpm_adapter_request_error_maps_to_503(monkeypatch):
    config = TTSRouterConfig(_env_file=None, tts_voxcpm_url=_VOXCPM_URL)
    adapter = VoxCPMAdapter(config)
    monkeypatch.setattr(
        adapter._client,
        "post",
        MagicMock(side_effect=httpx.ConnectError("refused")),
    )

    with pytest.raises(VoxCPMHTTPError) as exc_info:
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
def test_classify_voxcpm_error_by_status(status_code, expected):
    assert classify_voxcpm_error(VoxCPMHTTPError(status_code, "x")) == expected


def test_classify_voxcpm_error_network():
    assert classify_voxcpm_error(httpx.ConnectError("refused")) == REASON_NETWORK_ERROR
