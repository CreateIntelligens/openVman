"""Each chat turn states the reply language explicitly.

鶴記實測（2026-09-24）：提示只寫「本專案主要語言：繁體中文」時，西語提問 6 題裡
2 題整句回中文（照抄人設裡的中文固定句）；改成每輪明講回答語言後 6 題全是西語。
"""

from __future__ import annotations

from collections import defaultdict

import pytest

from core import prompt_templates


@pytest.fixture(autouse=True)
def primary(monkeypatch):
    def use(code: str) -> None:
        monkeypatch.setattr(prompt_templates, "_primary_language", lambda project_id: code)

    use("zh")
    monkeypatch.setattr(prompt_templates, "_reply_seconds", lambda project_id: 20)
    return use


@pytest.mark.parametrize(
    ("message", "expected"),
    [
        ("¿Cuánto cuesta la bomba sumergible más pequeña?", "Español"),
        ("What is the max flow of the HIPPO series?", "English"),
        ("HIPPO 系列最大流量是多少？", "繁體中文"),
    ],
)
def test_clear_language_is_stated(message, expected):
    line = prompt_templates.reply_language_line("p", message)
    assert line.startswith(f"這一輪的回答語言：{expected}。")


def test_short_greeting_follows_the_primary_language(primary):
    primary("en")
    assert prompt_templates.reply_language_line("p", "hola").startswith(
        "這一輪的回答語言：English。",
    )


def test_short_spanish_question_is_answered_in_spanish():
    """鶴記實測（2026-10-02）：「¿Quién eres?」只有兩個字被歸主要語言，一直回中文。"""
    assert prompt_templates.reply_language_line("p", "¿Quién eres?").startswith(
        "這一輪的回答語言：Español。",
    )


def test_taiwanese_speech_is_answered_in_traditional_chinese():
    line = prompt_templates.reply_language_line("p", "我想欲問掛號", speech_language="nan")
    assert line.startswith("這一輪的回答語言：繁體中文。")


def test_unclear_language_is_left_to_the_model_without_naming_primary_first():
    line = prompt_templates.reply_language_line("p", "EUBL pump specs")
    # 不能寫成「判斷不出來就用主要語言」：模型會直接挑主要語言。
    assert "看使用者這句話是用哪種語言寫的就用哪種" in line
    assert "只有型號、數字這類看不出語言的輸入才用繁體中文" in line


def test_live_fallback_line_does_not_announce_a_project_language():
    line = prompt_templates.primary_language_line("p")
    assert "本專案主要語言" not in line
    assert "判斷不出來" in line


def test_chat_prompt_ends_with_the_reply_language(monkeypatch):
    from core import prompt_builder

    monkeypatch.setattr(
        prompt_builder, "load_core_workspace_context", lambda *a, **kw: defaultdict(str),
    )
    monkeypatch.setattr(prompt_builder, "_build_recall_block", lambda **kw: "")
    messages = prompt_builder.build_chat_messages(
        user_message="¿Qué bomba me recomiendan?",
        request_context={"project_id": "p", "metadata": {}},
        session_messages=[],
    )
    assert "這一輪的回答語言：Español。" in messages[0]["content"]
    assert "本專案主要語言：" not in messages[0]["content"]


def test_every_language_gets_a_speaking_time_budget():
    """虛擬人會念出來：長度用秒數定，再換成各語言的字數或單字數。"""
    spanish = prompt_templates.reply_language_line("p", "¿Cuántos caballos tiene la bomba de lodos?")
    english = prompt_templates.reply_language_line("p", "How much horsepower does the sludge pump have?")
    chinese = prompt_templates.reply_language_line("p", "污泥泵有幾匹馬力？")
    taiwanese = prompt_templates.reply_language_line("p", "我想欲問掛號", speech_language="nan")
    unclear = prompt_templates.reply_language_line("p", "EUBL pump specs")
    for line in (spanish, english, chinese, taiwanese, unclear):
        assert "要在 20 秒內念完" in line
        # 硬上限、沒有「要詳細規格可以更長」的例外：有例外時模型常拿它當理由寫長。
        assert "嚴格不超過" in line and "詳細規格" not in line
    assert "嚴格不超過 30 個單字" in spanish
    assert "嚴格不超過 30 個單字" in english
    assert "嚴格不超過 80 字" in chinese
    assert "嚴格不超過 80 字" in taiwanese
    assert "單字" not in chinese
    # 換語言不能多加說明：只有外語要這句。
    assert "不要因為換語言" in spanish and "不要因為換語言" not in chinese


@pytest.mark.parametrize("code", ["ja", "ko"])
def test_japanese_and_korean_budget_by_characters(code):
    line = prompt_templates.reply_length_line(code, 20)
    assert "嚴格不超過 80 字" in line
    assert "單字" not in line
    assert "不要因為換語言" in line


def test_project_seconds_are_converted_per_language(monkeypatch):
    """每個專案在後台填秒數：元復醫院 40 字＝10 秒。"""
    monkeypatch.setattr(prompt_templates, "_reply_seconds", lambda project_id: 10)
    chinese = prompt_templates.reply_language_line("p", "污泥泵有幾匹馬力？")
    spanish = prompt_templates.reply_language_line("p", "¿Cuántos caballos tiene la bomba de lodos?")
    assert "要在 10 秒內念完" in chinese and "嚴格不超過 40 字" in chinese
    assert "嚴格不超過 15 個單字" in spanish


def test_zero_seconds_means_no_length_rule(monkeypatch):
    """ESG 要照抄完整 QA 答案：設 0 就不加長度規則。"""
    monkeypatch.setattr(prompt_templates, "_reply_seconds", lambda project_id: 0)
    line = prompt_templates.reply_language_line("p", "污泥泵有幾匹馬力？")
    assert line == "這一輪的回答語言：繁體中文。整段回答都用繁體中文，不要夾雜其他語言。"
