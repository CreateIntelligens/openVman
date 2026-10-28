"""Exercise dictionary selection at the actual synthesis boundaries."""

from unittest.mock import AsyncMock, MagicMock

import httpx
import pytest

from app.config import TTSRouterConfig
from app.providers.base import NormalizedTTSResult, SynthesizeRequest
from app.providers.cosyvoice_adapter import CosyVoiceAdapter, CosyVoiceHTTPError
from app.providers.voxcpm_adapter import VoxCPMAdapter
from app.service import TTSRouterService
from app.tts_hanji import HanjiConverter

_CONVERT_URL = "http://dictionary:50010/api/convert"
_SOURCE = "明天我們一起買東西。"
_CONVERTED = {"v1": "明仔載咱做伙買物件。", "v6": "明仔載咱鬥陣買物件。"}


def _config(**overrides):
    values = {
        "_env_file": None,
        "TTS_HANJI_CONVERT_ENABLED": True,
        "tts_hanji_convert_url": _CONVERT_URL,
        "tts_indextts_url": "",
        "tts_voxcpm_url": "http://vox:8800",
        "tts_cosyvoice_url": "http://cosy:50010/v1",
        "tts_gemini_url": "",
        "edge_tts_enabled": True,
    }
    values.update(overrides)
    # BaseSettings otherwise prefers the environment's alias over a name key.
    values["TTS_HANJI_CONVERT_URL"] = values.pop("tts_hanji_convert_url")
    return TTSRouterConfig(**values)


@pytest.fixture(autouse=True)
def _healthy_vox(monkeypatch):
    monkeypatch.setattr(VoxCPMAdapter, "_cached_health", lambda self: "")


def _dictionary(monkeypatch, *, payload=None, status=200, error=None):
    calls = []

    def get(client, url, *, params, **kwargs):
        calls.append((url, dict(params)))
        if error:
            raise error
        data = payload
        if data is None:
            version = params["version"]
            data = {"converted": _CONVERTED[version], "version": version}
        return httpx.Response(
            status,
            json=data,
            request=httpx.Request("GET", url, params=params),
        )

    async def get_async(client, url, **kwargs):
        return get(client, url, **kwargs)

    monkeypatch.setattr(httpx.Client, "get", get)
    monkeypatch.setattr(httpx.AsyncClient, "get", get_async)
    return calls


def test_cosy_synthesis_uses_the_derived_dictionary_endpoint(monkeypatch):
    calls = _dictionary(monkeypatch)
    adapter = CosyVoiceAdapter(_config(tts_hanji_convert_url=""))
    post = MagicMock(return_value=httpx.Response(200, content=b"audio"))
    monkeypatch.setattr(adapter._client, "post", post)

    adapter.synthesize(SynthesizeRequest(text=_SOURCE, locale="nan"))

    assert calls[0][0] == "http://cosy:50010/api/convert"
    assert post.call_args.kwargs["json"]["text"] == _CONVERTED["v1"]
    assert post.call_args.kwargs["json"]["annotate"] == "none"


@pytest.mark.parametrize("version", ["v1", "v6"])
def test_converter_requests_explicit_version_without_logging(monkeypatch, version):
    calls = _dictionary(monkeypatch)

    result = HanjiConverter(_config()).convert(_SOURCE, version)

    assert result == _CONVERTED[version]
    assert calls == [
        (
            _CONVERT_URL,
            {"text": _SOURCE, "version": version, "log_unknown": "false"},
        ),
    ]


@pytest.mark.asyncio
async def test_async_converter_uses_the_same_dictionary_contract(monkeypatch):
    calls = _dictionary(monkeypatch)

    result = await HanjiConverter(_config()).convert_async(_SOURCE, "v6")

    assert result == _CONVERTED["v6"]
    assert calls[0][1] == {
        "text": _SOURCE, "version": "v6", "log_unknown": "false",
    }


@pytest.mark.asyncio
async def test_disabled_converter_never_contacts_a_dictionary(monkeypatch):
    calls = _dictionary(monkeypatch)
    converter = HanjiConverter(_config(TTS_HANJI_CONVERT_ENABLED=False))

    assert converter.convert(_SOURCE, "v1") == _SOURCE
    assert await converter.convert_async(_SOURCE, "v6") == _SOURCE
    assert calls == []


@pytest.mark.parametrize(
    "payload",
    [
        {"version": "v5", "converted": "另一版的內容"},
        {"version": "v6", "converted": ""},
        {"version": "v6", "converted": "  "},
        {"version": "v6", "converted": None},
        {"version": "v6", "converted": ["台文"]},
        {"converted": "缺少版本"},
        [],
    ],
)
def test_invalid_dictionary_response_is_rejected(monkeypatch, payload):
    _dictionary(monkeypatch, payload=payload)

    with pytest.raises(RuntimeError):
        HanjiConverter(_config()).convert(_SOURCE, "v6")


@pytest.mark.parametrize("async_mode", [False, True])
@pytest.mark.asyncio
async def test_dictionary_http_errors_are_not_disguised_as_success(
    monkeypatch, async_mode,
):
    _dictionary(monkeypatch, status=503)
    converter = HanjiConverter(_config())

    with pytest.raises(httpx.HTTPStatusError):
        if async_mode:
            await converter.convert_async(_SOURCE, "v6")
        else:
            converter.convert(_SOURCE, "v6")


@pytest.mark.asyncio
async def test_malformed_dictionary_json_is_rejected_in_both_modes(monkeypatch):
    def get(*args, **kwargs):
        return httpx.Response(
            200, content=b"not-json", request=httpx.Request("GET", _CONVERT_URL),
        )

    async def get_async(*args, **kwargs):
        return get(*args, **kwargs)

    monkeypatch.setattr(httpx.Client, "get", get)
    monkeypatch.setattr(httpx.AsyncClient, "get", get_async)
    converter = HanjiConverter(_config())
    with pytest.raises(RuntimeError):
        converter.convert(_SOURCE, "v1")
    with pytest.raises(RuntimeError):
        await converter.convert_async(_SOURCE, "v6")


@pytest.mark.asyncio
async def test_vox_dictionary_timeout_does_not_start_audio_stream(monkeypatch):
    from app.providers.voxcpm_adapter import VoxCPMHTTPError

    _dictionary(monkeypatch, error=httpx.ReadTimeout("word table timeout"))
    adapter = VoxCPMAdapter(_config())
    send = AsyncMock()
    monkeypatch.setattr(adapter, "_send_stream", send)

    with pytest.raises(VoxCPMHTTPError) as caught:
        await adapter.open_stream(SynthesizeRequest(text=_SOURCE, locale="nan"))

    assert caught.value.status_code == 503
    send.assert_not_called()


@pytest.mark.parametrize("locale", ["nan", "nan-TW"])
def test_vox_buffered_sends_v6_text_only_for_taiwanese(monkeypatch, locale):
    calls = _dictionary(monkeypatch)
    adapter = VoxCPMAdapter(_config())
    post = MagicMock(return_value=httpx.Response(200, content=b"audio"))
    monkeypatch.setattr(adapter._client, "post", post)

    adapter.synthesize(SynthesizeRequest(text=_SOURCE, locale=locale))

    assert calls[0][1]["version"] == "v6"
    assert post.call_args.kwargs["json"]["text"] == _CONVERTED["v6"]


def test_vox_mandarin_does_not_apply_taiwanese_dictionary(monkeypatch):
    calls = _dictionary(monkeypatch)
    adapter = VoxCPMAdapter(_config())
    post = MagicMock(return_value=httpx.Response(200, content=b"audio"))
    monkeypatch.setattr(adapter._client, "post", post)

    adapter.synthesize(SynthesizeRequest(text=_SOURCE, locale="zh-TW"))

    assert calls == []
    assert post.call_args.kwargs["json"]["text"] == _SOURCE


@pytest.mark.asyncio
@pytest.mark.parametrize("version", ["v6", "v1"])
async def test_vox_streaming_uses_configured_dictionary(monkeypatch, version):
    calls = _dictionary(monkeypatch)
    adapter = VoxCPMAdapter(_config(TTS_VOXCPM_HANJI_VERSION=version))
    send = AsyncMock(return_value="accepted-stream")
    monkeypatch.setattr(adapter, "_send_stream", send)

    stream = await adapter.open_stream(
        SynthesizeRequest(text=_SOURCE, locale="nan"), sample_rate=16000,
    )

    assert stream == "accepted-stream"
    assert calls[0][1]["version"] == version
    assert send.call_args.args[0]["text"] == _CONVERTED[version]
    assert send.call_args.args[0]["sample_rate"] == "16000"


def test_cosy_sends_v1_text_and_disables_upstream_reannotation(monkeypatch):
    calls = _dictionary(monkeypatch)
    adapter = CosyVoiceAdapter(_config())
    post = MagicMock(return_value=httpx.Response(200, content=b"audio"))
    monkeypatch.setattr(adapter._client, "post", post)

    adapter.synthesize(SynthesizeRequest(text=_SOURCE))

    assert calls[0][1]["version"] == "v1"
    payload = post.call_args.kwargs["json"]
    assert payload["text"] == _CONVERTED["v1"]
    assert payload["annotate"] == "none"


def test_disabled_conversion_keeps_cosy_upstream_default(monkeypatch):
    calls = _dictionary(monkeypatch)
    adapter = CosyVoiceAdapter(_config(TTS_HANJI_CONVERT_ENABLED=False))
    post = MagicMock(return_value=httpx.Response(200, content=b"audio"))
    monkeypatch.setattr(adapter._client, "post", post)

    adapter.synthesize(SynthesizeRequest(text=_SOURCE))

    assert calls == []
    payload = post.call_args.kwargs["json"]
    assert payload["text"] == _SOURCE
    assert "annotate" not in payload


def test_dictionary_failure_prevents_synthesis(monkeypatch):
    _dictionary(monkeypatch, payload={"version": "v5", "converted": "錯版"})
    adapter = CosyVoiceAdapter(_config())
    post = MagicMock(return_value=httpx.Response(200, content=b"audio"))
    monkeypatch.setattr(adapter._client, "post", post)

    with pytest.raises(CosyVoiceHTTPError) as caught:
        adapter.synthesize(SynthesizeRequest(text=_SOURCE, locale="nan"))

    assert caught.value.status_code == 503
    post.assert_not_called()


@pytest.mark.parametrize(
    "adapter_class,override,version",
    [
        (VoxCPMAdapter, {"TTS_VOXCPM_HANJI_VERSION": "v1"}, "v1"),
        (CosyVoiceAdapter, {"TTS_COSYVOICE_HANJI_VERSION": "v6"}, "v6"),
    ],
)
def test_engine_dictionary_version_can_be_configured(
    monkeypatch, adapter_class, override, version,
):
    calls = _dictionary(monkeypatch)
    adapter = adapter_class(_config(**override))
    post = MagicMock(return_value=httpx.Response(200, content=b"audio"))
    monkeypatch.setattr(adapter._client, "post", post)

    adapter.synthesize(SynthesizeRequest(text=_SOURCE, locale="nan"))

    assert calls[0][1]["version"] == version
    assert post.call_args.kwargs["json"]["text"] == _CONVERTED[version]


def test_partner_and_edge_each_receive_original_text(monkeypatch):
    calls = _dictionary(monkeypatch)
    service = TTSRouterService(_config())
    cosy_post = MagicMock(return_value=httpx.Response(503, text="cosy down"))
    vox_post = MagicMock(return_value=httpx.Response(503, text="vox down"))
    monkeypatch.setattr(service.cosyvoice_adapter._client, "post", cosy_post)
    monkeypatch.setattr(service.voxcpm_adapter._client, "post", vox_post)
    edge = MagicMock(
        return_value=NormalizedTTSResult(
            audio_bytes=b"audio",
            content_type="audio/mpeg",
            sample_rate=24000,
            provider="edge-tts",
            route_kind="provider",
            route_target="edge-tts",
            latency_ms=1,
        ),
    )
    monkeypatch.setattr(service.edge_adapter, "synthesize", edge)

    output = service.synthesize(
        SynthesizeRequest(text=_SOURCE, locale="nan"),
        provider="cosyvoice",
        partners=(("voxcpm", "voxcpm2-cosy-young-female-02"),),
    )

    assert output.result.provider == "edge-tts"
    assert output.fallback is True
    assert [params for _, params in calls] == [
        {"text": _SOURCE, "version": "v1", "log_unknown": "false"},
        {"text": _SOURCE, "version": "v6", "log_unknown": "false"},
    ]
    assert cosy_post.call_args.kwargs["json"]["text"] == _CONVERTED["v1"]
    assert vox_post.call_args.kwargs["json"]["text"] == _CONVERTED["v6"]
    assert edge.call_args.args[0].text == _SOURCE
