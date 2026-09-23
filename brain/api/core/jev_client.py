"""Synchronous single-question calls to Jev (TypeSafe System One).

給需要當下拿到答案的閘門用（例如 save_memory 授權）。背景觀測走 jev_shadow。
呼叫端負責在失敗時退回既有規則；這裡只丟例外，不吞。
"""

from __future__ import annotations

import json
from typing import Any

import httpx

from config import get_settings

MODEL = "jev-latest"


def jev_available() -> bool:
    return bool(get_settings().typesafe_api_key)


def jev_nouls(
    state: str, questions: dict[str, dict[str, Any]], *, timeout: float,
) -> dict[str, float]:
    """Ask several noul questions about one ``state`` in a single call.

    Jev 平行評估同一份 state 的所有題目，多題幾乎不加延遲。
    """
    cfg = get_settings()
    response = httpx.post(
        f"{cfg.jev_shadow_base_url.rstrip('/')}/v1/systemone",
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
    answers = response.json()["answers"]
    scores: dict[str, float] = {}
    for name in questions:
        value = answers[name]["noul"]
        if not isinstance(value, (int, float)) or not 0 <= value <= 1:
            raise ValueError(f"Unexpected noul value: {json.dumps(value)[:40]}")
        scores[name] = float(value)
    return scores


def jev_noul(state: str, question: dict[str, Any], *, timeout: float) -> float:
    """Return the 0–1 yes-probability for one noul question about ``state``."""
    return jev_nouls(state, {"q": question}, timeout=timeout)["q"]
