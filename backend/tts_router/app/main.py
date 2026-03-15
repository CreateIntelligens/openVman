"""TTS Router — FastAPI entry point with node failover."""

from __future__ import annotations

import uuid

from fastapi import FastAPI, Response
from pydantic import BaseModel, Field

from app.config import get_tts_config
from app.observability import get_metrics_snapshot
from app.providers.base import SynthesizeRequest
from app.service import TTSRouterService

app = FastAPI(title="TTS Router")
_service: TTSRouterService | None = None


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


@app.get("/healthz")
async def healthz() -> dict:
    svc = _get_service()
    nodes = svc.health_manager.get_all_states()
    return {
        "status": "ok",
        "service": "tts-router",
        "nodes": [
            {
                "node_id": n.node_id,
                "role": n.role,
                "healthy": n.healthy,
                "score": n.score,
            }
            for n in nodes
        ],
    }


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
            content=f'{{"error": "{exc}"}}',
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


@app.get("/metrics")
async def metrics() -> dict:
    return get_metrics_snapshot()
