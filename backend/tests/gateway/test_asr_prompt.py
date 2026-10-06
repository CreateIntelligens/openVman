"""The project's speech glossary reaches the ASR engines that take a prompt."""

from __future__ import annotations

import asyncio
import types

import pytest

from app import asr_glossary
from app.gateway import ingestion_audio


class _Response:
    def __init__(self, body):
        self._body = body

    def raise_for_status(self):
        pass

    def json(self):
        return self._body


def test_breeze_gets_the_glossary_as_a_form_field(monkeypatch, tmp_path):
    audio = tmp_path / "clip.wav"
    audio.write_bytes(b"RIFF")
    cfg = ingestion_audio.get_tts_config().model_copy(update={"asr_breeze_url": "http://breeze"})
    monkeypatch.setattr(ingestion_audio, "get_tts_config", lambda: cfg)
    sent = []

    class Client:
        async def post(self, url, files, data=None):
            sent.append(data)
            return _Response({"text": "污泥泵有幾種型號"})

    monkeypatch.setattr(ingestion_audio._http, "get", lambda: Client())
    text = asyncio.run(ingestion_audio._transcribe_breeze(str(audio), "t", prompt="沉水泵、污泥泵"))
    asyncio.run(ingestion_audio._transcribe_breeze(str(audio), "t"))

    assert text == "污泥泵有幾種型號"
    # 沒詞表時不送欄位：Breeze 舊版與沒帶 prompt 的批次行為不變。
    assert sent == [{"prompt": "沉水泵、污泥泵"}, None]


def test_transcribe_hands_the_prompt_to_the_engine(monkeypatch, tmp_path):
    seen = {}

    async def engine(file_path, trace_id, prompt=""):
        seen["prompt"] = prompt
        return "ok"

    cfg = ingestion_audio.get_tts_config().model_copy(update={"asr_breeze_url": "http://breeze", "asr_provider": "breeze"})
    monkeypatch.setattr(ingestion_audio, "get_tts_config", lambda: cfg)
    monkeypatch.setitem(ingestion_audio._TRANSCRIBERS, "breeze", engine)
    result = asyncio.run(ingestion_audio.transcribe(str(tmp_path / "a.wav"), "t", "breeze", prompt="DIVA"))
    assert result.content == "ok" and seen["prompt"] == "DIVA"


@pytest.fixture
def brain(monkeypatch):
    asr_glossary._cache.clear()
    monkeypatch.setattr(asr_glossary, "resolve_project", lambda current, pid: pid or None)
    calls = []

    def answer(body=None, error=None):
        class Client:
            async def get(self, url, params, headers):
                calls.append(params["project_id"])
                if error:
                    raise error
                return _Response(body)
        monkeypatch.setattr(asr_glossary._http, "get", lambda: Client())

    return types.SimpleNamespace(answer=answer, calls=calls)


def test_glossary_is_fetched_once_per_project_and_cached(brain):
    brain.answer({"terms": "沉水泵、DIVA"})
    account = types.SimpleNamespace()
    assert asyncio.run(asr_glossary.project_asr_prompt(account, "p1")) == "沉水泵、DIVA"
    assert asyncio.run(asr_glossary.project_asr_prompt(account, "p1")) == "沉水泵、DIVA"
    assert brain.calls == ["p1"]


def test_no_project_or_brain_down_means_no_prompt(brain):
    account = types.SimpleNamespace()
    brain.answer(error=ConnectionError("down"))
    assert asyncio.run(asr_glossary.project_asr_prompt(account, "")) == ""
    assert asyncio.run(asr_glossary.project_asr_prompt(account, "p2")) == ""
    assert brain.calls == ["p2"]


def test_vocabulary_comes_from_the_same_cached_fetch(brain):
    brain.answer({"terms": "DIVA PRO、沉水泵", "vocabulary": ["DIVA PRO", "沉水泵", "", 3]})
    account = types.SimpleNamespace()
    assert asyncio.run(asr_glossary.project_asr_prompt(account, "p1")) == "DIVA PRO、沉水泵"
    assert asyncio.run(asr_glossary.project_asr_vocabulary(account, "p1")) == ["DIVA PRO", "沉水泵"]
    assert brain.calls == ["p1"]


def test_vocabulary_is_empty_without_a_project_or_a_list(brain):
    account = types.SimpleNamespace()
    brain.answer({"terms": "沉水泵"})
    assert asyncio.run(asr_glossary.project_asr_vocabulary(account, "")) == []
    assert asyncio.run(asr_glossary.project_asr_vocabulary(account, "p1")) == []
