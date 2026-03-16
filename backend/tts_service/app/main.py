"""Edge-TTS worker — FastAPI service wrapping edge-tts."""

from __future__ import annotations

import io
import time
import uuid

import edge_tts
from fastapi import FastAPI, Response
from pydantic import BaseModel, Field

from app.config import TTSWorkerConfig, get_worker_config

app = FastAPI(title="Edge-TTS Worker")
_config: TTSWorkerConfig | None = None


def _get_config() -> TTSWorkerConfig:
    global _config
    if _config is None:
        _config = get_worker_config()
    return _config


# ---- Models ----

class SynthesizeBody(BaseModel):
    text: str
    speaker_id: str = ""
    locale: str = "zh-TW"
    sample_rate: int = 0
    request_id: str = Field(default_factory=lambda: uuid.uuid4().hex)


# ---- Routes ----

@app.get("/healthz")
async def healthz() -> dict:
    cfg = _get_config()
    return {
        "status": "ok",
        "service": "edge-tts",
        "engine": "edge-tts",
        "device": "cpu",
        "speaker_default": cfg.voice,
    }


@app.post("/v1/synthesize")
async def synthesize(body: SynthesizeBody) -> Response:
    cfg = _get_config()

    if not body.text.strip():
        return Response(
            content='{"error": "text is required"}',
            status_code=422,
            media_type="application/json",
        )

    if len(body.text) > cfg.max_text_length:
        return Response(
            content=f'{{"error": "text exceeds max length {cfg.max_text_length}"}}',
            status_code=422,
            media_type="application/json",
        )

    voice = body.speaker_id or cfg.voice
    request_id = body.request_id

    t0 = time.monotonic()
    communicate = edge_tts.Communicate(body.text, voice)

    buf = io.BytesIO()
    async for chunk in communicate.stream():
        if chunk["type"] == "audio":
            buf.write(chunk["data"])

    latency_ms = round((time.monotonic() - t0) * 1000, 2)
    audio_bytes = buf.getvalue()

    return Response(
        content=audio_bytes,
        media_type="audio/mpeg",
        headers={
            "X-Request-Id": request_id,
            "X-TTS-Latency-Ms": str(latency_ms),
            "X-Sample-Rate": str(cfg.sample_rate),
        },
    )
