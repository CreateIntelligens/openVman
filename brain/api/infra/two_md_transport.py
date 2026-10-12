"""HTTP transport, failure classification and telemetry for 2MD calls."""

from __future__ import annotations

import time
from collections.abc import Callable, Iterable
from typing import Any, TypeVar

import httpx

from infra.two_md_coordination import (
    Budget,
    note_endpoint_failure,
    wait_before_fallback,
)
from safety.observability import get_metrics_store, log_event

T = TypeVar("T")


class Url2mdUpstreamError(ValueError):
    """Classified upstream failure used to decide whether failover is safe."""

    def __init__(self, message: str, *, retryable: bool, reason: str, status_code: int = 0):
        super().__init__(message)
        self.retryable = retryable
        self.reason = reason
        self.status_code = status_code


def request_json(
    client: httpx.Client,
    method: str,
    endpoint: str,
    *,
    budget: Budget | None = None,
    **kwargs: Any,
) -> dict[str, Any]:
    # 這一台最多只能用掉剩餘預算，否則單台逾時就能吃掉整條鏈的時間。
    if budget is not None and (remaining := budget.remaining()) is not None:
        kwargs["timeout"] = httpx.Timeout(
            connect=min(5.0, remaining), read=remaining, write=min(10.0, remaining), pool=5,
        )
    try:
        response = client.request(method, endpoint, **kwargs)
        response.raise_for_status()
    except httpx.HTTPStatusError as exc:
        status_code = exc.response.status_code
        retryable = status_code in {408, 425, 429} or status_code >= 500
        raise Url2mdUpstreamError(
            f"2md HTTP error status={status_code}",
            retryable=retryable,
            reason=f"http_{status_code}",
            status_code=status_code,
        ) from exc
    except httpx.RequestError as exc:
        raise Url2mdUpstreamError(
            f"2md network error: {type(exc).__name__}",
            retryable=True,
            reason="network_error",
        ) from exc
    try:
        payload = response.json()
    except ValueError as exc:
        raise Url2mdUpstreamError(
            "2md 回傳不是有效 JSON",
            retryable=True,
            reason="invalid_json",
        ) from exc
    if not isinstance(payload, dict):
        raise Url2mdUpstreamError(
            "2md 回傳格式無效", retryable=True, reason="invalid_response"
        )
    code = payload.get("code")
    if isinstance(code, int) and code >= 400:
        retryable = code in {408, 425, 429} or code >= 500
        raise Url2mdUpstreamError(
            f"2md 回傳錯誤（code={code}）",
            retryable=retryable,
            reason=f"upstream_code_{code}",
            status_code=code,
        )
    return payload


def record_attempt(
    operation: str,
    base: str,
    attempt: int,
    *,
    result: str,
    reason: str = "",
    latency_ms: float = 0.0,
) -> None:
    get_metrics_store().increment(
        "url2md_attempts_total",
        operation=operation,
        provider=base,
        result=result,
    )
    get_metrics_store().observe(
        "url2md_latency_ms",
        latency_ms,
        operation=operation,
        provider=base,
        result=result,
    )
    log_event(
        "url2md_attempt",
        operation=operation,
        provider=base,
        attempt=attempt,
        result=result,
        reason=reason,
        latency_ms=round(latency_ms, 2),
    )


def record_operation(
    operation: str,
    *,
    result: str,
    attempts: int,
    provider: str = "",
    reason: str = "",
    result_count: int = 0,
    content_chars: int = 0,
    truncated: bool = False,
    usage_tokens: int | float | None = None,
) -> None:
    get_metrics_store().increment(
        "url2md_operations_total",
        operation=operation,
        result=result,
    )
    log_event(
        "url2md_operation",
        operation=operation,
        result=result,
        attempts=attempts,
        provider=provider,
        reason=reason,
        result_count=result_count,
        content_chars=content_chars,
        truncated=truncated,
        usage_tokens=usage_tokens,
    )


def run_fallback_chain(
    operation: str,
    endpoints: Iterable[tuple[str, Budget]],
    cfg: Any,
    attempt_call: Callable[[str, Budget, int, float], Any],
    *,
    failure_message: str,
    on_success: Callable[[str, int, float, Any], T] | None = None,
) -> T:
    """Try each endpoint in order until one answers.

    Anything *attempt_call* raises counts against that endpoint and may move
    on to the next one; *on_success* runs outside that handling, so its own
    errors propagate instead of triggering failover.
    """
    last_error: Exception | None = None
    attempts = 0
    for attempt, (base, budget) in enumerate(endpoints, start=1):
        attempts = attempt
        started_at = time.monotonic()
        try:
            value = attempt_call(base, budget, attempt, started_at)
        except Url2mdUpstreamError as exc:
            last_error = exc
            note_endpoint_failure(base, cfg)
            record_attempt(
                operation,
                base,
                attempt,
                result="failure",
                reason=exc.reason,
                latency_ms=(time.monotonic() - started_at) * 1000,
            )
            if not exc.retryable or not wait_before_fallback(cfg, budget, attempt):
                break
            continue
        except Exception as exc:  # noqa: BLE001 - malformed upstream data may be endpoint-local
            last_error = exc
            note_endpoint_failure(base, cfg)
            record_attempt(
                operation,
                base,
                attempt,
                result="failure",
                reason="invalid_response",
                latency_ms=(time.monotonic() - started_at) * 1000,
            )
            if not wait_before_fallback(cfg, budget, attempt):
                break
            continue
        if on_success is None:
            return value
        return on_success(base, attempt, started_at, value)

    record_operation(
        operation,
        result="failure",
        attempts=attempts,
        reason=getattr(last_error, "reason", "no_eligible_endpoint"),
    )
    raise ValueError(f"{failure_message}：{last_error}") from last_error
