"""Jev fallback for interruptions the rules cannot decide."""

import pytest

from app.guard_agent import GuardAgent


@pytest.fixture
def jev(monkeypatch):
    """Enable the Jev fallback with a fake client; returns a dict to steer it."""
    from app import config, jev_client

    cfg = config.get_tts_config().model_copy(
        update={"jev_interrupt_enabled": True, "gateway_internal_token": "internal-key"},
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
async def test_on_by_default(monkeypatch):
    """2026-10-02 改預設開：自寫 30 題規則 23/30、Jev 29/30。"""
    from app import config

    assert config.get_tts_config().model_copy().jev_interrupt_enabled is True


@pytest.mark.asyncio
async def test_without_internal_brain_access_keeps_the_conservative_stop(monkeypatch):
    from app import config, jev_client

    cfg = config.get_tts_config().model_copy(update={"gateway_internal_token": ""})
    monkeypatch.setattr(config, "get_tts_config", lambda: cfg)
    monkeypatch.setattr(jev_client, "get_tts_config", lambda: cfg)
    assert await GuardAgent().classify("對啊我上次也是這樣覺得") == "STOP"


@pytest.mark.asyncio
async def test_backend_decision_client_calls_brain_broker(monkeypatch):
    from types import SimpleNamespace
    from unittest.mock import AsyncMock

    from app import jev_client

    response = SimpleNamespace(
        raise_for_status=lambda: None,
        json=lambda: {"answers": {"q": {"type": "choice", "choice": "IGNORE"}}},
    )
    client = SimpleNamespace(post=AsyncMock(return_value=response))
    monkeypatch.setattr(jev_client, "get_tts_config", lambda: SimpleNamespace(
        brain_url="http://api:8100",
        gateway_internal_token="internal-key",
    ))
    monkeypatch.setattr(jev_client, "_shared_client", lambda: client)

    answer = await jev_client.jev_answer(
        "state", {"type": "choice", "criteria": {"STOP": "stop", "IGNORE": "ignore"}},
        timeout=0.6,
    )

    assert answer["choice"] == "IGNORE"
    assert client.post.await_args.args == ("http://api:8100/internal/decision",)
    assert client.post.await_args.kwargs["headers"] == {"X-Internal-Token": "internal-key"}
    assert client.post.await_args.kwargs["json"]["questions"]["q"]["type"] == "choice"
