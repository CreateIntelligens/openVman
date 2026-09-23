"""Tests for the chat language guess used by session filters and backups."""

from __future__ import annotations

import types

import pytest

import core.jev_client  # noqa: F401 - 先載入，免得綁到 fixture 換掉的 get_settings
from memory import language_detect
from memory.language_detect import detect_language


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("你好, 地下室要抽汙水, 你推薦哪一款泵浦?", "zh"),
        # 中文夾型號仍是中文。
        ("EUS 系列多少 HP？", "zh"),
        ("DIVA PRO 有 agitator 嗎", "zh"),
        ("Hi, which pump would you recommend for draining dirty water?", "en"),
        ("Hola, ¿qué bomba me recomiendas para sacar agua sucia?", "es"),
        ("quiero una bomba para el sotano", "es"),
        # 其他語言與判斷不出來的都算中文。
        ("ポンプを探しています", "zh"),
        ("펌프 추천해 주세요", "zh"),
        ("Guten Tag", "zh"),
        ("", "zh"),
        ("12345 ???", "zh"),
    ],
)
def test_detect_language(text: str, expected: str):
    assert detect_language(text) == expected


class _InlineExecutor:
    def submit(self, fn):
        fn()


@pytest.fixture
def jev(monkeypatch):
    monkeypatch.setattr(language_detect, "_executor", _InlineExecutor())
    settings = types.SimpleNamespace(jev_language_enabled=True, jev_gate_timeout_seconds=2.0)
    monkeypatch.setattr("config.get_settings", lambda: settings)
    monkeypatch.setattr("core.jev_client.jev_available", lambda: True)
    return settings


def test_jev_overrides_rule_when_it_disagrees(jev, monkeypatch):
    monkeypatch.setattr(
        "core.jev_client.jev_nouls", lambda *a, **kw: {"en": 0.02, "es": 0.97},
    )
    changes: list[str] = []
    language_detect.refine_language_in_background("buenos dias", "zh", changes.append)
    assert changes == ["es"]


def test_jev_agreeing_or_failing_keeps_rule(jev, monkeypatch):
    changes: list[str] = []
    monkeypatch.setattr(
        "core.jev_client.jev_nouls", lambda *a, **kw: {"en": 0.1, "es": 0.1},
    )
    language_detect.refine_language_in_background("你好", "zh", changes.append)

    def boom(*_a, **_kw):
        raise RuntimeError("jev down")

    monkeypatch.setattr("core.jev_client.jev_nouls", boom)
    language_detect.refine_language_in_background("ok", "zh", changes.append)
    assert changes == []


def test_jev_disabled_never_calls(jev, monkeypatch):
    jev.jev_language_enabled = False

    def boom(*_a, **_kw):
        raise AssertionError("should not call Jev")

    monkeypatch.setattr("core.jev_client.jev_nouls", boom)
    language_detect.refine_language_in_background("ok", "zh", lambda _l: None)
