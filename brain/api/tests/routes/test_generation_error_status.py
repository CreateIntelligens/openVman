"""空回覆要回 502 + retry_after，不是 400。

2026-09-22 線上一筆：Gemini 連續兩輪回空（第一輪 agent_loop 已催過一次），
最後以 400 回給前端，且被算成 guardrail block。400 讓前端不重試、監控誤判；
而且那條路不記 log，錯誤訊息只進 metrics，得靠推理才拼回「LLM 沒有回傳內容」。
"""
from __future__ import annotations

from types import SimpleNamespace

import pytest
from core.llm_client import LLMEmptyReplyError
from fastapi import HTTPException
from protocol.protocol_events import ProtocolValidationError
from routes import chat as chat_route


@pytest.fixture
def request_with_trace() -> SimpleNamespace:
    return SimpleNamespace(state=SimpleNamespace(trace_id="trace-123"))


@pytest.fixture
def observed(monkeypatch: pytest.MonkeyPatch) -> dict[str, list]:
    calls: dict[str, list] = {"log_exception": [], "failures": [], "metrics": []}
    monkeypatch.setattr(
        chat_route,
        "log_exception",
        lambda event, exc, **fields: calls["log_exception"].append((event, exc, fields)),
    )
    monkeypatch.setattr(
        chat_route,
        "record_generation_failure",
        lambda action, kind, msg: calls["failures"].append((action, kind, msg)),
    )
    monkeypatch.setattr(
        chat_route,
        "get_metrics_store",
        lambda: SimpleNamespace(
            increment=lambda name, **labels: calls["metrics"].append((name, labels)),
        ),
    )
    return calls


def test_empty_reply_is_a_retryable_upstream_failure(
    request_with_trace: SimpleNamespace, observed: dict[str, list],
) -> None:
    with pytest.raises(HTTPException) as info:
        chat_route._handle_generation_error(
            LLMEmptyReplyError("LLM 沒有回傳內容"), "chat", request_with_trace,
        )

    assert info.value.status_code == 502
    assert info.value.detail["error_code"] == "LLM_OVERLOAD"
    assert info.value.detail["retry_after_ms"] == 3000
    # 是模型故障，不是 guardrail 擋下的壞請求。
    assert observed["failures"] == [("chat", "llm_failure", "LLM 沒有回傳內容")]
    assert observed["metrics"] == []
    # 這條路以前不記 log。
    assert [event for event, _, _ in observed["log_exception"]] == ["chat_empty_reply"]
    assert observed["log_exception"][0][2]["trace_id"] == "trace-123"


def test_empty_reply_still_short_circuits_the_fallback_chain() -> None:
    # fallback chain 靠 ``except ValueError: raise`` 讓空回覆不在下一個 hop 重試。
    # 改成不是 ValueError 的子類，那條路會悄悄變成「換 provider 再試一次」。
    assert issubclass(LLMEmptyReplyError, ValueError)


@pytest.mark.parametrize(
    "exc",
    [ValueError("句子超過長度上限"), ProtocolValidationError("bad envelope", version="v1")],
    ids=["guardrail", "protocol"],
)
def test_bad_requests_still_get_400_and_are_now_logged(
    exc: Exception, request_with_trace: SimpleNamespace, observed: dict[str, list],
) -> None:
    with pytest.raises(HTTPException) as info:
        chat_route._handle_generation_error(exc, "chat", request_with_trace)

    assert info.value.status_code == 400
    assert observed["metrics"] == [("guardrail_blocks_total", {"action": "chat"})]
    assert observed["failures"][0][1] == "validation"
    assert [event for event, _, _ in observed["log_exception"]] == ["chat_rejected"]
