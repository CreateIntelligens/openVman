"""VibeVoice adapter for TTS routing."""

from __future__ import annotations

import logging
from time import monotonic
import httpx

from app.config import TTSRouterConfig
from app.providers.base import NormalizedTTSResult, SynthesizeRequest

logger = logging.getLogger("provider.vibevoice")

VIBEVOICE_DEFAULT_SPEAKER = "0"
VIBEVOICE_SPEAKERS = ("0", "1", "2", "3")

class VibeVoiceAdapter:
    """Synthesize speech via VibeVoice (HTTP) and return a NormalizedTTSResult."""

    def __init__(self, config: TTSRouterConfig) -> None:
        self._config = config
        self._url = config.tts_vibevoice_url.rstrip("/") + "/tts" if config.tts_vibevoice_url else ""
        self._client = httpx.Client(timeout=30.0) # VibeVoice might take longer for 1.5b

    @property
    def provider_name(self) -> str:
        return "vibevoice"

    @property
    def enabled(self) -> bool:
        return bool(self._url)

    def synthesize(self, request: SynthesizeRequest) -> NormalizedTTSResult:
        """POST to /tts on the VibeVoice worker."""
        if not self._url:
            raise RuntimeError("VibeVoice URL is not configured")

        payload = {
            "text": request.text,
            "speaker": request.voice_hint or VIBEVOICE_DEFAULT_SPEAKER,
        }

        t0 = monotonic()
        try:
            resp = self._client.post(self._url, json=payload)
            latency_ms = (monotonic() - t0) * 1000

            if resp.status_code >= 400:
                raise VibeVoiceHTTPError(
                    status_code=resp.status_code,
                    detail=resp.text[:500],
                )

            return NormalizedTTSResult(
                audio_bytes=resp.content,
                content_type=resp.headers.get("content-type", "audio/mpeg"),
                sample_rate=request.sample_rate,
                provider="vibevoice",
                route_kind="provider",
                route_target="vibevoice",
                latency_ms=round(latency_ms, 2),
                raw_metadata={
                    "speaker": payload["speaker"],
                    "status_code": resp.status_code,
                },
            )
        except httpx.RequestError as exc:
            raise VibeVoiceHTTPError(status_code=503, detail=f"Request failed: {exc}")

class VibeVoiceHTTPError(Exception):
    """Raised when VibeVoice returns an HTTP error."""

    def __init__(self, status_code: int, detail: str = "") -> None:
        self.status_code = status_code
        self.detail = detail
        super().__init__(f"VibeVoice HTTP {status_code}: {detail}")
