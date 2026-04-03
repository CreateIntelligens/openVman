"""IndexTTS adapter for TTS routing."""

from __future__ import annotations

import logging
from time import monotonic

import httpx

from app.config import TTSRouterConfig
from app.providers.base import NormalizedTTSResult, SynthesizeRequest

logger = logging.getLogger("provider.indextts")


class IndexTTSAdapter:
    """Synthesize speech via IndexTTS (HTTP) and return a NormalizedTTSResult."""

    def __init__(self, config: TTSRouterConfig) -> None:
        self._config = config
        base = config.tts_indextts_url.rstrip("/") if config.tts_indextts_url else ""
        self._url = f"{base}/tts" if base else ""
        self._default_character = config.tts_indextts_default_character
        self._client = httpx.Client(timeout=60.0)

    @property
    def provider_name(self) -> str:
        return "indextts"

    @property
    def enabled(self) -> bool:
        return bool(self._url)

    def synthesize(self, request: SynthesizeRequest) -> NormalizedTTSResult:
        """POST to /tts on the IndexTTS worker."""
        if not self._url:
            raise RuntimeError("IndexTTS URL is not configured")

        payload = {
            "text": request.text,
            "character": request.voice_hint or self._default_character,
        }

        t0 = monotonic()
        try:
            resp = self._client.post(self._url, json=payload)
            latency_ms = (monotonic() - t0) * 1000

            if resp.status_code >= 400:
                raise IndexTTSHTTPError(
                    status_code=resp.status_code,
                    detail=resp.text[:500],
                )

            return NormalizedTTSResult(
                audio_bytes=resp.content,
                content_type=resp.headers.get("content-type", "audio/wav"),
                sample_rate=16000,
                provider="indextts",
                route_kind="provider",
                route_target="indextts",
                latency_ms=round(latency_ms, 2),
                raw_metadata={
                    "character": payload["character"],
                    "status_code": resp.status_code,
                },
            )
        except httpx.RequestError as exc:
            raise IndexTTSHTTPError(status_code=503, detail=f"Request failed: {exc}")


class IndexTTSHTTPError(Exception):
    """Raised when IndexTTS returns an HTTP error."""

    def __init__(self, status_code: int, detail: str = "") -> None:
        self.status_code = status_code
        self.detail = detail
        super().__init__(f"IndexTTS HTTP {status_code}: {detail}")
