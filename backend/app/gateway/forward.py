"""Forward enriched context to brain service."""

from __future__ import annotations

import logging
from typing import Any

import httpx

from app.config import get_tts_config

logger = logging.getLogger("gateway.forward")


async def forward_to_brain(
    trace_id: str,
    session_id: str,
    enriched_context: dict[str, Any],
    media_refs: list[dict[str, Any]] | None = None,
) -> None:
    """POST enriched context to brain's internal endpoint.

    Fire-and-forget: only logs errors, never raises.
    """
    cfg = get_tts_config()
    url = f"{cfg.brain_url}/internal/enrich"

    payload = {
        "trace_id": trace_id,
        "session_id": session_id,
        "context": enriched_context,
        "media_refs": media_refs or [],
    }

    logger.info("forward_to_brain trace_id=%s session_id=%s url=%s", trace_id, session_id, url)

    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            response = await client.post(url, json=payload)
            response.raise_for_status()
            logger.info("forward_ok trace_id=%s status=%d", trace_id, response.status_code)
    except Exception as exc:
        logger.error("forward_failed trace_id=%s err=%s", trace_id, exc)
