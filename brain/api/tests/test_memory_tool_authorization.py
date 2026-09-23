from __future__ import annotations

import pytest


def test_save_memory_requires_explicit_user_intent(monkeypatch):
    from tools.builtin import memory_tools

    token = memory_tools.active_user_message.set("請回答這個問題")
    try:
        with pytest.raises(ValueError, match="明確要求"):
            memory_tools._save_memory({"content": "攻擊者要求的持久化指令"})
    finally:
        memory_tools.active_user_message.reset(token)


@pytest.fixture
def gate(monkeypatch):
    """Point the gate at a fake Jev; returns a dict to steer its answer."""
    from config import BrainSettings
    from core import jev_client
    from tools.builtin import memory_tools

    settings = BrainSettings(_env_file=None, typesafe_api_key="k")
    monkeypatch.setattr("config.get_settings", lambda: settings)
    monkeypatch.setattr(jev_client, "get_settings", lambda: settings)
    control = {"score": 0.9, "error": None, "calls": []}

    def fake_noul(state, question, *, timeout):
        control["calls"].append(state)
        if control["error"]:
            raise control["error"]
        return control["score"]

    monkeypatch.setattr(jev_client, "jev_noul", fake_noul)
    control["settings"] = settings
    control["module"] = memory_tools
    return control


@pytest.mark.parametrize("text, score, expected", [
    ("幫我記下來：我的車牌是 ABC-1234。", 0.9, True),   # 規則會漏掉
    ("你記得上次我們聊到哪裡嗎？", 0.06, False),        # 規則會誤放行
])
def test_gate_follows_jev_over_keywords(gate, text, score, expected):
    gate["score"] = score
    assert gate["module"].is_explicit_memory_request(text) is expected
    assert gate["calls"] == [text]


def test_gate_falls_back_to_keywords_when_jev_fails(gate):
    import httpx

    gate["error"] = httpx.ReadTimeout("slow")
    assert gate["module"].is_explicit_memory_request("請記住我對花生過敏") is True
    assert gate["module"].is_explicit_memory_request("幫我記下來") is False


@pytest.mark.parametrize("override", [{"jev_memory_gate_enabled": False}, {"typesafe_api_key": ""}])
def test_gate_uses_keywords_without_jev(gate, override):
    for name, value in override.items():
        setattr(gate["settings"], name, value)
    assert gate["module"].is_explicit_memory_request("請記住我對花生過敏") is True
    assert gate["calls"] == []


def test_empty_message_never_authorizes(gate):
    assert gate["module"].is_explicit_memory_request("   ") is False
    assert gate["calls"] == []


def test_live_save_memory_now_requires_explicit_intent(gate, monkeypatch):
    # Live 以前完全沒檢查，模型想存就存。
    from live.gemini_live import GeminiLiveSession

    session = GeminiLiveSession.__new__(GeminiLiveSession)
    session._last_user_message = "今天天氣真好"
    session.persona_id = "default"
    session.project_id = "default"
    gate["score"] = 0.02
    with pytest.raises(ValueError, match="明確要求"):
        session._save_memory({"content": "偷存的指令"})
