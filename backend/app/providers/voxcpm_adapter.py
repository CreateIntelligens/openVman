"""VoxCPM360 adapter for TTS routing.

Talks to the CastAgent-compatible ``/api/v1/tts/*`` surface exposed by the
VoxCPM360 gateway (see ``~/VoxCPM360/gateway/routes/castvoice.py``).
"""

from __future__ import annotations

import logging
from time import monotonic

import httpx

from app.config import TTSRouterConfig
from app.providers.base import NormalizedTTSResult, SynthesizeRequest

logger = logging.getLogger("provider.voxcpm")

VOXCPM_PROVIDER_NAME = "voxcpm"
# 無 TTS_VOXCPM_DEFAULT_VOICE 時的保底語音。VoxCPM2 依文字內容推斷語言，
# 參考音只決定音色，所以台語參考音唸華語文字仍是華語。
VOXCPM_DEFAULT_VOICE = "voxcpm2-cosy-young-female-01"
# VoxCPM2 輸出 48kHz WAV，gateway 再以 ffmpeg 轉 mp3（取樣率不變）。
# mp3 由瀏覽器自行解碼，此值只作為 cache metadata。
VOXCPM_SAMPLE_RATE = 48000
VOXCPM_CONTENT_TYPE = "audio/mpeg"
# 一次合成整段（非串流），GPU 排隊時可能超過一分鐘；上游 nginx 為 900s。
_REQUEST_TIMEOUT_SECONDS = 120.0


class VoxCPMAdapter:
    """Synthesize speech via VoxCPM360 (HTTP) and return a NormalizedTTSResult."""

    def __init__(self, config: TTSRouterConfig) -> None:
        base_url = config.tts_voxcpm_url.rstrip("/") if config.tts_voxcpm_url else ""
        self._url = f"{base_url}/api/v1/tts/synthesize" if base_url else ""
        self._default_voice = config.tts_voxcpm_default_voice or VOXCPM_DEFAULT_VOICE
        self._headers = _auth_headers(config.tts_voxcpm_api_key)
        self._client = httpx.Client(timeout=_REQUEST_TIMEOUT_SECONDS)

    @property
    def provider_name(self) -> str:
        return VOXCPM_PROVIDER_NAME

    @property
    def enabled(self) -> bool:
        return bool(self._url)

    def _build_payload(self, request: SynthesizeRequest) -> dict[str, str]:
        return {
            "text": request.text,
            "voice_id": request.voice_hint or self._default_voice,
            "format": "mp3",
        }

    def synthesize(self, request: SynthesizeRequest) -> NormalizedTTSResult:
        """POST to /api/v1/tts/synthesize on the VoxCPM360 gateway."""
        if not self._url:
            raise RuntimeError("VoxCPM URL is not configured")

        payload = self._build_payload(request)

        t0 = monotonic()
        try:
            response = self._client.post(
                self._url,
                json=payload,
                headers=self._headers,
            )
            latency_ms = (monotonic() - t0) * 1000

            if response.status_code >= 400:
                raise VoxCPMHTTPError(
                    status_code=response.status_code,
                    detail=response.text[:500],
                )

            return NormalizedTTSResult(
                audio_bytes=response.content,
                content_type=response.headers.get(
                    "content-type",
                    VOXCPM_CONTENT_TYPE,
                ),
                sample_rate=VOXCPM_SAMPLE_RATE,
                provider=VOXCPM_PROVIDER_NAME,
                route_kind="provider",
                route_target=VOXCPM_PROVIDER_NAME,
                latency_ms=round(latency_ms, 2),
                raw_metadata={
                    "voice_id": payload["voice_id"],
                    "status_code": response.status_code,
                    "request_id": response.headers.get("X-Request-ID", ""),
                },
            )
        except httpx.RequestError as exc:
            raise VoxCPMHTTPError(status_code=503, detail=f"Request failed: {exc}")


def _auth_headers(api_key: str) -> dict[str, str]:
    # 上游 TTS_API_KEY 留空即不驗證；這裡同樣留空就不送 Authorization。
    return {"Authorization": f"Bearer {api_key}"} if api_key else {}


class VoxCPMHTTPError(Exception):
    """Raised when VoxCPM360 returns an HTTP error."""

    def __init__(self, status_code: int, detail: str = "") -> None:
        self.status_code = status_code
        self.detail = detail
        super().__init__(f"VoxCPM HTTP {status_code}: {detail}")
