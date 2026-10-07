"""Confucius4-R2T2 batch transcription."""

from __future__ import annotations

import asyncio

import pytest

from app.gateway import ingestion_audio


class _Response:
    def __init__(self, body):
        self._body = body

    def raise_for_status(self):
        pass

    def json(self):
        return self._body


@pytest.fixture
def r2t2(monkeypatch, tmp_path):
    audio = tmp_path / "clip.wav"
    audio.write_bytes(b"RIFF")
    cfg = ingestion_audio.get_tts_config().model_copy(
        update={"asr_r2t2_url": "http://r2t2:8040/", "asr_r2t2_dev_url": ""},
    )
    monkeypatch.setattr(ingestion_audio, "get_tts_config", lambda: cfg)
    sent = []

    def answer(body):
        class Client:
            async def post(self, url, files, data=None):
                sent.append((url, sorted(files), data))
                return _Response(body)

        monkeypatch.setattr(ingestion_audio._http, "get", lambda: Client())

    return str(audio), sent, answer


def test_r2t2_sends_the_glossary_and_returns_traditional_chinese(r2t2):
    audio, sent, answer = r2t2
    answer({"status": "success", "text": "请问DIVA有搅拌器吗", "cost_ms": 412.0})

    text = asyncio.run(ingestion_audio._transcribe_r2t2(audio, "t", prompt="沉水泵、DIVA"))

    assert text == "請問DIVA有攪拌器嗎"
    # 沒指定語言分流就當華語；詞表放 context。
    assert sent == [("http://r2t2:8040/transcribe", ["file"], {"language": "Chinese", "context": "沉水泵、DIVA"})]


@pytest.mark.parametrize(
    ("routes", "language", "reply", "text"),
    [
        # R2T2 不會自己判斷語言，西日韓當中文解碼會整句壞掉（2026-10-05 批次實測，串流同）。
        (["es"], "Spanish", "¿Qué bomba?", "¿Qué bomba?"),
        # 指定日文不轉繁：「学校」是日文漢字，不是簡體。
        (["ja"], "Japanese", "学校のポンプ", "学校のポンプ"),
        (["nan", "zh"], "Chinese", "请问", "請問"),
        (["zh", "en", "es"], "zhen", "请问", "請問"),
        (None, "Chinese", "请问", "請問"),
    ],
)
def test_transcribe_decodes_in_the_project_language(r2t2, routes, language, reply, text):
    audio, sent, answer = r2t2
    answer({"status": "success", "text": reply})

    result = asyncio.run(ingestion_audio.transcribe(audio, "t", "r2t2", routes=routes))

    assert (result.provider, result.content) == ("r2t2", text)
    assert sent[0][2]["language"] == language


def test_r2t2_error_status_falls_back_instead_of_returning_nothing(r2t2):
    audio, _, answer = r2t2
    answer({"status": "error", "message": "Model not loaded"})

    with pytest.raises(RuntimeError, match="Model not loaded"):
        asyncio.run(ingestion_audio._transcribe_r2t2(audio, "t"))


def test_r2t2_joins_the_chain_only_when_configured():
    cfg = ingestion_audio.get_tts_config().model_copy(update={
        "asr_provider": "breeze", "asr_breeze_url": "http://b", "asr_r2t2_url": "",
        "asr_sensevoice_url": "", "whisper_api_key": "",
    })
    assert "r2t2" not in ingestion_audio._resolve_chain(cfg)
    configured = cfg.model_copy(update={"asr_r2t2_url": "http://r2t2"})
    # 使用者選了 r2t2 就排第一，Breeze 留著當備援。
    assert ingestion_audio._resolve_chain(configured, "r2t2") == ["r2t2", "breeze"]



@pytest.fixture
def dev_host(monkeypatch, tmp_path):
    audio = tmp_path / "clip.wav"
    audio.write_bytes(b"RIFF")
    cfg = ingestion_audio.get_tts_config().model_copy(update={
        "asr_r2t2_url": "http://main:8803", "asr_r2t2_dev_url": "http://dev:8040/",
        "asr_r2t2_dev_timeout_seconds": 20.0,
    })
    monkeypatch.setattr(ingestion_audio, "get_tts_config", lambda: cfg)
    calls = []

    class Client:
        async def post(self, url, files, data=None, **kwargs):
            calls.append((url, kwargs.get("timeout")))
            return _Response({"status": "success", "text": "测试机"})

    monkeypatch.setattr(ingestion_audio._http, "get", lambda: Client())
    return str(audio), calls


def test_dev_engine_uses_the_dev_host_with_a_short_timeout(dev_host):
    audio, calls = dev_host
    assert asyncio.run(ingestion_audio._transcribe_r2t2_dev(audio, "t")) == "測試機"
    # .35 同時多句會卡死：只等設定的秒數，等不到就交給下一家引擎。
    assert calls == [("http://dev:8040/transcribe", 20.0)]


def test_main_engine_never_touches_the_dev_host(dev_host):
    audio, calls = dev_host
    asyncio.run(ingestion_audio._transcribe_r2t2(audio, "t"))
    assert calls == [("http://main:8803/transcribe", None)]


def test_dev_engine_is_only_used_when_chosen():
    """測試機不當別人的備援：沒選它就不會排進順序。"""
    cfg = ingestion_audio.get_tts_config().model_copy(update={
        "asr_provider": "breeze", "asr_breeze_url": "http://b", "asr_r2t2_url": "http://r",
        "asr_r2t2_dev_url": "http://dev", "asr_sensevoice_url": "",
        "whisper_api_key": "",
    })
    assert ingestion_audio._resolve_chain(cfg) == ["breeze", "r2t2"]
    assert ingestion_audio._resolve_chain(cfg, "r2t2") == ["r2t2", "breeze"]
    assert ingestion_audio._resolve_chain(cfg, "r2t2-dev") == ["r2t2-dev", "breeze", "r2t2"]
