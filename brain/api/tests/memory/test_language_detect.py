"""Tests for the chat language guess used by session filters and backups."""

from __future__ import annotations

import types

import pytest

import core.jev_client  # noqa: F401 - 先載入，免得綁到 fixture 換掉的 get_settings
from memory import language_detect
from memory.language_detect import detect_language, is_short_text


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
        # 日韓 2026-09-30 起各自成一種語言（見下方 test_japanese_and_korean_are_recognized_by_script）。
        ("ポンプを探しています", "ja"),
        ("펌프 추천해 주세요", "ko"),
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
    language_detect.refine_language_in_background("buenos dias amigo mio", "zh", changes.append)
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


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("請問急診佇佗位？阮阿母昨昏跋倒，跤頭趺腫起來矣。藥仔愛食飯前抑是食飯後？我欲去檢查血糖。", "nan"),
        ("Guá tsit-má thâu-khak tsiok thiànn, ài kuà tó tsi̍t kho? Kin-á-ji̍t mn̂g-tsín khui kàu kuí tiám?", "nan"),
        # 華語文件偶爾出現「給予」「欲望」不算台語。
        ("衛教資訊：術後請給予病人充足休息，避免食慾不振與過度的欲望壓力。急診位於一樓。" * 3, "zh"),
        ("Catálogo de bombas sumergibles. La serie EUS está disponible de 0.5 a 2 HP.", "es"),
        ("EVAK submersible pump catalog for basement drainage.", "en"),
    ],
)
def test_detect_document_language(text: str, expected: str):
    assert language_detect.detect_document_language(text) == expected


def test_long_chinese_document_with_a_stray_spanish_mark_stays_chinese():
    text = "竹東好玩的景點很多，推薦辣椒園與老街。" * 20 + " Peña "
    assert detect_language(text) == "zh"


@pytest.mark.parametrize(
    ("text", "default", "expected"),
    [
        # 一兩個字的招呼判斷不出語言，歸專案主要語言。
        ("hi", "zh", "zh"),
        ("hi", "en", "en"),
        ("hola", "es", "es"),
        ("ok thanks", "en", "en"),
        # 有中文就是中文，不管主要語言是什麼。
        ("EUS 多少", "en", "zh"),
        ("hi 你好", "es", "zh"),
        # 夠長就照內容判斷。
        ("Which pump do you recommend?", "es", "en"),
    ],
)
def test_short_or_unclear_text_falls_to_primary_language(text, default, expected):
    assert detect_language(text, default) == expected


def test_short_text_is_never_sent_to_jev(jev, monkeypatch):
    def boom(*_a, **_kw):
        raise AssertionError("short text should not reach Jev")

    monkeypatch.setattr("core.jev_client.jev_nouls", boom)
    language_detect.refine_language_in_background("hi", "zh", lambda _l: None)


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("このポンプの馬力はいくつですか？", "ja"),
        ("水中ポンプ", "ja"),
        ("ありがとう", "ja"),
        ("이 펌프의 마력은 얼마입니까?", "ko"),
        ("감사합니다", "ko"),
        # 中文句子引了一個日文品牌，不能整句變日文。
        ("我們的沉水泵搭配了新しい馬達控制器，請問保固多久", "zh"),
        ("50EUBL 的馬力是多少？", "zh"),
    ],
)
def test_japanese_and_korean_are_recognized_by_script(text, expected):
    assert detect_language(text) == expected


def test_short_japanese_and_korean_are_not_treated_as_unknown():
    # 「hi」「ok」會歸主要語言；「はい」「네」是看得出語言的。
    assert not is_short_text("はい")
    assert not is_short_text("네")


def test_jev_does_not_pull_japanese_back_to_chinese(monkeypatch):
    import memory.language_detect as ld

    called = []
    monkeypatch.setattr(ld, "_executor", type("E", (), {"submit": lambda self, fn: called.append(fn)})())
    ld.refine_language_in_background("このポンプの馬力はいくつですか？", "ja", lambda lang: None)
    assert called == []


def test_audio_language_reuses_one_gemini_client(monkeypatch):
    """每次新建 client 要 0.1–0.18 秒；backend 只等 2.5 秒。"""
    import google.genai as genai

    built: list[str] = []

    class FakeClient:
        def __init__(self, api_key, http_options=None):
            built.append(api_key)
            self.models = types.SimpleNamespace(
                generate_content=lambda **kw: types.SimpleNamespace(text='{"language": "nan"}'),
            )

    monkeypatch.setattr(genai, "Client", FakeClient)
    monkeypatch.setattr("config.get_settings", lambda: types.SimpleNamespace(
        gemini_api_key="k1", live_audio_language_id_model="m",
    ))
    language_detect._audio_language_client.cache_clear()
    try:
        assert language_detect.detect_audio_language(b"RIFF") == "nan"
        assert language_detect.detect_audio_language(b"RIFF") == "nan"
        assert built == ["k1"]
    finally:
        language_detect._audio_language_client.cache_clear()
