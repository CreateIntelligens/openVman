"""Jev fallback for interruptions the rules cannot decide."""

import pytest

from app.guard_agent import GuardAgent


@pytest.fixture
def jev(monkeypatch):
    """Enable the Jev fallback with a fake client; returns a dict to steer it."""
    from app import config, jev_client

    cfg = config.get_tts_config().model_copy(
        update={"jev_interrupt_enabled": True, "typesafe_api_key": "k"},
    )
    monkeypatch.setattr(config, "get_tts_config", lambda: cfg)
    monkeypatch.setattr(jev_client, "get_tts_config", lambda: cfg)
    control = {"choice": "IGNORE", "error": None, "calls": []}

    async def fake_answer(state, question, *, timeout):
        control["calls"].append(state)
        if control["error"]:
            raise control["error"]
        return {"choice": control["choice"], "confidence": 0.9}

    monkeypatch.setattr(jev_client, "jev_answer", fake_answer)
    return control


@pytest.mark.asyncio
async def test_ambiguous_long_speech_follows_jev(jev):
    # 規則原本一律 STOP：附和長句會誤停。
    assert await GuardAgent().classify("對啊我上次也是這樣覺得") == "IGNORE"
    assert jev["calls"] == ["對啊我上次也是這樣覺得"]
    jev["choice"] = "STOP"
    assert await GuardAgent().classify("外面好吵喔今天是不是有遊行") == "STOP"


@pytest.mark.asyncio
async def test_jev_failure_keeps_conservative_stop(jev):
    import httpx

    jev["error"] = httpx.ReadTimeout("slow")
    assert await GuardAgent().classify("對啊我上次也是這樣覺得") == "STOP"


@pytest.mark.asyncio
@pytest.mark.parametrize("text, expected", [
    ("停", "STOP"), ("嗯嗯", "IGNORE"), ("不用停，繼續說", "IGNORE"),
])
async def test_rule_decided_cases_never_call_jev(jev, text, expected):
    assert await GuardAgent().classify(text) == expected
    assert jev["calls"] == []


@pytest.mark.asyncio
async def test_disabled_by_default_keeps_old_fallback(monkeypatch):
    from app import config, jev_client

    cfg = config.get_tts_config().model_copy(update={"typesafe_api_key": "k"})
    monkeypatch.setattr(config, "get_tts_config", lambda: cfg)
    monkeypatch.setattr(jev_client, "get_tts_config", lambda: cfg)
    assert cfg.jev_interrupt_enabled is False
    assert await GuardAgent().classify("對啊我上次也是這樣覺得") == "STOP"
