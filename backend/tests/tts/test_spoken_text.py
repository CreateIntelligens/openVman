"""Only IndexTTS gets the remote normalization call by default."""

from __future__ import annotations

import pytest

from app.routes import tts as tts_routes


@pytest.mark.asyncio
@pytest.mark.parametrize(("provider", "normalized"), [
    ("gemini-tts", False),
    ("edge-tts", False),
    ("voxcpm", False),
    ("cosyvoice", False),
    ("indextts", True),
    ("indextts-nurse", True),
    ("", True),
])
async def test_only_listed_engines_are_normalized(monkeypatch, provider, normalized):
    calls = []

    async def fake_prepare(text, simplified=True):
        calls.append(text)
        return "第一號"

    monkeypatch.setattr(tts_routes, "prepare_tts_text_async", fake_prepare)
    result = await tts_routes.spoken_text("**第1號**", provider, taiwanese=False)

    assert bool(calls) is normalized
    assert result == ("第一號" if normalized else "第1號")
