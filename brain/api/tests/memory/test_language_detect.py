"""Tests for the rule-based chat language guess used by session filters."""

from __future__ import annotations

import pytest

from memory.language_detect import detect_language


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("你好, 地下室要抽汙水, 你推薦哪一款泵浦?", "zh"),
        ("EUS 系列多少 HP？", "zh"),
        ("ポンプを探しています", "ja"),
        ("펌프 추천해 주세요", "ko"),
        ("Hi, which pump would you recommend for draining dirty water?", "en"),
        ("Hola, ¿qué bomba me recomiendas para sacar agua sucia?", "es"),
        # 沒有 ¿ ñ 也要靠常用字判斷出西語。
        ("quiero una bomba para el sotano", "es"),
        ("Guten Tag", "other"),
        ("", ""),
        ("12345 ???", ""),
    ],
)
def test_detect_language(text: str, expected: str):
    assert detect_language(text) == expected
