"""Tests for audio ingestion."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest

from app.gateway import ingestion_audio
from app.gateway.ingestion_audio import transcribe


@pytest.fixture
def fake_audio(tmp_path):
    path = tmp_path / "test.mp3"
    path.write_bytes(b"\xff\xfb\x90\x00" + b"\x00" * 100)
    return str(path)


def _openai_cfg() -> MagicMock:
    return MagicMock(
        whisper_provider="openai",
        whisper_api_key="test-key",
        vision_llm_base_url="",
    )


def _asr_cfg(provider: str, **overrides) -> MagicMock:
    """Config with exactly one ASR provider configured.

    _resolve_chain 只排入設定齊全的 provider，所以其餘欄位要明確清空——
    否則 MagicMock 的自動屬性是 truthy，整條 chain 都會被排進來。
    """
    fields = {
        "whisper_provider": provider,
        "asr_sensevoice_url": "",
        "asr_breeze_url": "",
        "whisper_api_key": "",
        "whisper_local_bin": "",
    }
    fields.update(overrides)
    return MagicMock(**fields)


def _sensevoice_cfg(url: str = "http://asr:50002/") -> MagicMock:
    return _asr_cfg("sensevoice", asr_sensevoice_url=url)


def _breeze_cfg(url: str = "http://asr:8801/") -> MagicMock:
    return _asr_cfg("breeze", asr_breeze_url=url)


def _stub_post(handler, seen: dict):
    """Replace the shared client's post(), recording what the adapter sent."""

    async def _post(url, files=None, data=None, **kwargs):
        seen["url"] = url
        seen["file_field"] = next(iter(files))
        seen["data"] = data
        return handler(url)

    return MagicMock(get=MagicMock(return_value=MagicMock(post=_post)))


def _local_cfg() -> MagicMock:
    # _provider_ready 會檢查 binary 真的存在，所以指向一個必然存在的檔案；
    # subprocess.run 在這些測試裡都被 patch 掉，不會真的執行它。
    return _asr_cfg("local", whisper_local_bin="/bin/sh")


class TestOpenAITranscription:
    @pytest.mark.asyncio
    async def test_openai_success(self, fake_audio):
        mock_response = MagicMock()
        mock_response.text = "你好世界"

        mock_client = AsyncMock()
        mock_client.audio.transcriptions.create = AsyncMock(return_value=mock_response)

        with (
            patch("app.gateway.ingestion_audio.get_tts_config", return_value=_openai_cfg()),
            patch("app.gateway.ingestion_audio.AsyncOpenAI", return_value=mock_client),
        ):
            result = await transcribe(fake_audio, "trace-1")

        assert result.content_type == "audio_transcription"
        assert result.content == "你好世界"

    @pytest.mark.asyncio
    async def test_openai_failure_returns_fallback(self, fake_audio):
        with (
            patch("app.gateway.ingestion_audio.get_tts_config", return_value=_openai_cfg()),
            patch("app.gateway.ingestion_audio.AsyncOpenAI", side_effect=RuntimeError("API down")),
        ):
            result = await transcribe(fake_audio, "trace-2")

        assert "轉錄失敗" in result.content


class TestLocalTranscription:
    @pytest.mark.asyncio
    async def test_local_success_from_file(self, fake_audio, tmp_path):
        # whisper writes to <input>.txt
        txt_path = tmp_path / "test.txt"
        txt_path.write_text("本地轉錄結果", encoding="utf-8")

        mock_result = MagicMock(returncode=0, stdout="", stderr="")

        with (
            patch("app.gateway.ingestion_audio.get_tts_config", return_value=_local_cfg()),
            patch("app.gateway.ingestion_audio.subprocess.run", return_value=mock_result),
        ):
            result = await transcribe(fake_audio, "trace-3")

        assert result.content == "本地轉錄結果"

    @pytest.mark.asyncio
    async def test_local_success_from_stdout(self, fake_audio):
        mock_result = MagicMock(returncode=0, stdout="stdout轉錄", stderr="")

        with (
            patch("app.gateway.ingestion_audio.get_tts_config", return_value=_local_cfg()),
            patch("app.gateway.ingestion_audio.subprocess.run", return_value=mock_result),
        ):
            result = await transcribe(fake_audio, "trace-4")

        assert result.content == "stdout轉錄"

    @pytest.mark.asyncio
    async def test_local_nonzero_exit(self, fake_audio):
        mock_result = MagicMock(returncode=1, stderr="error")

        with (
            patch("app.gateway.ingestion_audio.get_tts_config", return_value=_local_cfg()),
            patch("app.gateway.ingestion_audio.subprocess.run", return_value=mock_result),
        ):
            result = await transcribe(fake_audio, "trace-5")

        assert "轉錄失敗" in result.content


class TestSenseVoiceTranscription:
    @pytest.mark.asyncio
    async def test_strips_emotion_markers_from_the_transcript(self, fake_audio):
        """取 clean_text：text 尾端有情緒 emoji，raw_text 還帶控制標記。"""
        seen: dict = {}
        def handler(url):
            return httpx.Response(
                200,
                json={"result": [{
                    "key": "test.mp3",
                    "text": "今仔日天氣袂歹。😊",
                    "raw_text": "<|zh|><|HAPPY|><|Speech|>今仔日天氣袂歹。",
                    "clean_text": "今仔日天氣袂歹。",
                }]},
                request=httpx.Request("POST", url),
            )
        with patch.object(
            ingestion_audio, "get_tts_config", return_value=_sensevoice_cfg(),
        ), patch.object(
            ingestion_audio, "_http", _stub_post(handler, seen),
        ):
            result = await transcribe(fake_audio, "trace-sv")

        assert result.content == "今仔日天氣袂歹。"
        # 尾斜線不能疊成 //api，那會讓部分反向代理回 404。
        assert seen["url"] == "http://asr:50002/api/v1/asr"
        assert seen["file_field"] == "files"
        assert seen["data"]["keys"] == "test.mp3"

    @pytest.mark.asyncio
    async def test_empty_result_list_reports_failure(self, fake_audio, caplog):
        """result 空陣列不能靜默回空字串，那會讓 LLM 收到空 prompt。

        並且要以具名的 RuntimeError 收場，不是讓 result[0] 拋 IndexError ——
        日誌只印例外訊息，IndexError 看不出是上游回了空結果。
        """
        seen: dict = {}
        def handler(url):
            return httpx.Response(
                200, json={"result": []}, request=httpx.Request("POST", url),
            )
        with patch.object(
            ingestion_audio, "get_tts_config", return_value=_sensevoice_cfg(),
        ), patch.object(
            ingestion_audio, "_http", _stub_post(handler, seen),
        ), caplog.at_level("WARNING"):
            result = await transcribe(fake_audio, "trace-sv-empty")

        assert result.content == "（音訊轉錄失敗）"
        assert "no result" in caplog.text
        assert "IndexError" not in caplog.text and "list index" not in caplog.text

    @pytest.mark.asyncio
    async def test_missing_url_reports_failure(self, fake_audio):
        with patch.object(
            ingestion_audio, "get_tts_config", return_value=_sensevoice_cfg(url=""),
        ):
            result = await transcribe(fake_audio, "trace-sv-nourl")

        assert result.content == "（音訊轉錄失敗）"


class TestBreezeTranscription:
    @pytest.mark.asyncio
    async def test_posts_the_file_and_trims_the_transcript(self, fake_audio):
        seen: dict = {}
        def handler(url):
            return httpx.Response(
                200,
                json={"text": " 今天天氣不錯 ", "duration": 5.12},
                request=httpx.Request("POST", url),
            )
        with patch.object(
            ingestion_audio, "get_tts_config", return_value=_breeze_cfg(),
        ), patch.object(
            ingestion_audio, "_http", _stub_post(handler, seen),
        ):
            result = await transcribe(fake_audio, "trace-bz")

        assert result.content == "今天天氣不錯"
        assert seen["url"] == "http://asr:8801/transcribe"
        assert seen["file_field"] == "file"

    @pytest.mark.asyncio
    async def test_missing_url_reports_failure(self, fake_audio):
        with patch.object(
            ingestion_audio, "get_tts_config", return_value=_breeze_cfg(url=""),
        ):
            result = await transcribe(fake_audio, "trace-bz-nourl")

        assert result.content == "（音訊轉錄失敗）"


class TestProviderFallbackChain:
    """一台 ASR 掛掉要換下一台，不是把「音訊轉錄失敗」當成使用者說的話。"""

    @pytest.mark.asyncio
    async def test_falls_back_to_the_next_configured_provider(self, fake_audio):
        cfg = _asr_cfg(
            "sensevoice",
            asr_sensevoice_url="http://down:50002",
            asr_breeze_url="http://up:8801",
        )
        tried: list[str] = []

        async def _sensevoice(path, trace):
            tried.append("sensevoice")
            raise RuntimeError("GPU node restarting")

        async def _breeze(path, trace):
            tried.append("breeze")
            return "今天天氣不錯"

        with patch.object(
            ingestion_audio, "get_tts_config", return_value=cfg,
        ), patch.dict(
            ingestion_audio._TRANSCRIBERS,
            {"sensevoice": _sensevoice, "breeze": _breeze},
        ):
            result = await transcribe(fake_audio, "trace-chain")

        assert result.content == "今天天氣不錯"
        assert tried == ["sensevoice", "breeze"]

    @pytest.mark.asyncio
    async def test_unconfigured_providers_are_skipped(self, fake_audio):
        """沒填 URL 的不排進 chain：排進來只會白等一次連線逾時。"""
        cfg = _asr_cfg("sensevoice", asr_sensevoice_url="http://up:50002")
        tried: list[str] = []

        async def _sensevoice(path, trace):
            tried.append("sensevoice")
            return "好"

        async def _breeze(path, trace):
            tried.append("breeze")
            return "不該走到這裡"

        with patch.object(
            ingestion_audio, "get_tts_config", return_value=cfg,
        ), patch.dict(
            ingestion_audio._TRANSCRIBERS,
            {"sensevoice": _sensevoice, "breeze": _breeze},
        ):
            result = await transcribe(fake_audio, "trace-skip")

        assert result.content == "好"
        assert tried == ["sensevoice"]

    @pytest.mark.asyncio
    async def test_configured_provider_runs_first(self, fake_audio):
        """設定的那家排第一，其餘照字典序當備援。"""
        cfg = _asr_cfg(
            "breeze",
            asr_sensevoice_url="http://a:50002",
            asr_breeze_url="http://b:8801",
        )
        assert ingestion_audio._resolve_chain(cfg)[0] == "breeze"
        assert "sensevoice" in ingestion_audio._resolve_chain(cfg)

    @pytest.mark.asyncio
    async def test_every_provider_down_reports_failure_once(self, fake_audio, caplog):
        cfg = _asr_cfg(
            "sensevoice",
            asr_sensevoice_url="http://down:50002",
            asr_breeze_url="http://down:8801",
        )

        async def _dead(path, trace):
            raise RuntimeError("connection refused")

        with patch.object(
            ingestion_audio, "get_tts_config", return_value=cfg,
        ), patch.dict(
            ingestion_audio._TRANSCRIBERS,
            {"sensevoice": _dead, "breeze": _dead},
        ), caplog.at_level("ERROR"):
            result = await transcribe(fake_audio, "trace-alldown")

        assert result.content == "（音訊轉錄失敗）"
        # 失敗日誌要說試過誰，不然看不出是全掛還是根本沒排進來。
        assert "sensevoice" in caplog.text and "breeze" in caplog.text

    def test_local_whisper_needs_the_binary_to_exist(self, tmp_path):
        """whisper_local_bin 有預設值，光看設定永遠 truthy。"""
        missing = _asr_cfg("local", whisper_local_bin="/nonexistent/whisper")
        assert ingestion_audio._resolve_chain(missing) == []

        present = tmp_path / "whisper"
        present.write_text("#!/bin/sh\n")
        installed = _asr_cfg("local", whisper_local_bin=str(present))
        assert ingestion_audio._resolve_chain(installed) == ["local"]
