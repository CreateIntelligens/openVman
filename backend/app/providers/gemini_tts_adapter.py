"""Gemini TTS for the routing chain: straight to Google, or through the relay."""

from __future__ import annotations

import asyncio
import logging
from collections.abc import AsyncIterator
from time import monotonic

import httpx

from app.auth.gemini_tts_route import gemini_route, gemini_route_usable
from app.auth.project_gemini_credentials import (
    GeminiCredential,
    resolve_gemini_credential,
)
from app.auth.settings_repository import TTS_GEMINI_ROUTE_DIRECT
from app.config import TTSRouterConfig
from app.providers import project_gemini_tts
from app.providers.base import NormalizedTTSResult, SynthesizeRequest
from app.upstream_guard import (
    knob,
    HopTimeout,
    describe_error,
    host_of,
    tts_http_timeout,
    tts_request_timeout,
)

logger = logging.getLogger("provider.gemini")

# Gemini TTS Console 的 stream=true 回應格式（見 API 文件）：raw PCM,
# 16-bit little-endian, mono, 24000Hz —— 固定值，不受 request 影響。
GEMINI_STREAM_SAMPLE_RATE = 24000
GEMINI_STREAM_CONTENT_TYPE = "audio/l16;rate=24000;channels=1"
GEMINI_DEFAULT_VOICE = "Kore"
GEMINI_PROVIDER_NAME = "gemini-tts"
GEMINI_DIRECT_HOST = host_of(project_gemini_tts.GOOGLE_API_BASE)
# Google 的預設聲音。直連與轉接服務用的是同一組名稱，所以聲音清單固定在這裡，
# 切換路線時能選的聲音不會變。
GEMINI_PREBUILT_VOICES = (
    "Achernar", "Achird", "Algenib", "Algieba", "Alnilam", "Aoede",
    "Autonoe", "Callirrhoe", "Charon", "Despina", "Enceladus", "Erinome",
    "Fenrir", "Gacrux", "Iapetus", "Kore", "Laomedeia", "Leda", "Orus",
    "Puck", "Pulcherrima", "Rasalgethi", "Sadachbia", "Sadaltager",
    "Schedar", "Sulafat", "Umbriel", "Vindemiatrix", "Zephyr",
    "Zubenelgenubi",
)


def shared_gemini_credential(runtime=None) -> GeminiCredential | None:
    """The deployment's own Gemini key (Admin or GEMINI_API_KEY), or None."""
    try:
        credential = (
            resolve_gemini_credential(None) if runtime is None
            else resolve_gemini_credential(None, runtime)
        )
    except Exception as exc:  # noqa: BLE001 - 讀不到金鑰就當沒有，直連不列入可用
        logger.warning("shared gemini credential unavailable: %s", exc)
        return None
    return credential if credential.configured else None


def gemini_tts_usable(cfg, runtime=None) -> bool:
    """Either route can run: a relay URL is set, or the shared key exists.

    登錄聲音資源用這條寬鬆的規則：專案綁了自己的金鑰時一律直連，不論後台選哪條
    路線都要選得到 Google 的聲音。
    """
    return bool(cfg.tts_gemini_url) or shared_gemini_credential(runtime) is not None


def gemini_tts_route_usable(cfg, runtime=None) -> bool:
    """The route chosen in the Admin can run (same rule as the adapter)."""
    return gemini_route_usable(
        gemini_route(cfg, runtime),
        relay_url=cfg.tts_gemini_url or "",
        has_shared_key=lambda: shared_gemini_credential(runtime) is not None,
    )


class GeminiTTSAdapter:
    """Synthesize Gemini speech by the route chosen in the Admin.

    專案綁了自己的金鑰時一律直連 Google；其餘看路線：direct 用本系統的共用金鑰
    直連，relay 經 TTS_GEMINI_URL 的轉接服務。
    """

    def __init__(self, config: TTSRouterConfig) -> None:
        self._config = config
        base = config.tts_gemini_url.rstrip("/") if config.tts_gemini_url else ""
        self._url = f"{base}/api/tts" if base else ""
        self._default_voice = GEMINI_DEFAULT_VOICE
        self._relay_host = host_of(base)
        self._client = httpx.Client(
            timeout=tts_http_timeout(config, knob(config, "tts_node_max_seconds")),
        )

    @property
    def route(self) -> str:
        return gemini_route(self._config)

    @property
    def host(self) -> str:
        if self.route == TTS_GEMINI_ROUTE_DIRECT:
            return GEMINI_DIRECT_HOST
        return self._relay_host

    @property
    def provider_name(self) -> str:
        return GEMINI_PROVIDER_NAME

    @property
    def enabled(self) -> bool:
        return gemini_tts_route_usable(self._config)

    def enabled_for(self, request: SynthesizeRequest) -> bool:
        return self.enabled or self._project_credential(request) is not None

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

    @staticmethod
    def _project_credential(request: SynthesizeRequest):
        project_id = request.usage_scope.get("project_id")
        if not project_id:
            return None
        credential = resolve_gemini_credential(str(project_id))
        return credential if credential.source == "project" else None

    def _google_credential(self, request: SynthesizeRequest):
        """The key to call Google with, or None to use the relay.

        專案自己的金鑰優先（兩條路線都一樣）；direct 沒有專案金鑰就用共用金鑰。
        """
        if self.route != TTS_GEMINI_ROUTE_DIRECT:
            return self._project_credential(request)
        project_id = request.usage_scope.get("project_id")
        credential = resolve_gemini_credential(
            str(project_id) if project_id else None,
        )
        if credential.source == "project" or credential.configured:
            return credential
        raise RuntimeError("Gemini TTS key is not configured")

    async def open_stream(
        self, request: SynthesizeRequest,
    ) -> AsyncIterator[bytes]:
        """驗證第一個回應沒有錯誤後，回傳串流 raw PCM 的 async iterator。

        與 synthesize_stream 不同：這是一般 async function（非 generator），
        會在回傳前就把請求送出並檢查 status code，讓呼叫端能在建立
        StreamingResponse（也就是送出 200 headers）之前就捕捉到錯誤，
        避免「headers 已送出、body 迭代中途才發現是 502」的中斷。
        """
        credential = self._google_credential(request)
        if credential is not None:
            return await project_gemini_tts.open_stream(
                request, credential, self._config.tts_gemini_model,
            )
        if not self._url:
            raise RuntimeError("Gemini TTS URL is not configured")

        cfg = self._config
        first_byte = knob(cfg, "tts_stream_first_byte_seconds")
        connect = min(knob(cfg, "tts_connect_timeout_seconds"), first_byte)
        client = httpx.AsyncClient(timeout=httpx.Timeout(
            connect=connect,
            read=max(first_byte, knob(cfg, "tts_stream_stall_seconds")),
            write=first_byte,
            pool=connect,
        ))
        req = client.build_request(
            "POST",
            self._url,
            json=self._build_payload(request, stream=True),
        )
        try:
            async with asyncio.timeout(first_byte):
                resp = await client.send(req, stream=True)
        except TimeoutError:
            await client.aclose()
            raise GeminiTTSHTTPError(
                status_code=504, detail=f"no response in {first_byte:.1f}s",
            ) from HopTimeout("first_byte", first_byte, GEMINI_PROVIDER_NAME)
        except httpx.RequestError as exc:
            await client.aclose()
            raise GeminiTTSHTTPError(
                status_code=503, detail=f"Request failed: {describe_error(exc)}",
            ) from exc

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
        """Synthesize with Google directly, or POST to the relay's /api/tts."""
        credential = self._google_credential(request)
        if credential is not None:
            return project_gemini_tts.synthesize(
                request, credential, self._config.tts_gemini_model, self._client,
                timeout=tts_request_timeout(self._config, request),
            )
        if not self._url:
            raise RuntimeError("Gemini TTS URL is not configured")

        payload = self._build_payload(request)

        t0 = monotonic()
        try:
            resp = self._client.post(
                self._url, json=payload,
                timeout=tts_request_timeout(self._config, request),
            )
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
            raise GeminiTTSHTTPError(
                status_code=503, detail=f"Request failed: {describe_error(exc)}",
            ) from exc


class GeminiTTSHTTPError(Exception):
    """Raised when Gemini TTS Console returns an HTTP error."""

    def __init__(self, status_code: int, detail: str = "") -> None:
        self.status_code = status_code
        self.detail = detail
        super().__init__(f"Gemini TTS HTTP {status_code}: {detail}")
