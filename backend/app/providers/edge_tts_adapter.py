"""In-process Edge-TTS adapter for TTS routing."""

from __future__ import annotations

import asyncio
import concurrent.futures
import io
from time import monotonic

import edge_tts

from app.config import TTSRouterConfig
from app.providers.base import NormalizedTTSResult, SynthesizeRequest

# Single shared thread pool for running async edge-tts from sync contexts.
_THREAD_POOL = concurrent.futures.ThreadPoolExecutor(max_workers=2)


class EdgeTTSAdapter:
    """Synthesize speech via edge-tts in-process (no HTTP hop)."""

    def __init__(self, config: TTSRouterConfig) -> None:
        self._voice = config.edge_tts_voice
        self._sample_rate = config.edge_tts_sample_rate
        self._max_text_length = config.edge_tts_max_text_length
        self._enabled = config.edge_tts_enabled

    @property
    def provider_name(self) -> str:
        return "edge-tts"

    @property
    def enabled(self) -> bool:
        return self._enabled

    def synthesize(self, request: SynthesizeRequest) -> NormalizedTTSResult:
        """Run edge-tts synthesis (sync wrapper around async API)."""
        text = request.text.strip()
        if not text:
            raise EdgeTTSError("text is required")

        if len(text) > self._max_text_length:
            raise EdgeTTSError(
                f"text exceeds max length {self._max_text_length}"
            )

        voice = request.voice_hint or self._voice

        t0 = monotonic()
        audio_bytes = _run_synthesis(text, voice)
        latency_ms = (monotonic() - t0) * 1000

        return NormalizedTTSResult(
            audio_bytes=audio_bytes,
            content_type="audio/mpeg",
            sample_rate=self._sample_rate,
            provider="edge-tts",
            route_kind="provider",
            route_target="edge-tts",
            latency_ms=round(latency_ms, 2),
            raw_metadata={"voice": voice},
        )


class EdgeTTSError(Exception):
    """Raised when edge-tts synthesis fails."""

    def __init__(self, detail: str = "") -> None:
        self.detail = detail
        self.status_code = 422
        super().__init__(f"Edge-TTS error: {detail}")


async def _synthesize_async(text: str, voice: str) -> bytes:
    """Async edge-tts streaming to bytes."""
    communicate = edge_tts.Communicate(text, voice)
    buf = io.BytesIO()
    async for chunk in communicate.stream():
        if chunk["type"] == "audio":
            buf.write(chunk["data"])
    return buf.getvalue()


def _run_synthesis(text: str, voice: str) -> bytes:
    """Run edge-tts async synthesis from a sync context.

    If an event loop is already running (e.g. inside FastAPI), offloads to
    a thread pool.  Otherwise uses asyncio.run directly.
    """
    try:
        asyncio.get_running_loop()
    except RuntimeError:
        return asyncio.run(_synthesize_async(text, voice))

    # Inside an async context -- run in a worker thread with its own loop.
    future = _THREAD_POOL.submit(asyncio.run, _synthesize_async(text, voice))
    return future.result()
