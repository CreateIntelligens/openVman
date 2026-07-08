"""Gemini TTS Console adapter for TTS routing."""

from __future__ import annotations

from collections.abc import AsyncIterator
import logging
from time import monotonic

import httpx

from app.config import TTSRouterConfig
from app.providers.base import NormalizedTTSResult, SynthesizeRequest

logger = logging.getLogger("provider.gemini")

# Gemini TTS Console 的 stream=true 回應格式（見 API 文件）：raw PCM,
# 16-bit little-endian, mono, 24000Hz —— 固定值，不受 request 影響。
GEMINI_STREAM_SAMPLE_RATE = 24000
GEMINI_STREAM_CONTENT_TYPE = "audio/l16;rate=24000;channels=1"
GEMINI_DEFAULT_VOICE = "Kore"
GEMINI_PROVIDER_NAME = "gemini-tts"


class GeminiTTSAdapter:
    """Synthesize speech via Gemini TTS Console (HTTP) and return a NormalizedTTSResult."""

    def __init__(self, config: TTSRouterConfig) -> None:
        self._config = config
        base = config.tts_gemini_url.rstrip("/") if config.tts_gemini_url else ""
        self._url = f"{base}/api/tts" if base else ""
        self._default_voice = GEMINI_DEFAULT_VOICE
        self._client = httpx.Client(timeout=60.0)

    @property
    def provider_name(self) -> str:
        return GEMINI_PROVIDER_NAME

    @property
    def enabled(self) -> bool:
        return bool(self._url)

    def _build_payload(
        self,
        request: SynthesizeRequest,
        *,
        stream: bool = False,
    ) -> dict[str, str | bool]:
        payload: dict[str, str | bool] = {
            "text": request.text,
            "voice": request.voice_hint or self._default_voice,
        }
        if stream:
            payload["stream"] = True
        return payload

    async def open_stream(
        self, request: SynthesizeRequest,
    ) -> AsyncIterator[bytes]:
        """驗證第一個回應沒有錯誤後，回傳串流 raw PCM 的 async iterator。

        與 synthesize_stream 不同：這是一般 async function（非 generator），
        會在回傳前就把請求送出並檢查 status code，讓呼叫端能在建立
        StreamingResponse（也就是送出 200 headers）之前就捕捉到錯誤，
        避免「headers 已送出、body 迭代中途才發現是 502」的中斷。
        """
        if not self._url:
            raise RuntimeError("Gemini TTS URL is not configured")

        client = httpx.AsyncClient(timeout=60.0)
        req = client.build_request(
            "POST",
            self._url,
            json=self._build_payload(request, stream=True),
        )
        resp = await client.send(req, stream=True)

        if resp.status_code >= 400:
            detail = (await resp.aread()).decode("utf-8", errors="replace")[:500]
            await resp.aclose()
            await client.aclose()
            raise GeminiTTSHTTPError(status_code=resp.status_code, detail=detail)

        async def _iter_and_close() -> AsyncIterator[bytes]:
            try:
                async for chunk in resp.aiter_bytes():
                    if chunk:
                        yield chunk
            finally:
                await resp.aclose()
                await client.aclose()

        return _iter_and_close()

    def synthesize(self, request: SynthesizeRequest) -> NormalizedTTSResult:
        """POST to /api/tts on the Gemini TTS Console server."""
        if not self._url:
            raise RuntimeError("Gemini TTS URL is not configured")

        payload = self._build_payload(request)

        t0 = monotonic()
        try:
            resp = self._client.post(self._url, json=payload)
            latency_ms = (monotonic() - t0) * 1000

            if resp.status_code >= 400:
                raise GeminiTTSHTTPError(
                    status_code=resp.status_code,
                    detail=resp.text[:500],
                )

            return NormalizedTTSResult(
                audio_bytes=resp.content,
                content_type=resp.headers.get("content-type", "audio/wav"),
                sample_rate=GEMINI_STREAM_SAMPLE_RATE,
                provider=GEMINI_PROVIDER_NAME,
                route_kind="provider",
                route_target=GEMINI_PROVIDER_NAME,
                latency_ms=round(latency_ms, 2),
                raw_metadata={
                    "voice": payload["voice"],
                    "status_code": resp.status_code,
                    "seed": resp.headers.get("X-Seed", ""),
                },
            )
        except httpx.RequestError as exc:
            raise GeminiTTSHTTPError(status_code=503, detail=f"Request failed: {exc}")


class GeminiTTSHTTPError(Exception):
    """Raised when Gemini TTS Console returns an HTTP error."""

    def __init__(self, status_code: int, detail: str = "") -> None:
        self.status_code = status_code
        self.detail = detail
        super().__init__(f"Gemini TTS HTTP {status_code}: {detail}")
