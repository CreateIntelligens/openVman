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
        update={"asr_r2t2_url": "http://r2t2:8040/", "asr_r2t2_backup_url": ""},
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


class _Failing:
    def __init__(self, status):
        self.status = status

    def raise_for_status(self):
        import httpx

        request = httpx.Request("POST", "http://x")
        raise httpx.HTTPStatusError("boom", request=request, response=httpx.Response(self.status, request=request))


@pytest.fixture
def two_hosts(monkeypatch, tmp_path):
    """主機 .37、備援 .35；回傳每台的回應怎麼設與送了哪些請求。"""
    audio = tmp_path / "clip.wav"
    audio.write_bytes(b"RIFF")
    cfg = ingestion_audio.get_tts_config().model_copy(update={
        "asr_r2t2_url": "http://main:8803", "asr_r2t2_backup_url": "http://backup:8040",
        "asr_r2t2_backup_timeout_seconds": 20.0,
    })
    monkeypatch.setattr(ingestion_audio, "get_tts_config", lambda: cfg)
    calls = []
    behaviour = {}

    class Client:
        async def post(self, url, files, data=None, **kwargs):
            calls.append((url, kwargs.get("timeout")))
            result = behaviour[url.split("/transcribe")[0]]
            if isinstance(result, Exception):
                raise result
            return result

    monkeypatch.setattr(ingestion_audio._http, "get", lambda: Client())
    return str(audio), behaviour, calls


def test_backup_host_answers_when_the_main_host_is_down(two_hosts):
    import httpx

    audio, behaviour, calls = two_hosts
    behaviour["http://main:8803"] = httpx.ConnectError("refused")
    behaviour["http://backup:8040"] = _Response({"status": "success", "text": "备援"})

    assert asyncio.run(ingestion_audio._transcribe_r2t2(audio, "t")) == "備援"
    # 備援 .35 同時多句會卡死：只等設定的秒數，等不到就交給下一家引擎。
    assert calls == [("http://main:8803/transcribe", None), ("http://backup:8040/transcribe", 20.0)]


def test_backup_host_answers_when_the_main_host_errors(two_hosts):
    audio, behaviour, calls = two_hosts
    behaviour["http://main:8803"] = _Failing(503)
    behaviour["http://backup:8040"] = _Response({"status": "success", "text": "好"})
    assert asyncio.run(ingestion_audio._transcribe_r2t2(audio, "t")) == "好"


def test_client_errors_do_not_retry_on_the_backup(two_hosts):
    import httpx

    audio, behaviour, calls = two_hosts
    behaviour["http://main:8803"] = _Failing(400)
    with pytest.raises(httpx.HTTPStatusError):
        asyncio.run(ingestion_audio._transcribe_r2t2(audio, "t"))
    assert len(calls) == 1


def test_backup_alone_still_joins_the_chain():
    cfg = ingestion_audio.get_tts_config().model_copy(update={
        "asr_provider": "breeze", "asr_breeze_url": "http://b", "asr_r2t2_url": "",
        "asr_r2t2_backup_url": "http://backup", "asr_xiaomi_url": "", "asr_sensevoice_url": "",
        "whisper_api_key": "",
    })
    assert ingestion_audio._resolve_chain(cfg, "r2t2") == ["r2t2", "breeze"]
