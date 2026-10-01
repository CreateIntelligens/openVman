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
    cfg = ingestion_audio.get_tts_config().model_copy(update={"asr_r2t2_url": "http://r2t2:8040/"})
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
    # 兩套部署都認得 Chinese（.37 收到 zhen 會 500）；詞表放 context。
    assert sent == [("http://r2t2:8040/transcribe", ["file"], {"language": "Chinese", "context": "沉水泵、DIVA"})]


def test_r2t2_error_status_falls_back_instead_of_returning_nothing(r2t2):
    audio, _, answer = r2t2
    answer({"status": "error", "message": "Model not loaded"})

    with pytest.raises(RuntimeError, match="Model not loaded"):
        asyncio.run(ingestion_audio._transcribe_r2t2(audio, "t"))


def test_r2t2_joins_the_chain_only_when_configured():
    cfg = ingestion_audio.get_tts_config().model_copy(update={
        "asr_provider": "breeze", "asr_breeze_url": "http://b", "asr_r2t2_url": "",
        "asr_xiaomi_url": "", "asr_sensevoice_url": "", "whisper_api_key": "",
    })
    assert "r2t2" not in ingestion_audio._resolve_chain(cfg)
    configured = cfg.model_copy(update={"asr_r2t2_url": "http://r2t2"})
    # 使用者選了 r2t2 就排第一，Breeze 留著當備援。
    assert ingestion_audio._resolve_chain(configured, "r2t2") == ["r2t2", "breeze"]
