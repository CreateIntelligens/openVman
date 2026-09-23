"""Async single-question calls to Jev (TypeSafe System One) for the backend.

backend 與 brain 是兩個獨立 runtime，不共用 brain/api/core/jev_client.py。
呼叫端自己決定失敗時退回什麼；這裡只丟例外。
"""

from __future__ import annotations

from typing import Any

import httpx

from app.config import get_tts_config

MODEL = "jev-latest"

# 共用連線：每次新開要重做 TLS 握手，實測第一次呼叫約 800 ms，會吃掉語音打斷
# 600 ms 的預算。backend 只跑一個 event loop，所以一個 client 就夠。
_client: httpx.AsyncClient | None = None


def _shared_client() -> httpx.AsyncClient:
    global _client
    if _client is None or _client.is_closed:
        _client = httpx.AsyncClient()
    return _client


def jev_available() -> bool:
    return bool(get_tts_config().typesafe_api_key)


async def jev_answer(state: str, question: dict[str, Any], *, timeout: float) -> dict[str, Any]:
    """Ask one question about ``state``; returns Jev's answer object."""
    cfg = get_tts_config()
    response = await _shared_client().post(
        f"{cfg.jev_base_url.rstrip('/')}/v1/systemone",
        json={"state": state, "model": MODEL, "questions": {"q": question}},
        headers={"Authorization": f"Bearer {cfg.typesafe_api_key}"},
        timeout=timeout,
    )
    response.raise_for_status()
    return response.json()["answers"]["q"]
