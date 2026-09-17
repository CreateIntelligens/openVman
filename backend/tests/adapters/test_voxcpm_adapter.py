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
    equivalent_preset,
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
        "http://10.9.0.37:8800/api/v1/synthesize",
        data={
            "engine_id": "voxcpm2",
            "text": "你好",
            "reference_preset_id": "cosy-teen-female-01",
            "cfg_value": "2.0",
            "inference_timesteps": "30",
            "normalize": "true",
            "denoise": "false",
            "speed": "1.0",
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

    # 預設聲線同樣要去掉 voxcpm2- 前綴才是 catalog 裡的 reference preset id。
    assert mock_post.call_args.kwargs["data"]["reference_preset_id"] == (
        VOXCPM_DEFAULT_VOICE.removeprefix("voxcpm2-")
    )
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

    assert mock_post.call_args.kwargs["data"]["reference_preset_id"] == (
        "barbet-hung-yi-lee"
    )


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


@pytest.mark.asyncio
async def test_voxcpm_adapter_open_stream_success(monkeypatch):
    config = TTSRouterConfig(
        _env_file=None,
        tts_voxcpm_url="http://10.9.0.37:8800/",
        tts_voxcpm_api_key="secret",
    )
    adapter = VoxCPMAdapter(config)

    class FakeResponse:
        status_code = 200

        async def aiter_bytes(self):
            yield b"RIFF-header"
            yield b"pcm-chunk-1"
            yield b"pcm-chunk-2"

        async def aclose(self):
            pass

    class FakeAsyncClient:
        def __init__(self, *args, **kwargs):
            self.closed = False

        def build_request(self, method, url, data=None, headers=None):
            return {"method": method, "url": url, "data": data, "headers": headers}

        async def send(self, req, stream=False):
            assert req["method"] == "POST"
            assert req["url"] == "http://10.9.0.37:8800/api/v1/synthesize/stream"
            assert req["data"]["engine_id"] == "voxcpm2"
            assert req["data"]["text"] == "你好"
            assert req["data"]["reference_preset_id"] == "cosy-teen-female-01"
            assert req["headers"] == {"Authorization": "Bearer secret"}
            assert stream is True
            return FakeResponse()

        async def aclose(self):
            self.closed = True

    monkeypatch.setattr(httpx, "AsyncClient", FakeAsyncClient)

    stream = await adapter.open_stream(
        SynthesizeRequest(text="你好", voice_hint="voxcpm2-cosy-teen-female-01")
    )
    chunks = [chunk async for chunk in stream]
    assert chunks == [b"RIFF-header", b"pcm-chunk-1", b"pcm-chunk-2"]


@pytest.mark.asyncio
async def test_voxcpm_adapter_open_stream_http_error(monkeypatch):
    config = TTSRouterConfig(_env_file=None, tts_voxcpm_url=_VOXCPM_URL)
    adapter = VoxCPMAdapter(config)

    class FakeErrorResponse:
        status_code = 400

        async def aread(self):
            return b"preset not found"

        async def aclose(self):
            pass

    class FakeAsyncClient:
        def __init__(self, *args, **kwargs):
            pass

        def build_request(self, method, url, **kwargs):
            return {}

        async def send(self, req, stream=False):
            return FakeErrorResponse()

        async def aclose(self):
            pass

    monkeypatch.setattr(httpx, "AsyncClient", FakeAsyncClient)

    with pytest.raises(VoxCPMHTTPError) as exc_info:
        await adapter.open_stream(SynthesizeRequest(text="你好"))

    assert exc_info.value.status_code == 400
    assert "preset not found" in exc_info.value.detail


@pytest.mark.asyncio
async def test_voxcpm_adapter_open_stream_network_error(monkeypatch):
    config = TTSRouterConfig(_env_file=None, tts_voxcpm_url=_VOXCPM_URL)
    adapter = VoxCPMAdapter(config)

    class FakeAsyncClient:
        def __init__(self, *args, **kwargs):
            pass

        def build_request(self, method, url, **kwargs):
            return {}

        async def send(self, req, stream=False):
            raise httpx.ConnectError("network down")

        async def aclose(self):
            pass

    monkeypatch.setattr(httpx, "AsyncClient", FakeAsyncClient)

    with pytest.raises(VoxCPMHTTPError) as exc_info:
        await adapter.open_stream(SynthesizeRequest(text="你好"))

    assert exc_info.value.status_code == 503


def test_both_endpoints_send_the_same_form_fields():
    """批次與串流必須送同一組欄位，只差在路徑。

    這兩條路徑先前各寫各的，結果批次那份帶著錯的 URL 與 JSON body 沉了幾個
    月：串流有人用所以是對的，批次沒人用所以沒人發現。共用 _build_payload
    之後，這個測試確保它們不會再各自漂移。
    """
    config = TTSRouterConfig(_env_file=None, tts_voxcpm_url=_VOXCPM_URL)
    adapter = VoxCPMAdapter(config)
    request = SynthesizeRequest(text="你好", voice_hint="voxcpm2-cosy-teen-female-01")

    payload = adapter._build_payload(request)

    assert payload["engine_id"] == "voxcpm2"
    assert payload["reference_preset_id"] == "cosy-teen-female-01"
    assert adapter._url.endswith("/api/v1/synthesize")
    assert adapter._stream_url == f"{adapter._url}/stream"


class TestEquivalentPreset:
    """CosyVoice 聲線換成 VoxCPM preset，讓整段合成的請求能走串流。"""

    def test_maps_shared_taiwanese_voices(self):
        assert equivalent_preset("young-female-01") == "cosy-young-female-01"
        assert equivalent_preset("teen-male-02") == "cosy-teen-male-02"
        assert equivalent_preset("senior-female-01") == "cosy-senior-female-01"

    def test_cosyvoice_only_voices_have_no_equivalent(self):
        """young-female-02（Hayley）只有 CosyVoice 有；硬換會唸成別人的聲音。"""
        assert equivalent_preset("young-female-02") == ""
        assert equivalent_preset("child-female-02") == ""

    def test_voxcpm_voices_are_not_remapped(self):
        """已經是 VoxCPM 的聲線不該再加一層 cosy- 前綴。"""
        assert equivalent_preset("voxcpm2-cosy-young-female-01") == ""

    def test_blank_voice_has_no_equivalent(self):
        assert equivalent_preset("") == ""

    def test_every_mapped_preset_exists_upstream(self):
        """對應表不能編造 preset：每個值都要能被 _resolve_reference_preset 還原。"""
        from app.providers.voxcpm_adapter import _VOXCPM_PRESETS

        for voice in ("young-female-01", "teen-male-01", "child-male-02"):
            assert equivalent_preset(voice) in _VOXCPM_PRESETS
