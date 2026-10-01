"""Language routes: admin settings narrowed by client toggles, and what they switch."""

from __future__ import annotations

import asyncio
import time
import types

import pytest

from app import language_routes as lr


def _account(embed_project: str | None = None):
    embed = types.SimpleNamespace(project_id=embed_project) if embed_project else None
    return types.SimpleNamespace(embed_key=embed, user=types.SimpleNamespace(id="u1"))


@pytest.fixture
def routes(monkeypatch):
    table = {"proj-hospital": ["zh", "nan"], "proj-hekee": ["zh", "en", "es"]}

    async def fake_admin_routes(project_id):
        return table.get(project_id or "", ["zh"])

    monkeypatch.setattr(lr, "admin_routes", fake_admin_routes)
    monkeypatch.setattr(lr, "resolve_project", lambda current, pid: (
        current.embed_key.project_id if current.embed_key else (pid or None)
    ))
    return table


def test_client_can_only_narrow_admin_routes(routes):
    run = asyncio.run
    assert run(lr.effective_routes(_account(), "proj-hekee", None)) == ["zh", "en", "es"]
    # 前台把西語關掉。
    assert run(lr.effective_routes(_account(), "proj-hekee", ["zh", "en"])) == ["zh", "en"]
    # 前台想開後台沒有的台語：不給；全部關掉時保留後台第一條。
    assert run(lr.effective_routes(_account(), "proj-hekee", ["nan"])) == ["zh"]
    # 中文不是必選：只留英文也可以。
    assert run(lr.effective_routes(_account(), "proj-hekee", ["en"])) == ["en"]


def test_embed_key_uses_its_own_project(routes):
    assert asyncio.run(lr.effective_routes(_account("proj-hospital"), "proj-hekee", None)) == ["zh", "nan"]


def test_taiwanese_tts_switches_only_away_from_other_providers():
    assert lr.taiwanese_tts_provider("gemini-tts") == "voxcpm"
    assert lr.taiwanese_tts_provider("") == "voxcpm"
    assert lr.taiwanese_tts_provider("voxcpm") is None
    assert lr.taiwanese_tts_provider("cosyvoice") is None


def test_parse_requested():
    assert lr.parse_requested(None) is None
    assert lr.parse_requested("zh, nan,") == ["zh", "nan"]
    assert lr.parse_requested([]) == []


def _language_check_limit(monkeypatch, seconds: float):
    cfg = lr.get_tts_config().model_copy(update={"asr_language_check_timeout_seconds": seconds})
    monkeypatch.setattr(lr, "get_tts_config", lambda: cfg)


def test_slow_language_check_gives_up_instead_of_holding_the_turn(monkeypatch):
    """真人語料有一句判斷拖到 22.7 秒；使用者在等回答，逾時就當不是台語。"""
    _language_check_limit(monkeypatch, 0.05)

    async def hangs(file_path, cfg):
        await asyncio.sleep(5)
        return "nan"

    monkeypatch.setattr(lr, "_ask_brain_language", hangs)
    started = time.monotonic()
    check = asyncio.run(lr.detect_taiwanese("clip.wav"))
    assert time.monotonic() - started < 1
    # 逾時要跟「判成華語」分得開，語音模擬才數得出逾時。
    assert (check.language, check.result) == (None, "timeout")


def test_language_check_within_limit_is_used(monkeypatch):
    _language_check_limit(monkeypatch, 1.0)

    async def answers(file_path, cfg):
        return "nan"

    monkeypatch.setattr(lr, "_ask_brain_language", answers)
    check = asyncio.run(lr.detect_taiwanese("clip.wav"))
    assert (check.language, check.result) == ("nan", "nan")
    assert check.ms >= 0


def test_language_check_that_cannot_tell_is_reported_as_failed(monkeypatch):
    _language_check_limit(monkeypatch, 1.0)

    async def cannot_tell(file_path, cfg):
        return None

    monkeypatch.setattr(lr, "_ask_brain_language", cannot_tell)
    check = asyncio.run(lr.detect_taiwanese("clip.wav"))
    assert (check.language, check.result) == (None, "failed")


def _write_wav(path, *, rate=16000, channels=1):
    import wave

    with wave.open(str(path), "wb") as handle:
        handle.setnchannels(channels)
        handle.setsampwidth(2)
        handle.setframerate(rate)
        handle.writeframes(b"\0\0" * channels * 160)


def test_speech_wav_is_sent_without_ffmpeg(monkeypatch, tmp_path):
    """前台 VAD 上傳的就是 16 kHz 單聲道 wav；再跑 ffmpeg 白花 0.15 秒。"""
    clip = tmp_path / "speech.wav"
    _write_wav(clip)
    monkeypatch.setattr(lr.subprocess, "run", lambda *a, **k: pytest.fail("ffmpeg should not run"))
    assert lr._to_wav_bytes(str(clip)) == clip.read_bytes()


@pytest.mark.parametrize("name,kwargs", [
    ("cd.wav", {"rate": 44100}),
    ("stereo.wav", {"channels": 2}),
])
def test_other_wavs_are_converted(monkeypatch, tmp_path, name, kwargs):
    clip = tmp_path / name
    _write_wav(clip, **kwargs)
    ran = []
    monkeypatch.setattr(lr.subprocess, "run", lambda cmd, **k: ran.append(cmd) or types.SimpleNamespace(
        returncode=0, stdout=b"RIFF-converted", stderr=b"",
    ))
    assert lr._to_wav_bytes(str(clip)) == b"RIFF-converted"
    assert ran and ran[0][0] == "ffmpeg"


def test_non_wav_uploads_are_converted(monkeypatch, tmp_path):
    clip = tmp_path / "speech.webm"
    clip.write_bytes(b"\x1aE\xdf\xa3 not a wav")
    monkeypatch.setattr(lr.subprocess, "run", lambda cmd, **k: types.SimpleNamespace(
        returncode=0, stdout=b"RIFF-converted", stderr=b"",
    ))
    assert lr._to_wav_bytes(str(clip)) == b"RIFF-converted"


class _Settings:
    """Brain's /brain/knowledge/settings: answers, or refuses like a restarting container."""

    def __init__(self, routes):
        self.routes = routes
        self.down = False
        self.calls = 0

    async def get(self, url, params=None, headers=None):
        self.calls += 1
        if self.down:
            raise ConnectionError("All connection attempts failed")
        routes = self.routes
        return types.SimpleNamespace(raise_for_status=lambda: None, json=lambda: {"language_routes": routes})


@pytest.fixture
def brain_settings(monkeypatch):
    settings = _Settings(["zh", "nan"])
    monkeypatch.setattr(lr, "_cache", {})
    monkeypatch.setattr(lr._http, "get", lambda: settings)
    clock = [100.0]
    monkeypatch.setattr(lr.time, "monotonic", lambda: clock[0])
    return settings, clock


def test_brain_restart_keeps_the_last_known_routes(brain_settings):
    """部署時 Brain 重啟約半分鐘：不能因此把台語分流默默關掉。"""
    settings, clock = brain_settings
    assert asyncio.run(lr.admin_routes("proj-hospital")) == ["zh", "nan"]
    clock[0] += lr._CACHE_SECONDS + 1
    settings.down = True
    assert asyncio.run(lr.admin_routes("proj-hospital")) == ["zh", "nan"]
    assert settings.calls == 2  # 過期了還是有去問，問不到才沿用


def test_never_seen_project_falls_back_to_chinese_when_brain_is_down(brain_settings):
    settings, _ = brain_settings
    settings.down = True
    assert asyncio.run(lr.admin_routes("proj-new")) == ["zh"]


def test_fresh_answer_replaces_the_last_known_routes(brain_settings):
    settings, clock = brain_settings
    asyncio.run(lr.admin_routes("proj-hospital"))
    clock[0] += lr._CACHE_SECONDS + 1
    settings.routes = ["zh"]
    assert asyncio.run(lr.admin_routes("proj-hospital")) == ["zh"]
