"""Rejected requests must not be reported as an unavailable Brain."""

from core.sse_events import build_exception_protocol_error


def test_validation_rejections_use_invalid_request():
    # 2026-10-16 串接方回報：空訊息回 400 卻標成 BRAIN_UNAVAILABLE，照錯誤碼判斷的
    # 用戶端會以為 Brain 掛了，前台也會跳整頁錯誤。
    for message in ("message 不可為空", "message 不可超過 2000 字"):
        payload = build_exception_protocol_error(ValueError(message))
        assert payload["error_code"] == "INVALID_REQUEST"
        assert payload["message"] == message


def test_session_limits_still_report_session_expired():
    payload = build_exception_protocol_error(ValueError("session 已過期"))
    assert payload["error_code"] == "SESSION_EXPIRED"


def test_rate_limit_is_429_overload_not_invalid_request():
    # 限流以前跟空訊息一樣是 400；改成 INVALID_REQUEST 後會叫串接端改寫問題，
    # 但正確做法是等 Retry-After 再送。
    from types import SimpleNamespace

    import pytest
    from fastapi import HTTPException

    from routes.chat import _handle_generation_error
    from safety.guardrails import RequestRateLimitedError

    request = SimpleNamespace(state=SimpleNamespace(trace_id="t-1"))
    with pytest.raises(HTTPException) as caught:
        _handle_generation_error(RequestRateLimitedError(12), "chat", request)

    assert caught.value.status_code == 429
    assert caught.value.headers == {"Retry-After": "12"}
    assert caught.value.detail["error_code"] == "LLM_OVERLOAD"
    assert caught.value.detail["retry_after_ms"] == 12000


def test_chat_openapi_documents_the_reply_fields():
    from main import app

    response = app.openapi()["paths"]["/brain/chat"]["post"]["responses"]["200"]
    ref = response["content"]["application/json"]["schema"]["$ref"]
    assert ref.endswith("/ChatResponse")
    fields = app.openapi()["components"]["schemas"]["ChatResponse"]["properties"]
    for name in ("reply", "session_id", "answer_source", "knowledge_searched", "no_answer"):
        assert name in fields
