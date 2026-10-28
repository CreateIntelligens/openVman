"""Keep one service address authoritative across HTTP and stream consumers."""

import pytest

from app.config import TTSRouterConfig
from app.gateway import asr_stream


def _config(**overrides):
    values = {
        "_env_file": None,
        "TTS_COSYVOICE_URL": "",
        "TTS_HANJI_CONVERT_URL": "",
        "TTS_HANJI_CONVERT_ENABLED": True,
        "asr_r2t2_url": "",
        "asr_r2t2_stream_url": "",
        "asr_r2t2_secret_key": "",
        "asr_r2t2_dev_url": "",
        "asr_r2t2_dev_stream_url": "",
        "asr_r2t2_dev_secret_key": "",
    }
    values.update(overrides)
    return TTSRouterConfig(**values)


@pytest.mark.parametrize("engine", ["r2t2", "r2t2_dev"])
@pytest.mark.parametrize(
    "base,expected",
    [
        ("http://asr:8040", "ws://asr:8040/asr_stream_api_v1"),
        ("https://asr.example/", "wss://asr.example/asr_stream_api_v1"),
        (
            "https://asr.example/services/speech/",
            "wss://asr.example/services/speech/asr_stream_api_v1",
        ),
        (
            "http://[2001:db8::35]:8040/hospital",
            "ws://[2001:db8::35]:8040/hospital/asr_stream_api_v1",
        ),
    ],
)
def test_r2t2_stream_address_follows_batch_base(engine, base, expected):
    cfg = _config(**{f"asr_{engine}_url": base})

    assert getattr(cfg, f"effective_asr_{engine}_stream_url") == expected
    assert getattr(cfg, f"asr_{engine}_stream_url") == ""


@pytest.mark.parametrize("engine", ["r2t2", "r2t2_dev"])
@pytest.mark.parametrize("base", ["", "ftp://asr:8040", "ws://asr:8040"])
def test_r2t2_does_not_guess_a_stream_address_from_an_invalid_base(engine, base):
    cfg = _config(**{f"asr_{engine}_url": base})

    assert getattr(cfg, f"effective_asr_{engine}_stream_url") == ""


@pytest.mark.parametrize("engine", ["r2t2", "r2t2_dev"])
def test_explicit_r2t2_stream_address_takes_priority(engine):
    cfg = _config(**{
        f"asr_{engine}_url": "https://batch.example/prefix",
        f"asr_{engine}_stream_url": "wss://stream.example:9000/custom",
    })

    assert getattr(cfg, f"effective_asr_{engine}_stream_url") == (
        "wss://stream.example:9000/custom"
    )


@pytest.mark.parametrize("engine", ["r2t2", "r2t2_dev"])
def test_copied_config_recomputes_derived_r2t2_address(engine):
    cfg = _config(**{f"asr_{engine}_url": "http://old:8040"})
    assert getattr(cfg, f"effective_asr_{engine}_stream_url") == (
        "ws://old:8040/asr_stream_api_v1"
    )

    changed = cfg.model_copy(update={
        f"asr_{engine}_url": "https://new.example/proxy/",
    })

    assert getattr(changed, f"effective_asr_{engine}_stream_url") == (
        "wss://new.example/proxy/asr_stream_api_v1"
    )


@pytest.mark.parametrize(
    "base,expected",
    [
        ("http://cosy:50010/v1", "http://cosy:50010/api/convert"),
        ("http://cosy:50010/v1/", "http://cosy:50010/api/convert"),
        (
            "https://voice.example/hospital/cosy/v1/",
            "https://voice.example/hospital/cosy/api/convert",
        ),
        (
            "http://[2001:db8::35]:50010/v1",
            "http://[2001:db8::35]:50010/api/convert",
        ),
        (
            "https://voice.example/service/",
            "https://voice.example/service/api/convert",
        ),
        (
            "https://voice.example/service/v10",
            "https://voice.example/service/v10/api/convert",
        ),
        ("", ""),
    ],
)
def test_dictionary_address_follows_cosy_service(base, expected):
    cfg = _config(TTS_COSYVOICE_URL=base)

    assert cfg.effective_tts_hanji_convert_url == expected
    assert cfg.tts_hanji_convert_url == ""


def test_explicit_dictionary_address_takes_priority():
    cfg = _config(
        TTS_COSYVOICE_URL="http://cosy:50010/v1",
        TTS_HANJI_CONVERT_URL="https://dictionary.example/custom",
    )

    assert cfg.effective_tts_hanji_convert_url == "https://dictionary.example/custom"


@pytest.mark.parametrize("override", ["", "https://dictionary.example/custom"])
def test_disabling_dictionary_conversion_overrides_every_address(override):
    cfg = _config(
        TTS_COSYVOICE_URL="http://cosy:50010/v1",
        TTS_HANJI_CONVERT_URL=override,
        TTS_HANJI_CONVERT_ENABLED=False,
    )

    assert cfg.effective_tts_hanji_convert_url == ""


def test_copied_config_recomputes_dictionary_address():
    cfg = _config(TTS_COSYVOICE_URL="http://old:50010/v1")
    assert cfg.effective_tts_hanji_convert_url == "http://old:50010/api/convert"

    changed = cfg.model_copy(update={
        "tts_cosyvoice_url": "https://new.example/cosy/v1/",
    })

    assert changed.effective_tts_hanji_convert_url == (
        "https://new.example/cosy/api/convert"
    )
    disabled = changed.model_copy(update={"tts_hanji_convert_enabled": False})
    assert disabled.effective_tts_hanji_convert_url == ""


@pytest.mark.parametrize(
    "engine,base_field,key_field,base,key,expected",
    [
        (
            "r2t2-live", "asr_r2t2_url", "asr_r2t2_secret_key",
            "https://main.example/speech", "main-key",
            "wss://main.example/speech/asr_stream_api_v1",
        ),
        (
            "r2t2-dev-live", "asr_r2t2_dev_url", "asr_r2t2_dev_secret_key",
            "http://[2001:db8::37]:8040", "dev-key",
            "ws://[2001:db8::37]:8040/asr_stream_api_v1",
        ),
    ],
)
def test_asr_stream_consumer_uses_derived_address_and_matching_key(
    engine, base_field, key_field, base, key, expected,
):
    cfg = _config(**{base_field: base, key_field: key})

    assert asr_stream._r2t2_stream_endpoint(cfg, engine) == (expected, key)
    assert asr_stream._r2t2_stream_endpoint(
        cfg.model_copy(update={key_field: ""}), engine,
    ) is None


def test_stream_engine_listing_recognizes_services_with_only_batch_addresses(
    monkeypatch,
):
    cfg = _config(
        asr_r2t2_url="https://main.example",
        asr_r2t2_secret_key="main-key",
        asr_r2t2_dev_url="http://dev:8040",
        asr_r2t2_dev_secret_key="dev-key",
    )
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    monkeypatch.setattr(asr_stream, "get_tts_config", lambda: cfg)

    assert asr_stream.configured_stream_engines() == ["r2t2-live", "r2t2-dev-live"]

    cfg = cfg.model_copy(update={"asr_r2t2_dev_secret_key": ""})
    assert asr_stream.configured_stream_engines() == ["r2t2-live"]

    cfg = cfg.model_copy(update={"asr_r2t2_url": ""})
    assert asr_stream.configured_stream_engines() == []
