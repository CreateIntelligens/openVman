"""Compatibility facade for Backend calls into the shared Brain decision broker."""

from __future__ import annotations

from typing import Any

import httpx

from app.config import get_tts_config

_client: httpx.AsyncClient | None = None


def _shared_client() -> httpx.AsyncClient:
    global _client
    if _client is None or _client.is_closed:
        _client = httpx.AsyncClient()
    return _client


def jev_available() -> bool:
    """Whether Backend can reach Brain's configured decision broker."""
    cfg = get_tts_config()
    return bool(cfg.brain_url and cfg.gateway_internal_token)


async def jev_answer(
    state: str | dict[str, Any] | list[Any] | None,
    question: dict[str, Any],
    *,
    timeout: float,
) -> dict[str, Any]:
    """Ask one typed question through Brain's shared provider chain."""
    cfg = get_tts_config()
    response = await _shared_client().post(
        f"{cfg.brain_url.rstrip('/')}/internal/decision",
        json={
            "state": state,
            "questions": {"q": question},
            "purpose": "interrupt",
            "timeout_seconds": timeout,
        },
        headers={"X-Internal-Token": cfg.gateway_internal_token},
        timeout=timeout,
    )
    response.raise_for_status()
    body = response.json()
    answers = body.get("answers")
    answer = answers.get("q") if isinstance(answers, dict) else None
    if not isinstance(answer, dict):
        raise ValueError("Brain decision response is missing the requested answer")
    return {
        **answer,
        "provider": body.get("provider", ""),
        "model": body.get("model", ""),
        "hop_id": body.get("hop_id", ""),
    }


__all__ = ["jev_answer", "jev_available"]
