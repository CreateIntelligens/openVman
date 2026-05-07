"""Public embed API and WebSocket routes."""

from __future__ import annotations

import logging
import uuid
from pathlib import Path

from fastapi import APIRouter, File, Request, UploadFile, WebSocket
from fastapi.responses import JSONResponse, Response
from pydantic import BaseModel, Field

from app.brain_proxy import _proxy_to_brain
from app.config import get_tts_config
from app.gateway import websocket as websocket_routes
from app.gateway.auth_embed import (
    EmbedAuthContext,
    EmbedRateLimiter,
    host_allowed,
    host_from_url,
)
from app.gateway.embed_keys import EmbedKeyStore, get_embed_key_store
from app.gateway.ingestion_audio import transcribe
from app.providers.base import SynthesizeRequest
from app.service import TTSRouterService
from app.tts_text_cleaner import clean_for_tts
from app.utils.upload import UploadTooLargeError, cleanup_temp_path, persist_upload_to_tempfile

logger = logging.getLogger("gateway.embed.routes")
router = APIRouter(tags=["Embed"])

_service: TTSRouterService | None = None
_ws_key_store = get_embed_key_store()
_ws_rate_limiter = EmbedRateLimiter()


class EmbedSessionResponse(BaseModel):
    session_token: str
    tenant_id: str
    key_id: str


class EmbedTtsRequest(BaseModel):
    text: str = Field(..., min_length=1)
    voice: str = ""
    provider: str = ""


def _get_service() -> TTSRouterService:
    global _service
    _service = _service or TTSRouterService(get_tts_config())
    return _service


def _auth_context(request: Request) -> EmbedAuthContext:
    return request.state.embed_auth


def _log_request(path: str, auth: EmbedAuthContext) -> None:
    logger.info(
        "embed_route path=%s tenant_id=%s key_id=%s",
        path,
        auth.tenant_id,
        auth.key_id,
    )


@router.post("/api/embed/session", response_model=EmbedSessionResponse)
async def create_embed_session(request: Request) -> EmbedSessionResponse:
    auth = _auth_context(request)
    _log_request(str(request.url.path), auth)
    return EmbedSessionResponse(
        session_token=uuid.uuid4().hex,
        tenant_id=auth.tenant_id,
        key_id=auth.key_id,
    )


@router.post("/api/embed/chat")
async def embed_chat(request: Request) -> Response:
    auth = _auth_context(request)
    _log_request(str(request.url.path), auth)
    return await _proxy_to_brain(request, "chat")


@router.post("/api/embed/tts")
async def embed_tts(request: Request, body: EmbedTtsRequest) -> Response:
    auth = _auth_context(request)
    _log_request(str(request.url.path), auth)
    cleaned_text = clean_for_tts(body.text.strip())
    if not cleaned_text:
        return JSONResponse(status_code=400, content={"error": "empty text"})

    service = _get_service()
    try:
        output = service.synthesize(
            SynthesizeRequest(text=cleaned_text, voice_hint=body.voice),
            provider=body.provider,
        )
    except RuntimeError as exc:
        return JSONResponse(status_code=502, content={"error": str(exc)})

    headers = {
        "X-TTS-Latency-Ms": str(round(output.result.latency_ms, 2)),
        "X-TTS-Provider": output.result.provider,
        "X-TTS-Cache-Hit": "false",
    }
    if output.fallback:
        headers["X-TTS-Fallback"] = "true"
        headers["X-TTS-Fallback-Reason"] = output.fallback_reason

    return Response(
        content=output.result.audio_bytes,
        media_type=output.result.content_type,
        headers=headers,
    )


@router.post("/api/embed/asr")
async def embed_asr(request: Request, file: UploadFile = File(...)) -> JSONResponse:
    auth = _auth_context(request)
    _log_request(str(request.url.path), auth)
    cfg = get_tts_config()
    suffix = Path(file.filename or "").suffix
    trace_id = uuid.uuid4().hex
    tmp_path: str | None = None

    try:
        tmp_path, _ = await persist_upload_to_tempfile(
            file,
            suffix=suffix,
            max_bytes=cfg.markitdown_max_upload_bytes,
        )
        result = await transcribe(tmp_path, trace_id)
        return JSONResponse(
            content={
                "text": result.content,
                "content_type": result.content_type,
                "trace_id": trace_id,
            }
        )
    except UploadTooLargeError as exc:
        limit_mb = exc.limit_bytes / (1024 * 1024)
        return JSONResponse(
            status_code=413,
            content={"error": f"file too large; limit {limit_mb:.0f} MB"},
        )
    finally:
        await file.close()
        cleanup_temp_path(tmp_path)


@router.websocket("/ws/embed/{client_id}")
async def embed_websocket_endpoint(websocket: WebSocket, client_id: str) -> None:
    auth = _authenticate_websocket(websocket)
    if auth is None:
        await websocket.accept()
        await websocket.close(code=4401)
        return

    logger.info(
        "embed_ws_connect client_id=%s tenant_id=%s key_id=%s",
        client_id,
        auth.tenant_id,
        auth.key_id,
    )
    websocket.scope.setdefault("state", {})["embed_auth"] = auth
    await websocket_routes.websocket_endpoint(websocket, client_id)


def _authenticate_websocket(websocket: WebSocket) -> EmbedAuthContext | None:
    secret = websocket.query_params.get("api_key") or websocket.query_params.get("key")
    if not secret:
        return None

    record = _ws_key_store.get(secret)
    if record is None:
        return None

    source_host = _websocket_source_host(websocket)
    if source_host is not None and not host_allowed(source_host, record.allowed_domains):
        return None

    allowed, _retry_after = _ws_rate_limiter.check(record.key_id)
    if not allowed:
        return None

    return EmbedAuthContext(
        key_id=record.key_id,
        tenant_id=record.tenant_id,
        allowed_domains=list(record.allowed_domains),
    )


def _websocket_source_host(websocket: WebSocket) -> str | None:
    origin = websocket.headers.get("origin")
    if origin:
        return host_from_url(origin)
    referer = websocket.headers.get("referer")
    if referer:
        return host_from_url(referer)
    return None
