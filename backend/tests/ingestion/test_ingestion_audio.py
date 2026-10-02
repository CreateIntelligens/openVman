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
        asr_provider="openai",
        whisper_api_key="test-key",
        vision_llm_base_url="",
    )


def _asr_cfg(provider: str, **overrides) -> MagicMock:
    """Config with exactly one ASR provider configured.

    _resolve_chain 只排入設定齊全的 provider，所以其餘欄位要明確清空——
    否則 MagicMock 的自動屬性是 truthy，整條 chain 都會被排進來。
    """
    fields = {
        "asr_provider": provider,
        "asr_sensevoice_url": "",
        "asr_breeze_url": "",
        "asr_xiaomi_url": "",
        "asr_r2t2_url": "",
        "asr_r2t2_backup_url": "",
        "whisper_api_key": "",
    }
    fields.update(overrides)
    return MagicMock(**fields)


def _sensevoice_cfg(url: str = "http://asr:50002/") -> MagicMock:
    return _asr_cfg("sensevoice", asr_sensevoice_url=url)


def _breeze_cfg(url: str = "http://asr:8801/") -> MagicMock:
    return _asr_cfg("breeze", asr_breeze_url=url)


def _xiaomi_cfg(url: str = "http://asr:8802/") -> MagicMock:
    return _asr_cfg("xiaomi", asr_xiaomi_url=url)


def _stub_post(handler, seen: dict):
    """Replace the shared client's post(), recording what the adapter sent."""

    async def _post(url, files=None, data=None, **kwargs):
        seen["url"] = url
        seen["file_field"] = next(iter(files))
        seen["files"] = files
        seen["data"] = data
        return handler(url)

    return MagicMock(get=MagicMock(return_value=MagicMock(post=_post)))



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


class TestXiaomiTranscription:
    """目標語者模型：同一個音檔同時當 target 與 ref，閘門才會放行。"""

    @pytest.mark.asyncio
    async def test_sends_the_same_clip_as_both_target_and_ref(self, fake_audio):
        seen: dict = {}
        def handler(url):
            return httpx.Response(
                200,
                json={"text": " 你好请回复我 ", "rejected": False},
                request=httpx.Request("POST", url),
            )
        with patch.object(
            ingestion_audio, "get_tts_config", return_value=_xiaomi_cfg(),
        ), patch.object(
            ingestion_audio, "_http", _stub_post(handler, seen),
        ):
            result = await transcribe(fake_audio, "trace-xm")

        assert seen["url"] == "http://asr:8802/transcribe"
        # 少送 ref 會被當成「目標語者沒開口」而回空字串，這兩個欄位缺一不可。
        assert set(seen["files"]) == {"target", "ref"}
        assert seen["files"]["target"][1] == seen["files"]["ref"][1]
        # 簡體要轉繁，否則跟其他 provider 的輸出不一致。s2t 的「复」一律對到
        # 「復」，回覆的「覆」要靠詞庫才分得出來，這裡不苛求。
        assert result.content == "你好請回復我"

    @pytest.mark.asyncio
    async def test_rejected_clip_falls_through_instead_of_returning_empty(
        self, fake_audio,
    ):
        """rejected 回空字串，當成成功會讓使用者「說了一句空話」。"""
        def handler(url):
            return httpx.Response(
                200,
                json={"text": "", "rejected": True},
                request=httpx.Request("POST", url),
            )
        with patch.object(
            ingestion_audio, "get_tts_config", return_value=_xiaomi_cfg(),
        ), patch.object(
            ingestion_audio, "_http", _stub_post(handler, {}),
        ):
            result = await transcribe(fake_audio, "trace-xm-rej")

        assert result.content == "（音訊轉錄失敗）"

    @pytest.mark.asyncio
    async def test_missing_url_reports_failure(self, fake_audio):
        with patch.object(
            ingestion_audio, "get_tts_config", return_value=_xiaomi_cfg(url=""),
        ):
            result = await transcribe(fake_audio, "trace-xm-nourl")

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

        async def _sensevoice(path, trace, prompt=""):
            tried.append("sensevoice")
            raise RuntimeError("GPU node restarting")

        async def _breeze(path, trace, prompt=""):
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

        async def _sensevoice(path, trace, prompt=""):
            tried.append("sensevoice")
            return "好"

        async def _breeze(path, trace, prompt=""):
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


class TestUnreachableProviders:
    """連不上的引擎暫停一陣子：不要每句話都白等一次連線逾時。"""

    @pytest.fixture(autouse=True)
    def _fresh(self, monkeypatch):
        monkeypatch.setattr(ingestion_audio, "_unreachable_until", {})
        self.now = [1000.0]
        monkeypatch.setattr(ingestion_audio.time, "monotonic", lambda: self.now[0])

    def _cfg(self):
        return _asr_cfg("breeze", asr_breeze_url="http://b:8801", asr_xiaomi_url="http://x:8802",
                        asr_sensevoice_url="http://s:50002", whisper_api_key="k")

    async def _run(self, fake_audio, engines, preferred="xiaomi"):
        with patch.object(ingestion_audio, "get_tts_config", return_value=self._cfg()), patch.dict(
            ingestion_audio._TRANSCRIBERS, engines,
        ):
            return await transcribe(fake_audio, "trace-down", preferred)

    @staticmethod
    def _engines(tried, *, xiaomi_error=None):
        async def xiaomi(path, trace, prompt=""):
            tried.append("xiaomi")
            if xiaomi_error:
                raise xiaomi_error
            return "小米"

        async def breeze(path, trace, prompt=""):
            tried.append("breeze")
            return "布里茲"

        async def sensevoice(path, trace, prompt=""):
            tried.append("sensevoice")
            return "森"

        return {"xiaomi": xiaomi, "breeze": breeze, "sensevoice": sensevoice}

    @pytest.mark.asyncio
    async def test_a_provider_that_cannot_connect_is_skipped_next_time(self, fake_audio):
        tried: list[str] = []
        down = httpx.ConnectError("connection refused")
        first = await self._run(fake_audio, self._engines(tried, xiaomi_error=down))
        second = await self._run(fake_audio, self._engines(tried, xiaomi_error=down))

        assert (first.provider, second.provider) == ("breeze", "breeze")
        assert tried == ["xiaomi", "breeze", "breeze"]

    @pytest.mark.asyncio
    async def test_it_is_tried_again_after_the_cooldown(self, fake_audio):
        tried: list[str] = []
        await self._run(fake_audio, self._engines(tried, xiaomi_error=httpx.ConnectTimeout("t")))
        self.now[0] += ingestion_audio._UNREACHABLE_COOLDOWN_SECONDS
        result = await self._run(fake_audio, self._engines(tried))

        assert result.provider == "xiaomi"
        assert tried == ["xiaomi", "breeze", "xiaomi"]

    @pytest.mark.asyncio
    async def test_an_http_error_does_not_pause_the_provider(self, fake_audio):
        """回 500 代表機器還活著、正在回應；下一句照樣先試它。"""
        tried: list[str] = []
        error = httpx.HTTPStatusError("500", request=httpx.Request("POST", "http://x"),
                                      response=httpx.Response(500))
        await self._run(fake_audio, self._engines(tried, xiaomi_error=error))
        await self._run(fake_audio, self._engines(tried, xiaomi_error=error))

        assert tried == ["xiaomi", "breeze", "xiaomi", "breeze"]

    @pytest.mark.asyncio
    async def test_openai_connection_errors_pause_it_too(self, fake_audio):
        import openai

        tried: list[str] = []
        error = openai.APIConnectionError(request=httpx.Request("POST", "http://api.openai.com"))

        async def openai_engine(path, trace, prompt=""):
            tried.append("openai")
            raise error

        engines = {**self._engines(tried), "openai": openai_engine}
        await self._run(fake_audio, engines, preferred="openai")
        await self._run(fake_audio, engines, preferred="openai")

        # openai 暫停後，下一句直接從部署預設（breeze）開始。
        assert tried == ["openai", "breeze", "breeze"]

    @pytest.mark.asyncio
    async def test_when_every_provider_is_paused_they_are_tried_anyway(self, fake_audio):
        for name in ("xiaomi", "breeze", "sensevoice", "openai"):
            ingestion_audio._unreachable_until[name] = self.now[0] + 30
        tried: list[str] = []
        result = await self._run(fake_audio, self._engines(tried))

        assert result.provider == "xiaomi"
        # 成功就解除暫停，不必等冷卻時間。
        assert "xiaomi" not in ingestion_audio._unreachable_until


class TestDeploymentDefault:
    """沒選過引擎的人用 .env 的 ASR_PROVIDER；後台的全站預設已拔掉（2026-09-24）。"""

    def test_environment_default_leads_the_chain(self):
        cfg = _asr_cfg(
            "sensevoice",
            asr_sensevoice_url="http://asr:50002",
            asr_breeze_url="http://asr:8801",
        )
        assert ingestion_audio._resolve_chain(cfg)[0] == "sensevoice"

    def test_a_leftover_site_setting_is_ignored(self):
        """舊資料庫殘留的 asr_provider 設定不能再蓋過 .env。"""
        cfg = _asr_cfg("breeze", asr_breeze_url="http://asr:8801", asr_sensevoice_url="http://asr:50002")
        stored = MagicMock(settings=MagicMock(get=MagicMock(return_value="sensevoice")))
        with patch("app.auth.runtime.get_auth_runtime", return_value=stored):
            assert ingestion_audio._resolve_chain(cfg)[0] == "breeze"

    def test_the_user_choice_still_comes_first(self):
        cfg = _asr_cfg("breeze", asr_breeze_url="http://asr:8801", asr_sensevoice_url="http://asr:50002")
        assert ingestion_audio._resolve_chain(cfg, "sensevoice")[:2] == ["sensevoice", "breeze"]


class TestAudioConversion:
    """瀏覽器錄的是 webm/opus，SenseVoice 對它直接回 500。"""

    def test_native_formats_skip_ffmpeg(self, tmp_path):
        """已是引擎吃得下的格式就不白跑一次轉檔。"""
        clip = tmp_path / "clip.wav"
        clip.write_bytes(b"RIFF")

        source, scratch = ingestion_audio._as_wav(str(clip))

        assert source == str(clip)
        assert scratch is None

    def test_webm_is_converted_and_the_temp_file_is_reported(
        self, tmp_path, monkeypatch,
    ):
        clip = tmp_path / "clip.webm"
        clip.write_bytes(b"webm")
        seen: dict = {}

        def _run(cmd, **kwargs):
            seen["cmd"] = cmd
            return MagicMock(returncode=0, stderr="")

        monkeypatch.setattr(ingestion_audio.subprocess, "run", _run)

        source, scratch = ingestion_audio._as_wav(str(clip))

        assert source == scratch and source.endswith(".wav")
        # 16 kHz 單聲道：兩家引擎內部都會降到這個取樣率。
        assert "-ar" in seen["cmd"] and "16000" in seen["cmd"]
        assert "-ac" in seen["cmd"] and "1" in seen["cmd"]

    def test_a_failed_conversion_does_not_leave_the_temp_file_behind(
        self, tmp_path, monkeypatch,
    ):
        clip = tmp_path / "clip.webm"
        clip.write_bytes(b"not audio")
        monkeypatch.setattr(
            ingestion_audio.subprocess, "run",
            lambda cmd, **kw: MagicMock(returncode=1, stderr="invalid data"),
        )

        with pytest.raises(RuntimeError, match="conversion failed"):
            ingestion_audio._as_wav(str(clip))


class TestPreferredProvider:
    """使用者自己選的引擎排最前面，但不取消備援。"""

    @pytest.mark.asyncio
    async def test_preferred_goes_first_and_keeps_the_rest_as_fallback(self):
        cfg = _asr_cfg(
            "breeze",
            asr_breeze_url="http://b:8801",
            asr_sensevoice_url="http://s:50002",
        )
        with patch.object(ingestion_audio, "get_tts_config", return_value=cfg):
            chain = ingestion_audio._resolve_chain(cfg, "sensevoice")

        assert chain[0] == "sensevoice"
        # 選了 sensevoice 不代表放棄 fallback：它掛了還是要有下一家。
        assert "breeze" in chain

    @pytest.mark.asyncio
    async def test_browser_is_not_a_server_engine(self):
        """browser 在使用者裝置上跑，音檔根本不會送到這裡。"""
        cfg = _asr_cfg("breeze", asr_breeze_url="http://b:8801")
        with patch.object(ingestion_audio, "get_tts_config", return_value=cfg):
            chain = ingestion_audio._resolve_chain(cfg, "browser")

        assert "browser" not in chain
        assert chain == ["breeze"]

    @pytest.mark.asyncio
    async def test_unconfigured_preference_is_skipped(self):
        """選了一個沒設 URL 的引擎，不該白等一次連線逾時。"""
        cfg = _asr_cfg("breeze", asr_breeze_url="http://b:8801")
        with patch.object(ingestion_audio, "get_tts_config", return_value=cfg):
            chain = ingestion_audio._resolve_chain(cfg, "xiaomi")

        assert chain == ["breeze"]
