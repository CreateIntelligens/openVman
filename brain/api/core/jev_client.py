"""Synchronous single-question calls to Jev (TypeSafe System One).

給需要當下拿到答案的閘門用（例如 save_memory 授權、語言校正、串流定稿判斷）。
呼叫端負責在失敗時退回既有規則；這裡只丟例外，不吞。
每次呼叫（成功或失敗）都記一筆用量，kind 是呼叫端的用途：Jev 是外部 API，要算得出各功能
每天打了幾次；正式環境 docker log 看不到 info，不能靠 log 數。
"""

from __future__ import annotations

import json
from time import monotonic
from typing import Any

import httpx

from config import get_settings

MODEL = "jev-latest"
PROVIDER = "typesafe"


def jev_available() -> bool:
    return bool(get_settings().typesafe_api_key)


def jev_nouls(
    state: str, questions: dict[str, dict[str, Any]], *, timeout: float, purpose: str,
) -> dict[str, float]:
    """Ask several noul questions about one ``state`` in a single call.

    Jev 平行評估同一份 state 的所有題目，多題幾乎不加延遲。``purpose`` 記進用量的 kind
    （例如 jev_memory_gate），用來分功能統計。
    """
    cfg = get_settings()
    started = monotonic()
    body: dict[str, Any] = {}
    status = "error"
    try:
        response = httpx.post(
            f"{cfg.jev_base_url.rstrip('/')}/v1/systemone",
            json={
                "state": state,
                "model": MODEL,
                "questions": {
                    name: {"type": "noul", **question}
                    for name, question in questions.items()
                },
            },
            headers={"Authorization": f"Bearer {cfg.typesafe_api_key}"},
            timeout=timeout,
        )
        response.raise_for_status()
        body = response.json()
        answers = body["answers"]
        scores: dict[str, float] = {}
        for name in questions:
            value = answers[name]["noul"]
            if not isinstance(value, (int, float)) or not 0 <= value <= 1:
                raise ValueError(f"Unexpected noul value: {json.dumps(value)[:40]}")
            scores[name] = float(value)
        status = "ok"
        return scores
    except httpx.TimeoutException:
        status = "timeout"
        raise
    finally:
        _record_usage(purpose, body, status, len(questions), (monotonic() - started) * 1000)


def _record_usage(purpose: str, body: dict, status: str, questions: int, elapsed_ms: float) -> None:
    from core.usage import LLMUsage
    from infra.usage_ledger import record_usage_event

    usage = body.get("usage") or {}
    input_tokens = int(usage.get("input_tokens", 0) or 0)
    output_tokens = int(usage.get("output_tokens", 0) or 0)
    record_usage_event(
        provider=PROVIDER,
        model=str(body.get("model") or MODEL),
        usage=LLMUsage(
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            total_tokens=input_tokens + output_tokens,
        ),
        latency_ms=elapsed_ms,
        kind=f"jev_{purpose}",
        raw={"status": status, "questions": questions},
    )


def jev_noul(
    state: str, question: dict[str, Any], *, timeout: float, purpose: str,
) -> float:
    """Return the 0–1 yes-probability for one noul question about ``state``."""
    return jev_nouls(state, {"q": question}, timeout=timeout, purpose=purpose)["q"]
