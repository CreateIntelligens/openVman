"""Index TTS adapter for TTS routing."""

from __future__ import annotations

from time import monotonic

import httpx

from app.config import TTSRouterConfig
from app.providers.base import NormalizedTTSResult, SynthesizeRequest


class IndexTTSAdapter:
    """Synthesize speech via Index TTS (HTTP) and return a NormalizedTTSResult."""

    def __init__(self, config: TTSRouterConfig) -> None:
        self._config = config
        self._url = config.tts_index_url.rstrip("/") + "/tts" if config.tts_index_url else ""
        self._timeout = config.node_timeout_ms / 1000

    @property
    def provider_name(self) -> str:
        return "index"

    @property
    def enabled(self) -> bool:
        return bool(self._url)

    def synthesize(self, request: SynthesizeRequest) -> NormalizedTTSResult:
        """POST to /tts on the Index TTS worker."""
        if not self._url:
            raise RuntimeError("Index TTS URL is not configured")

        payload = {
            "text": request.text,
            "character": request.voice_hint or self._config.tts_index_character,
        }

        t0 = monotonic()
        with httpx.Client(timeout=self._timeout) as client:
            resp = client.post(self._url, json=payload)

        latency_ms = (monotonic() - t0) * 1000

        if resp.status_code >= 400:
            raise IndexTTSHTTPError(
                status_code=resp.status_code,
                detail=resp.text[:500],
            )

        return NormalizedTTSResult(
            audio_bytes=resp.content,
            content_type=resp.headers.get("content-type", "audio/mpeg"),
            sample_rate=request.sample_rate,
            provider="index",
            route_kind="provider",
            route_target="index-tts",
            latency_ms=round(latency_ms, 2),
            raw_metadata={
                "character": payload["character"],
                "status_code": resp.status_code,
            },
        )


class IndexTTSHTTPError(Exception):
    """Raised when Index TTS returns an HTTP error."""

    def __init__(self, status_code: int, detail: str = "") -> None:
        self.status_code = status_code
        self.detail = detail
        super().__init__(f"Index TTS HTTP {status_code}: {detail}")
