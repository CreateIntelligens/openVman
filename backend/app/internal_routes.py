"""Internal-only routes: receive enriched context from Gateway, forward to Brain."""

from __future__ import annotations

import hmac
import logging
from typing import Any

import httpx
from fastapi import APIRouter, Header, HTTPException
from pydantic import BaseModel, Field

from app.config import get_tts_config
from app.http_client import SharedAsyncClient

logger = logging.getLogger("backend.internal")

router = APIRouter(tags=["Internal"])

INTERNAL_TOKEN_HEADER = "X-Internal-Token"

_http = SharedAsyncClient(read=8)


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

    try:
        resp = await _http.get().post(brain_url, json=payload.model_dump())
        resp.raise_for_status()
        result = resp.json()
        logger.info(
            "enrich_forwarded trace_id=%s session_id=%s stored=%s",
            payload.trace_id,
            result.get("session_id"),
            result.get("stored_count"),
        )
        return result
    except httpx.TimeoutException as exc:
        logger.warning(
            "brain_enrich_timeout trace_id=%s url=%s err=%r",
            payload.trace_id,
            brain_url,
            exc,
        )
        raise HTTPException(status_code=504, detail="brain enrich timeout") from exc
    except httpx.ConnectError as exc:
        logger.warning("brain unreachable at %s", brain_url)
        raise HTTPException(status_code=502, detail="brain service unavailable") from exc
    except httpx.RequestError as exc:
        logger.warning(
            "brain_enrich_request_error trace_id=%s url=%s err=%r",
            payload.trace_id,
            brain_url,
            exc,
        )
        raise HTTPException(status_code=502, detail="brain service unavailable") from exc
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
