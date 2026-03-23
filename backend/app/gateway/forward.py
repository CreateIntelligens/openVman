"""Forward enriched context to brain via Backend's /internal/enrich endpoint."""

from __future__ import annotations

import logging
from typing import Any

import httpx

from app.config import get_tts_config
from app.internal_routes import INTERNAL_TOKEN_HEADER

logger = logging.getLogger("gateway.forward")

_client: httpx.AsyncClient | None = None


def _get_client() -> httpx.AsyncClient:
    global _client
    if _client is None:
        _client = httpx.AsyncClient(
            timeout=httpx.Timeout(connect=5, read=10, write=10, pool=5),
        )
    return _client


async def close_client() -> None:
    global _client
    if _client is not None:
        await _client.aclose()
        _client = None


async def forward_to_brain(
    trace_id: str,
    session_id: str,
    enriched_context: list[dict[str, Any]],
    media_refs: list[dict[str, Any]] | None = None,
) -> bool:
    """POST enriched context to Backend's /internal/enrich endpoint.

    The Backend endpoint validates the internal token and forwards to Brain.
    Fire-and-forget: only logs errors, never raises.
    """
    cfg = get_tts_config()
    url = f"http://127.0.0.1:{cfg.backend_port}/internal/enrich"

    payload = {
        "trace_id": trace_id,
        "session_id": session_id,
        "enriched_context": enriched_context,
        "media_refs": media_refs or [],
    }

    headers = {INTERNAL_TOKEN_HEADER: cfg.gateway_internal_token}

    logger.info("forward_to_brain trace_id=%s session_id=%s url=%s", trace_id, session_id, url)

    try:
        client = _get_client()
        response = await client.post(url, json=payload, headers=headers)
        response.raise_for_status()
        logger.info("forward_ok trace_id=%s status=%d", trace_id, response.status_code)
        return True
    except Exception as exc:
        logger.error("forward_failed trace_id=%s err=%s", trace_id, exc)
        return False
