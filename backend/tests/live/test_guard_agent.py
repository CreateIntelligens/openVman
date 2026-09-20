"""Interruption intent regressions, including ASR punctuation loss."""

import pytest

from app.guard_agent import GuardAgent


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "text",
    [
        "停", "停！", "STOP", "不對", "不要繼續說", "請不要再講了", "等一下", "先不要說了。",
        "換個問題，請問本機構幾點開始服務？",
        "你剛才說錯了，我問的是週六，不是週日。",
        "好，那我想了解流程", "我想知道怎麼辦",
        "旁邊的人說停，但我現在也要你停",
        "請改用臺語回答。",
        "不用回答剛才的問題了，請先說明退款流程。",
        "好，先停在這裡。",
        "不用停，繼續說。不過現在先停一下。",
        "不用停繼續說但我改變主意了先停一下",
        "不用停，繼續說。請問明天幾點開門？",
        "了解你繼續，不對，請改用英文回答。",
        "旁邊的人說不用停，但我是叫你停。",
        "don't stop, keep going. Actually stop now.",
        "這是一段比較長的文字，應該被視為有意圖的輸入",
    ],
)
async def test_guard_preserves_explicit_interruptions_and_long_fallback(text):
    assert await GuardAgent().classify(text) == "STOP"


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "text",
    [
        "", "   ", "喔", "呃", "嗯", "好", "嗯嗯",
        "了解，你繼續。", "了解你繼續",
        "不用停，繼續說。", "不用停繼續說", "請不要停", "麻煩你不用停",
        "我是在跟旁邊的人說話，你繼續說就好。",
        "我是在跟旁邊的人說話你繼續說就好",
        "「停」", '"STOP"',
        "旁邊的人剛才說「等一下」，不是叫你停，你繼續。",
        "旁邊的人剛才說「等一下」不是叫你停你繼續",
        "這段我懂了，請繼續下一段。",
        "這段我懂了請繼續下一段",
        "don't stop keep going", "Don't stop, keep going.",
        "please don't stop", "don't stop talking", "旁邊的人說停",
        "對對，我有在聽。",
    ],
)
async def test_guard_ignores_backchannels_continuations_and_quoted_speech(text):
    assert await GuardAgent().classify(text) == "IGNORE"
