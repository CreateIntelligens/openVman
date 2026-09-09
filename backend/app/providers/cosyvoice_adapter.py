"""CosyVoice3 adapter for TTS routing (臺灣台語).

Talks to the CastAgent-compatible ``/v1/*`` surface exposed by the CosyVoice3
service.  Same request shape as the VoxCPM360 gateway, but the endpoints live
directly under ``/v1`` instead of ``/api/v1/tts``.

輸入華語中文即可，繁簡字形轉換由服務端完成；串流端點的自訂 JSON-line 格式
與本服務的 PCM 串流不相容，故只走同步合成。
"""

from __future__ import annotations

import logging
from time import monotonic
from urllib.parse import unquote

import httpx

from app.config import TTSRouterConfig
from app.providers.base import NormalizedTTSResult, SynthesizeRequest

logger = logging.getLogger("provider.cosyvoice")

COSYVOICE_PROVIDER_NAME = "cosyvoice"
# 無 TTS_COSYVOICE_DEFAULT_VOICE 時的保底語音（青年男聲，音域窄、平穩）。
COSYVOICE_DEFAULT_VOICE = "young-male-02"
# 服務端以 ffmpeg 轉 mp3 後回傳；此值只作為 cache metadata。
COSYVOICE_SAMPLE_RATE = 24000
COSYVOICE_CONTENT_TYPE = "audio/mpeg"
# 長文會在服務端自動分段合成再串接，GPU 排隊時可能超過一分鐘。
_REQUEST_TIMEOUT_SECONDS = 120.0


class CosyVoiceAdapter:
    """Synthesize speech via CosyVoice3 (HTTP) and return a NormalizedTTSResult."""

    def __init__(self, config: TTSRouterConfig) -> None:
        base_url = (
            config.tts_cosyvoice_url.rstrip("/")
            if config.tts_cosyvoice_url
            else ""
        )
        self._base_url = base_url
        self._url = f"{base_url}/synthesize" if base_url else ""
        self._default_voice = (
            config.tts_cosyvoice_default_voice or COSYVOICE_DEFAULT_VOICE
        )
        self._headers = _auth_headers(config.tts_cosyvoice_api_key)
        self._client = httpx.Client(timeout=_REQUEST_TIMEOUT_SECONDS)

    @property
    def provider_name(self) -> str:
        return COSYVOICE_PROVIDER_NAME

    @property
    def enabled(self) -> bool:
        return bool(self._url)

    def _build_payload(self, request: SynthesizeRequest) -> dict[str, object]:
        return {
            "text": request.text,
            "voice_id": request.voice_hint or self._default_voice,
            "format": "mp3",
        }

    def synthesize(self, request: SynthesizeRequest) -> NormalizedTTSResult:
        """POST to /v1/synthesize on the CosyVoice3 service."""
        if not self._url:
            raise RuntimeError("CosyVoice URL is not configured")

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
                raise CosyVoiceHTTPError(
                    status_code=response.status_code,
                    detail=response.text[:500],
                )

            return NormalizedTTSResult(
                audio_bytes=response.content,
                content_type=response.headers.get(
                    "content-type",
                    COSYVOICE_CONTENT_TYPE,
                ),
                sample_rate=COSYVOICE_SAMPLE_RATE,
                provider=COSYVOICE_PROVIDER_NAME,
                route_kind="provider",
                route_target=COSYVOICE_PROVIDER_NAME,
                latency_ms=round(latency_ms, 2),
                raw_metadata={
                    "voice_id": payload["voice_id"],
                    "status_code": response.status_code,
                    # 服務端回報實際使用的模型版本、轉出的台文，以及仍會念錯
                    # 的字；發音有問題時用來分辨是漢字轉換錯還是模型念錯。
                    # 非 ASCII 的標頭值由服務端 percent-encode。
                    "model_version": response.headers.get("X-Model-Version", ""),
                    "spoken_text": unquote(
                        response.headers.get("X-Spoken-Text", ""),
                    ),
                    "unfixable": unquote(
                        response.headers.get("X-Unfixable", ""),
                    ),
                },
            )
        except httpx.RequestError as exc:
            raise CosyVoiceHTTPError(
                status_code=503,
                detail=f"Request failed: {exc}",
            ) from exc


def _auth_headers(api_key: str) -> dict[str, str]:
    # 上游留空即不驗證；這裡同樣留空就不送 Authorization。
    return {"Authorization": f"Bearer {api_key}"} if api_key else {}


class CosyVoiceHTTPError(Exception):
    """Raised when CosyVoice3 returns an HTTP error."""

    def __init__(self, status_code: int, detail: str = "") -> None:
        self.status_code = status_code
        self.detail = detail
        super().__init__(f"CosyVoice HTTP {status_code}: {detail}")
