"""OpenAI transcription: configurable model, auto language, its own base URL."""

import types

import pytest

from app.gateway import ingestion_audio


class _FakeTranscriptions:
    def __init__(self, sink):
        self.sink = sink

    async def create(self, **kwargs):
        self.sink["create"] = {k: v for k, v in kwargs.items() if k != "file"}
        return types.SimpleNamespace(text="¿A qué hora abren?")


@pytest.fixture
def openai_calls(monkeypatch, tmp_path):
    sink: dict = {}

    def fake_client(**kwargs):
        sink["client"] = kwargs
        return types.SimpleNamespace(audio=types.SimpleNamespace(transcriptions=_FakeTranscriptions(sink)))

    monkeypatch.setattr(ingestion_audio, "AsyncOpenAI", fake_client)
    audio = tmp_path / "clip.mp3"
    audio.write_bytes(b"fake")
    sink["path"] = str(audio)
    return sink


def _use_config(monkeypatch, **overrides):
    cfg = ingestion_audio.get_tts_config().model_copy(update={"whisper_api_key": "k", **overrides})
    monkeypatch.setattr(ingestion_audio, "get_tts_config", lambda: cfg)
    return cfg


@pytest.mark.asyncio
async def test_detects_language_instead_of_forcing_chinese(monkeypatch, openai_calls):
    _use_config(monkeypatch)
    text = await ingestion_audio._transcribe_openai(openai_calls["path"], "t")
    assert text == "¿A qué hora abren?"
    assert "language" not in openai_calls["create"]
    assert openai_calls["create"]["model"] == "gpt-4o-mini-transcribe"


@pytest.mark.asyncio
async def test_vlm_base_url_no_longer_hijacks_transcription(monkeypatch, openai_calls):
    _use_config(monkeypatch, vision_llm_base_url="http://vlm:9000/v1")
    await ingestion_audio._transcribe_openai(openai_calls["path"], "t")
    assert "base_url" not in openai_calls["client"]


@pytest.mark.asyncio
async def test_model_and_base_url_are_configurable(monkeypatch, openai_calls):
    _use_config(monkeypatch, asr_openai_model="gpt-4o-transcribe", asr_openai_base_url="http://proxy/v1")
    await ingestion_audio._transcribe_openai(openai_calls["path"], "t")
    assert openai_calls["create"]["model"] == "gpt-4o-transcribe"
    assert openai_calls["client"]["base_url"] == "http://proxy/v1"
