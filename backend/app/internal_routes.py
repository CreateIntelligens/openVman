"""Internal-only routes: receive enriched context from Gateway, forward to Brain."""

from __future__ import annotations

import hmac
import logging
from typing import Any

import httpx
from fastapi import APIRouter, Header, HTTPException
from pydantic import BaseModel, Field

from app.config import get_tts_config

logger = logging.getLogger("backend.internal")

router = APIRouter(tags=["Internal"])

INTERNAL_TOKEN_HEADER = "X-Internal-Token"

_client: httpx.AsyncClient | None = None


def _get_client() -> httpx.AsyncClient:
    global _client
    if _client is None:
        _client = httpx.AsyncClient(
            timeout=httpx.Timeout(connect=5, read=30, write=10, pool=5),
        )
    return _client


async def close_client() -> None:
    global _client
    if _client is not None:
        await _client.aclose()
        _client = None


class InternalEnrichRequest(BaseModel):
    trace_id: str = ""
    session_id: str | None = None
    enriched_context: list[dict[str, Any]] = Field(default_factory=list)
    media_refs: list[dict[str, Any]] = Field(default_factory=list)
    project_id: str = "default"
    persona_id: str = "default"


@router.post("/internal/enrich")
async def internal_enrich(
    payload: InternalEnrichRequest,
    x_internal_token: str = Header("", alias=INTERNAL_TOKEN_HEADER),
) -> dict[str, Any]:
    cfg = get_tts_config()

    if not hmac.compare_digest(x_internal_token, cfg.gateway_internal_token):
        raise HTTPException(status_code=403, detail="invalid internal token")

    brain_url = f"{cfg.brain_url}/internal/enrich"
    client = _get_client()

    try:
        resp = await client.post(brain_url, json=payload.model_dump())
        resp.raise_for_status()
        result = resp.json()
        logger.info(
            "enrich_forwarded trace_id=%s session_id=%s stored=%s",
            payload.trace_id,
            result.get("session_id"),
            result.get("stored_count"),
        )
        return result
    except httpx.ConnectError:
        logger.warning("brain unreachable at %s", brain_url)
        raise HTTPException(status_code=502, detail="brain service unavailable")
    except httpx.HTTPStatusError as exc:
        logger.error(
            "brain_enrich_error trace_id=%s status=%d",
            payload.trace_id,
            exc.response.status_code,
        )
        raise HTTPException(
            status_code=exc.response.status_code,
            detail=exc.response.text,
        )
