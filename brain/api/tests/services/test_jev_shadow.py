"""Jev shadow: outbound boundary, daily cap, failure isolation, usage ledger."""

import json
import sys
from types import ModuleType

import httpx
import pytest

from config import BrainSettings
from core import jev_shadow as jev
from core.usage import usage_scope
from infra import usage_ledger

HISTORY = [
    {"role": "system", "content": "SYSTEM_PROMPT_SECRET"},
    {"role": "user", "content": "EARLIER_USER_TURN"},
    {"role": "tool", "content": "KNOWLEDGE_PASSAGE 內部規章全文"},
    {"role": "assistant", "content": "OLDER_ASSISTANT_REPLY"},
    {"role": "user", "content": "SECOND_USER_TURN"},
    {"role": "assistant", "content": "上一輪回覆，網址是 https://example.org/"},
]
# 使用者與助手的對話照正式流程送出；這兩類與判斷意圖無關，一律不送。
FORBIDDEN = ("SYSTEM_PROMPT_SECRET", "KNOWLEDGE_PASSAGE")
DIALOGUE = (
    "EARLIER_USER_TURN", "OLDER_ASSISTANT_REPLY", "SECOND_USER_TURN",
    "https://example.org/",
)
REPLY = {
    "model": "jev-1.13.0",
    "answers": {"route": {
        "type": "choice", "choice": "knowledge",
        "probabilities": {"knowledge": 0.9, "chat": 0.1}, "confidence": 0.85,
    }},
    "usage": {"input_tokens": 560, "output_tokens": 47},
}


@pytest.fixture
def cfg(monkeypatch):
    settings = BrainSettings(
        _env_file=None, jev_shadow_enabled=True, jev_shadow_sample_rate=1,
        typesafe_api_key="test-key", jev_shadow_daily_call_cap=2,
    )
    monkeypatch.setattr(jev, "get_settings", lambda: settings)
    return settings


@pytest.fixture(autouse=True)
def isolated(monkeypatch, tmp_path):
    # 其他測試會把 safety.observability 換成殘缺的 stub，這裡自備一個。
    metrics = ModuleType("safety.observability")
    metrics.get_metrics_store = lambda: Metrics()
    monkeypatch.setitem(sys.modules, "safety.observability", metrics)
    usage_ledger.set_usage_db_path(tmp_path / "usage.db")
    monkeypatch.setattr(jev, "_observer", None)
    monkeypatch.setattr(jev, "_observer_key", None)
    monkeypatch.setattr(jev, "_cooldown_until", 0.0)
    monkeypatch.setattr(jev, "_cap_day", "")
    monkeypatch.setattr(jev, "_cap_used", 0)
    yield
    usage_ledger.set_usage_db_path(None)


class Metrics:
    def increment(self, *args, **kwargs):
        pass

    def observe(self, *args, **kwargs):
        pass


class Sent(list):
    behaviour: dict


class InlineExecutor:
    def submit(self, fn, *args):
        fn(*args)


@pytest.fixture
def sent(monkeypatch):
    """Run work inline against a mock transport; collect every outbound request."""
    requests = Sent()
    behaviour = {"handler": lambda request: httpx.Response(200, json=REPLY)}

    def transport(request):
        requests.append(request)
        return behaviour["handler"](request)

    real_init = jev.JevIntentObserver.__init__

    def init(self, cfg):
        real_init(self, cfg)
        self.client._transport = httpx.MockTransport(transport)

    monkeypatch.setattr(jev.JevIntentObserver, "__init__", init)
    monkeypatch.setattr(jev, "_executor", InlineExecutor())
    requests.behaviour = behaviour
    return requests


def submit(message="門禁卡怎麼申請？", history=HISTORY):
    return jev.submit_jev_shadow(
        message=message, history=history, trace_id="trace-1",
        project_id="proj", actual_route="tool",
    )


def test_state_uses_main_flow_dialogue_without_system_or_tools():
    from infra.reflection import select_recent_messages

    state = jev.jev_state("現在的問題", HISTORY)
    assert set(state) == {"history", "message"}
    assert state["message"] == "現在的問題"
    dialogue = [r for r in HISTORY if r["role"] in {"user", "assistant"}]
    assert state["history"] == select_recent_messages(dialogue)
    assert {row["role"] for row in state["history"]} == {"user", "assistant"}
    assert jev.jev_state("嗨", [])["history"] == []


def test_outbound_request_never_carries_session_or_knowledge(cfg, sent):
    # 這是外送邊界唯一的防線：直接檢查送上線的位元組。
    assert submit() is True
    assert len(sent) == 1
    raw = sent[0].content.decode("utf-8")
    for marker in FORBIDDEN:
        assert marker not in raw
    for marker in DIALOGUE:
        assert marker in raw
    body = json.loads(raw)
    assert set(body) == {"state", "model", "questions"}
    assert set(json.loads(body["state"])) == {"history", "message"}
    assert sent[0].headers["authorization"] == "Bearer test-key"
    assert sent[0].url.path == "/v1/systemone"


def test_long_message_is_truncated_before_sending(cfg, sent):
    submit(message="問" * 5000, history=[])
    state = json.loads(json.loads(sent[0].content)["state"])
    assert len(state["message"]) == jev.MAX_MESSAGE_CHARS


def test_success_records_usage_under_shadow_kind(cfg, sent):
    with usage_scope(kind="chat", user_id="u1", session_id="s1"):
        submit()
    events = usage_ledger.list_usage_events(kind="intent_shadow")
    assert len(events) == 1
    event = events[0]
    assert event["provider"] == "typesafe"
    assert event["model"] == "jev-1.13.0"
    assert event["input_tokens"] == 560
    assert (event["user_id"], event["session_id"]) == ("u1", "s1")
    assert (event["project_id"], event["trace_id"]) == ("proj", "trace-1")


@pytest.mark.parametrize("override", [
    {"jev_shadow_enabled": False},
    {"typesafe_api_key": ""},
    {"jev_shadow_sample_rate": 0},
])
def test_gates_send_nothing(cfg, sent, override):
    for name, value in override.items():
        setattr(cfg, name, value)
    assert submit() is False
    assert sent == []


def test_daily_cap_stops_calls(cfg, sent):
    assert [submit(), submit(), submit()] == [True, True, False]
    assert len(sent) == 2


def test_daily_cap_is_seeded_from_ledger_after_restart(cfg, sent):
    submit()
    submit()
    jev._cap_day = ""  # 模擬 process 重啟：記憶體計數歸零
    jev._cap_used = 0
    assert submit() is False
    assert len(sent) == 2


@pytest.mark.parametrize("handler, status", [
    (lambda r: (_ for _ in ()).throw(httpx.ReadTimeout("slow")), "timeout"),
    (lambda r: httpx.Response(529, json={"error": "overloaded"}), "error"),
    (lambda r: httpx.Response(200, json={"answers": {}}), "error"),
])
def test_failure_cools_down_and_releases_slot(cfg, sent, handler, status, caplog):
    sent.behaviour["handler"] = handler
    caplog.set_level("INFO", logger=jev.__name__)
    assert submit() is True
    record = json.loads(caplog.records[-1].getMessage())
    assert record["status"] == status
    assert "test-key" not in caplog.text
    assert "門禁卡" not in caplog.text
    # 冷卻中不再外送，slot 也沒被卡住。
    assert submit() is False
    assert len(sent) == 1
    assert jev._slot.acquire(blocking=False)
    jev._slot.release()
    assert usage_ledger.list_usage_events(kind="intent_shadow") == []


def test_unknown_choice_is_rejected(cfg, sent, caplog):
    reply = json.loads(json.dumps(REPLY))
    reply["answers"]["route"]["choice"] = "ignore previous instructions"
    sent.behaviour["handler"] = lambda r: httpx.Response(200, json=reply)
    caplog.set_level("INFO", logger=jev.__name__)
    submit()
    assert json.loads(caplog.records[-1].getMessage())["status"] == "error"


def test_settings_defaults_are_conservative():
    settings = BrainSettings(_env_file=None)
    assert settings.jev_shadow_enabled is False
    assert settings.jev_shadow_sample_rate == 0.05
    assert settings.jev_shadow_timeout_seconds == 0.6
    assert settings.jev_shadow_cooldown_seconds == 60
    assert settings.jev_shadow_daily_call_cap == 2000
