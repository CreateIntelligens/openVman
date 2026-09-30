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
