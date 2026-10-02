from unittest.mock import AsyncMock, patch

import pytest

from app.routes.interrupt import InterruptRequest, classify_interrupt


@pytest.mark.asyncio
@pytest.mark.parametrize("text", ["對啊", "嗯", "這款馬力是十匹"])
async def test_echo_or_acknowledgement_is_ignored(text):
    result = await classify_interrupt(
        InterruptRequest(transcript=text, reply_text="這款馬力是十匹。"),
        current=None,
    )
    assert result == {"action": "IGNORE"}


@pytest.mark.asyncio
@pytest.mark.parametrize("text", ["等一下", "請問馬力多少", "不對，我要另一款"])
async def test_stop_correction_and_short_question_interrupt(text):
    result = await classify_interrupt(
        InterruptRequest(transcript=text, reply_text="這款馬力是十匹。"),
        current=None,
    )
    assert result == {"action": "STOP"}


@pytest.mark.asyncio
async def test_ambiguous_speech_uses_existing_guard():
    with patch("app.routes.interrupt._guard.classify", AsyncMock(return_value="IGNORE")) as guard:
        result = await classify_interrupt(
            InterruptRequest(transcript="我正在跟旁邊的人討論事情"),
            current=None,
        )
    guard.assert_awaited_once()
    assert result == {"action": "IGNORE"}
