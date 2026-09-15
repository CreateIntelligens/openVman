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


@router.post("/api/v1/internal/enrich")
async def internal_enrich(
    payload: InternalEnrichRequest,
    x_internal_token: str = Header("", alias=INTERNAL_TOKEN_HEADER),
) -> dict[str, Any]:
    cfg = get_tts_config()

    if not cfg.gateway_internal_token:
        raise HTTPException(status_code=503, detail="internal token is not configured")
    if not hmac.compare_digest(x_internal_token, cfg.gateway_internal_token):
        raise HTTPException(status_code=403, detail="invalid internal token")

    brain_url = f"{cfg.brain_url}/internal/enrich"

    try:
        resp = await _http.get().post(
            brain_url,
            json=payload.model_dump(),
            headers={INTERNAL_TOKEN_HEADER: cfg.gateway_internal_token},
        )
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


class InternalA2ASendTaskRequest(BaseModel):
    target_agent_id: str = Field(..., min_length=1, max_length=256)
    message: str = Field(..., min_length=1, max_length=1_048_576)
    context_id: str | None = Field(default=None, max_length=256)
    hop_count: int = Field(default=1, ge=0, le=10)


class InternalA2ABroadcastGroupRequest(BaseModel):
    group_id: str = Field(..., min_length=1, max_length=256)
    message: str = Field(..., min_length=1, max_length=1_048_576)


def _check_internal_auth(token: str) -> None:
    cfg = get_tts_config()
    if not cfg.gateway_internal_token:
        raise HTTPException(status_code=503, detail="internal token is not configured")
    if not hmac.compare_digest(token, cfg.gateway_internal_token):
        raise HTTPException(status_code=403, detail="invalid internal token")


@router.get("/api/v1/internal/a2a/peers")
async def internal_a2a_peers(
    state: str | None = None,
    x_internal_token: str = Header("", alias=INTERNAL_TOKEN_HEADER),
) -> dict[str, Any]:
    _check_internal_auth(x_internal_token)
    cfg = get_tts_config()
    if not cfg.a2a_enabled:
        return {"peers": [], "enabled": False}

    from app.gateway.a2a_bridge import get_a2a_bridge_daemon
    daemon = get_a2a_bridge_daemon()
    if not daemon.is_leader or not daemon.client:
        raise HTTPException(status_code=503, detail="A2A bridge is not the active leader")
    if not daemon.client:
        raise HTTPException(status_code=503, detail="A2A client not initialized")

    peers = await daemon.client.list_peers(state=state)
    return {"peers": peers, "total": len(peers), "enabled": True}


@router.post("/api/v1/internal/a2a/tasks")
async def internal_a2a_send_task(
    payload: InternalA2ASendTaskRequest,
    x_internal_token: str = Header("", alias=INTERNAL_TOKEN_HEADER),
) -> dict[str, Any]:
    _check_internal_auth(x_internal_token)
    cfg = get_tts_config()
    if not cfg.a2a_enabled:
        raise HTTPException(status_code=503, detail="A2A integration is disabled")

    if payload.hop_count > cfg.a2a_max_delegation_hops:
        raise HTTPException(status_code=400, detail="Delegation hop limit exceeded")

    from app.gateway.a2a_bridge import get_a2a_bridge_daemon
    daemon = get_a2a_bridge_daemon()
    if not daemon.is_leader or not daemon.client:
        raise HTTPException(status_code=503, detail="A2A bridge is not the active leader")

    try:
        res = await daemon.client.send_task(
            target_agent_id=payload.target_agent_id,
            message=payload.message,
            context_id=payload.context_id,
        )
        return {"success": True, "target": payload.target_agent_id, "result": res}
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"Hub dispatch failed: {exc}")


@router.post("/api/v1/internal/a2a/groups/messages")
async def internal_a2a_broadcast_group(
    payload: InternalA2ABroadcastGroupRequest,
    x_internal_token: str = Header("", alias=INTERNAL_TOKEN_HEADER),
) -> dict[str, Any]:
    _check_internal_auth(x_internal_token)
    cfg = get_tts_config()
    if not cfg.a2a_enabled:
        raise HTTPException(status_code=503, detail="A2A integration is disabled")
    if not cfg.a2a_allow_group_broadcast:
        raise HTTPException(status_code=403, detail="A2A group broadcast is disabled")

    from app.gateway.a2a_bridge import get_a2a_bridge_daemon
    daemon = get_a2a_bridge_daemon()
    if not daemon.is_leader or not daemon.client:
        raise HTTPException(status_code=503, detail="A2A bridge is not the active leader")

    try:
        res = await daemon.client.broadcast_group(
            group_id=payload.group_id,
            message=payload.message,
        )
        return {"success": True, "groupId": payload.group_id, "result": res}
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"Group broadcast failed: {exc}")
