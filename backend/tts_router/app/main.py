"""TTS Router — FastAPI entry point.

Serves both TTS synthesis and MarkItDown document conversion.
"""

from __future__ import annotations

import json
import logging
import os
import tempfile
import uuid

from fastapi import FastAPI, File, Response, UploadFile
from fastapi.responses import JSONResponse
from markitdown import MarkItDown
from pydantic import BaseModel, Field

from app.config import get_tts_config
from app.observability import get_metrics_snapshot
from app.providers.base import SynthesizeRequest
from app.service import TTSRouterService

logger = logging.getLogger("tts-router")

app = FastAPI(title="TTS Router")
_service: TTSRouterService | None = None
_md_converter = MarkItDown()


def _get_service() -> TTSRouterService:
    global _service
    if _service is None:
        _service = TTSRouterService(get_tts_config())
    return _service


class SynthesizeBody(BaseModel):
    text: str
    speaker_id: str = ""
    locale: str = "zh-TW"
    sample_rate: int = 24000
    request_id: str = Field(default_factory=lambda: uuid.uuid4().hex)


# ---------------------------------------------------------------------------
# Health & metrics
# ---------------------------------------------------------------------------


@app.get("/healthz")
async def healthz() -> dict:
    return {"status": "ok", "service": "tts-router"}


@app.get("/metrics")
async def metrics() -> dict:
    return get_metrics_snapshot()


# ---------------------------------------------------------------------------
# TTS synthesis
# ---------------------------------------------------------------------------


@app.post("/v1/synthesize")
async def synthesize(body: SynthesizeBody) -> Response:
    svc = _get_service()
    request = SynthesizeRequest(
        text=body.text,
        locale=body.locale,
        sample_rate=body.sample_rate,
        voice_hint=body.speaker_id,
    )

    try:
        result = svc.synthesize(request)
    except RuntimeError as exc:
        return Response(
            content=json.dumps({"error": str(exc)}),
            status_code=502,
            media_type="application/json",
        )

    return Response(
        content=result.audio_bytes,
        media_type=result.content_type,
        headers={
            "X-Request-Id": body.request_id,
            "X-TTS-Latency-Ms": str(round(result.latency_ms, 2)),
            "X-TTS-Provider": result.provider,
            "X-TTS-Route-Target": result.route_target,
            "X-Sample-Rate": str(result.sample_rate),
        },
    )


# ---------------------------------------------------------------------------
# MarkItDown — document-to-markdown conversion
# ---------------------------------------------------------------------------


@app.post("/convert")
async def convert(file: UploadFile = File(...)) -> JSONResponse:
    suffix = ""
    if file.filename:
        _, suffix = os.path.splitext(file.filename)

    tmp_path: str | None = None
    try:
        content = await file.read()

        with tempfile.NamedTemporaryFile(delete=False, suffix=suffix) as tmp:
            tmp.write(content)
            tmp_path = tmp.name

        logger.info("Converting file: %s (%d bytes)", file.filename, len(content))
        result = _md_converter.convert(tmp_path)

        return JSONResponse(
            content={
                "markdown": result.text_content,
                "page_count": None,
            }
        )
    except Exception as exc:
        logger.error("Conversion failed: %s", exc)
        return JSONResponse(
            status_code=500,
            content={"error": str(exc)},
        )
    finally:
        if tmp_path is not None:
            os.unlink(tmp_path)
