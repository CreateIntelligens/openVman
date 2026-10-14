"""Edge TTS breaks whenever Microsoft changes its handshake; the probe makes that visible."""

from __future__ import annotations

import asyncio

import pytest

from app.providers import edge_tts_adapter, edge_tts_probe


class _Gauge:
    value = None

    def set(self, value):
        self.value = value


@pytest.fixture(autouse=True)
def gauge(monkeypatch: pytest.MonkeyPatch) -> _Gauge:
    monkeypatch.setattr(
        edge_tts_probe, "_state", {"status": "pending", "checked_at": None, "error": None},
    )
    recorder = _Gauge()
    monkeypatch.setattr(edge_tts_probe, "_edge_tts_up", recorder)
    return recorder


def test_audio_marks_edge_ready(monkeypatch: pytest.MonkeyPatch, gauge) -> None:
    async def fake(text, voice):
        return b"mp3"

    monkeypatch.setattr(edge_tts_adapter, "_synthesize_async", fake)
    snapshot = asyncio.run(edge_tts_probe.check_edge_tts())

    assert snapshot["status"] == "ready"
    assert snapshot["error"] is None
    assert snapshot["checked_at"]
    assert gauge.value == 1


def test_handshake_403_marks_edge_broken(monkeypatch: pytest.MonkeyPatch, caplog, gauge) -> None:
    # 2026-10-14：edge-tts 7.2.8 被微軟回 403，所有 Edge 合成都失敗。
    async def fake(text, voice):
        raise RuntimeError("WSServerHandshakeError: 403, message='Invalid response status'")

    monkeypatch.setattr(edge_tts_adapter, "_synthesize_async", fake)
    snapshot = asyncio.run(edge_tts_probe.check_edge_tts())

    assert snapshot["status"] == "error"
    assert "403" in snapshot["error"]
    assert gauge.value == 0
    assert "edge-tts probe failed" in caplog.text


def test_empty_audio_counts_as_broken(monkeypatch: pytest.MonkeyPatch) -> None:
    async def fake(text, voice):
        return b""

    monkeypatch.setattr(edge_tts_adapter, "_synthesize_async", fake)
    assert asyncio.run(edge_tts_probe.check_edge_tts())["status"] == "error"


def test_snapshot_never_calls_edge(monkeypatch: pytest.MonkeyPatch) -> None:
    # 健康頁每次開都讀快照，不能每次都去打微軟。
    async def fake(text, voice):
        pytest.fail("snapshot must not synthesize")

    monkeypatch.setattr(edge_tts_adapter, "_synthesize_async", fake)
    snapshot = edge_tts_probe.edge_tts_probe_snapshot()
    assert snapshot["status"] == "pending"
    assert "edge_tts_version" in snapshot


def test_image_always_installs_the_newest_edge_tts() -> None:
    from pathlib import Path

    root = Path(__file__).resolve().parents[3]
    dockerfile = (root / "backend" / "Dockerfile").read_text(encoding="utf-8")
    workflow = (root / ".github" / "workflows" / "docker-publish.yml").read_text(encoding="utf-8")
    assert 'uv pip install --upgrade "edge-tts<8"' in dockerfile
    assert "ARG EDGE_TTS_REFRESH" in dockerfile
    assert "EDGE_TTS_REFRESH=${{ github.run_id }}" in workflow
