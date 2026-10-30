"""VoxCPM360 adapter for TTS routing.

Talks to the VoxCPM360 studio API: ``POST /api/v1/synthesize`` for one-shot
synthesis and ``POST /api/v1/synthesize/stream`` for incremental playback.
Both take multipart form fields, not JSON — see ``/api/v1/catalog`` for the
engines and reference presets a given deployment exposes.
"""

from __future__ import annotations

import asyncio
import logging
import re
from collections.abc import AsyncIterator
from dataclasses import replace
from time import monotonic

import httpx

from app.config import TTSRouterConfig
from app.providers.base import NormalizedTTSResult, SynthesizeRequest
from app.tts_hanji import HanjiConverter
from app.upstream_guard import (
    knob,
    HopTimeout,
    describe_error,
    exempt,
    first_chunk,
    host_of,
    tts_http_timeout,
    tts_request_timeout,
)

logger = logging.getLogger("provider.voxcpm")

VOXCPM_PROVIDER_NAME = "voxcpm"
# /api/v1/catalog 公布的引擎 id；這個部署只有 voxcpm2。
VOXCPM_ENGINE_ID = "voxcpm2"
# 無 TTS_VOXCPM_DEFAULT_VOICE 時的保底語音：Hayley，與 IndexTTS 的 hayley、CosyVoice 的
# young-female-02 同一位，備援換引擎時聲音不變。VoxCPM2 依文字內容推斷語言，
# 參考音只決定音色，所以台語參考音唸華語文字仍是華語。
VOXCPM_DEFAULT_VOICE = "voxcpm2-cosy-young-female-02"
# catalog 的模型 id：完整 checkpoint（full::）或 LoRA（lora::）。
VOXCPM_MODEL_ID = re.compile(r"(?:full|lora)::[A-Za-z0-9._-]{1,128}")
# VoxCPM2 輸出 48kHz WAV，gateway 再以 ffmpeg 轉 mp3（取樣率不變）。
# mp3 由瀏覽器自行解碼，此值只作為 cache metadata。
VOXCPM_SAMPLE_RATE = 48000
VOXCPM_CONTENT_TYPE = "audio/mpeg"
VOXCPM_STREAM_CONTENT_TYPE = "audio/wav; rate=48000"
# 整段合成的逾時依文字長度計算（upstream_guard.tts_node_seconds），上游 nginx 為 900s。
# 合成前先看 /api/v1/health：推論 worker 死掉時回 503。2026-10-01 worker 被 OOM 殺掉、
# health 卻照回 ok，每句都等滿 120 秒才退到 Edge，持續約 7 小時。結果快取一小段時間，
# 不讓每句多一次往返。
_HEALTH_TIMEOUT_SECONDS = 2.0
_HEALTH_CACHE_SECONDS = 10.0


def _resolve_reference_preset(voice: str) -> str:
    """從 voice_id 解析出 reference_preset_id（去除 voxcpm2- 前綴）。"""
    return voice.removeprefix("voxcpm2-")


class VoxCPMAdapter:
    """Synthesize speech via VoxCPM360 (HTTP) and return a NormalizedTTSResult or stream."""

    def __init__(self, config: TTSRouterConfig) -> None:
        base_url = config.tts_voxcpm_url.rstrip("/") if config.tts_voxcpm_url else ""
        # 兩個端點不是同一套 API，刻意分開：
        #   /api/v1/tts/synthesize  CastVoice 相容，JSON + voice_id，回 mp3。
        #   /api/v1/synthesize      studio UI 用，multipart，固定回 48 kHz WAV。
        # 同一句 49 字實測 155 KB 對 1.38 MB，差 9 倍，所以整段合成走前者；
        # 但 CastVoice 沒有串流版本，要低首音延遲只能走後者的 /stream。
        self._url = f"{base_url}/api/v1/tts/synthesize" if base_url else ""
        self._stream_url = f"{base_url}/api/v1/synthesize/stream" if base_url else ""
        self._health_url = f"{base_url}/api/v1/health" if base_url else ""
        self._health: tuple[float, str] | None = None
        self._default_voice = config.tts_voxcpm_default_voice or VOXCPM_DEFAULT_VOICE
        self._inference_timesteps = str(config.tts_voxcpm_inference_timesteps)
        self._headers = _auth_headers(config.tts_voxcpm_api_key)
        self._hanji = HanjiConverter(config)
        self._hanji_version = getattr(config, "tts_voxcpm_hanji_version", "v6")
        self._config = config
        self._host = host_of(base_url)
        self._client = httpx.Client(
            timeout=tts_http_timeout(config, knob(config, "tts_node_max_seconds")),
        )

    @property
    def host(self) -> str:
        return self._host

    @property
    def default_voice(self) -> str:
        """The voice used when a request carries none."""
        return self._default_voice

    @property
    def provider_name(self) -> str:
        return VOXCPM_PROVIDER_NAME

    @property
    def enabled(self) -> bool:
        return bool(self._url)

    def _cached_health(self) -> str | None:
        if self._health and monotonic() - self._health[0] < _HEALTH_CACHE_SECONDS:
            return self._health[1]
        return None

    def _remember_health(self, response: httpx.Response | None, error: str = "") -> str:
        """"" when VoxCPM can synthesize, otherwise why not."""
        if response is None:
            problem = error or "health check failed"
        elif response.status_code >= 500:
            problem = f"health {response.status_code}: {response.text[:200]}"
        else:
            # 舊版 health 沒有 worker 欄位：回 200 就當可用。
            problem = ""
        if problem:
            logger.warning("voxcpm unavailable, skipping: %s", problem)
        self._health = (monotonic(), problem)
        return problem

    def _ensure_healthy(self) -> None:
        problem = self._cached_health()
        if problem is None:
            try:
                response = httpx.get(self._health_url, headers=self._headers, timeout=_HEALTH_TIMEOUT_SECONDS)
            except httpx.RequestError as exc:
                problem = self._remember_health(
                    None, f"health request failed: {describe_error(exc)}",
                )
            else:
                problem = self._remember_health(response)
        if problem:
            # 健康檢查自己有 10 秒快取，不再算進斷路器，免得同一次故障被記兩次。
            raise exempt(VoxCPMHTTPError(status_code=503, detail=problem))

    async def _ensure_healthy_async(self) -> None:
        problem = self._cached_health()
        if problem is None:
            try:
                async with httpx.AsyncClient(timeout=_HEALTH_TIMEOUT_SECONDS) as client:
                    response = await client.get(self._health_url, headers=self._headers)
            except httpx.RequestError as exc:
                problem = self._remember_health(
                    None, f"health request failed: {describe_error(exc)}",
                )
            else:
                problem = self._remember_health(response)
        if problem:
            raise exempt(VoxCPMHTTPError(status_code=503, detail=problem))

    def _build_payload(self, request: SynthesizeRequest) -> dict[str, str]:
        """JSON body for the CastVoice endpoint (``/api/v1/tts/synthesize``).

        voice_id 保留 ``voxcpm2-`` 前綴——CastVoice 與 studio 的 reference
        preset 是兩套命名空間，拿 ``cosy-young-female-01`` 去打會 voice_not_found。
        """
        payload = {
            "text": request.text,
            "voice_id": request.voice_hint or self._default_voice,
        }
        if request.model_id:
            payload["model_id"] = request.model_id
        return payload

    def _build_stream_form(self, request: SynthesizeRequest) -> dict[str, str]:
        """Multipart form for the studio streaming endpoint.

        這裡才需要去掉 ``voxcpm2-`` 前綴，因為 studio 收的是 reference preset id。
        """
        voice_raw = request.voice_hint or self._default_voice
        return {
            "engine_id": VOXCPM_ENGINE_ID,
            "text": request.text,
            "reference_preset_id": _resolve_reference_preset(voice_raw),
            "cfg_value": "2.0",
            # 非部署預設值會退出 CUDA graph 走 eager，比多算幾步還貴。
            "inference_timesteps": self._inference_timesteps,
            "normalize": "true",
            # 對「參考音」降噪，內建 preset 已是乾淨錄音，開了只多一次模型載入。
            "denoise": "false",
            "speed": "1.0",
        }

    def synthesize(self, request: SynthesizeRequest) -> NormalizedTTSResult:
        """POST to /api/v1/tts/synthesize on the VoxCPM360 CastVoice API."""
        if not self._url:
            raise RuntimeError("VoxCPM URL is not configured")
        self._ensure_healthy()

        # Vox 的聲音全是台語，不管這一輪標成什麼語言都先查詞表，跟 CosyVoice 一樣。
        try:
            request = replace(
                request,
                text=self._hanji.convert(request.text, self._hanji_version),
            )
        except (httpx.HTTPError, RuntimeError) as exc:
            raise exempt(VoxCPMHTTPError(503, "Taiwanese word table unavailable")) from exc
        payload = self._build_payload(request)

        t0 = monotonic()
        try:
            response = self._client.post(
                self._url,
                json=payload,
                headers=self._headers,
                # 指定了未載入的 full:: 模型要重載 30～40 秒，這一站多給載入時間。
                timeout=tts_request_timeout(
                    self._config, request, model_load=bool(request.model_id),
                ),
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
            raise VoxCPMHTTPError(
                status_code=503, detail=f"Request failed: {describe_error(exc)}",
            ) from exc

    async def open_stream(
        self, request: SynthesizeRequest, *, sample_rate: int | None = None,
    ) -> AsyncIterator[bytes]:
        """驗證第一個回應沒有錯誤後，回傳串流音訊 chunk 的 async iterator。

        向 VoxCPM360 的 /api/v1/synthesize/stream 送出表單資料，
        即時串流回傳 48kHz mono WAV (帶 44-byte WAV header 之後接 PCM16)。
        """
        if not self._stream_url:
            raise RuntimeError("VoxCPM URL is not configured")
        await self._ensure_healthy_async()

        try:
            request = replace(
                request,
                text=await self._hanji.convert_async(
                    request.text, self._hanji_version,
                ),
            )
        except (httpx.HTTPError, RuntimeError) as exc:
            raise exempt(VoxCPMHTTPError(503, "Taiwanese word table unavailable")) from exc
        form_data = self._build_stream_form(request)
        if sample_rate is not None:
            # 2026-10-14 起 GB10 節點可直接輸出 16 kHz WAV，省掉我們這端 48k→16k 的重採樣。
            form_data["sample_rate"] = str(sample_rate)
        try:
            return await self._send_stream(form_data)
        except VoxCPMHTTPError as exc:
            # 還沒更新的節點不認得 sample_rate 會回 422：拿掉再要一次 48k，由呼叫端轉換。
            # 只在錯誤點名 sample_rate 時才重送；其他 422（文字、聲音不對）重送也一樣錯。
            if (
                sample_rate is None
                or exc.status_code != 422
                or "sample_rate" not in exc.detail
            ):
                raise
            logger.info("voxcpm rejected sample_rate=%s; falling back to 48 kHz", sample_rate)
            form_data.pop("sample_rate", None)
            return await self._send_stream(form_data)

    async def _send_stream(self, form_data: dict[str, str]) -> AsyncIterator[bytes]:
        """Open the stream and wait for the first audio chunk before returning.

        第一段聲音到之前都還能換引擎（呼叫端還沒送 200 header），所以 header 加上
        第一個 chunk 一起受 TTS_STREAM_FIRST_BYTE_SECONDS 限制；之後 chunk 之間的
        停頓由路由層的 guard_stream 管。
        """
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
            self._stream_url,
            data=form_data,
            headers=self._headers,
        )
        started = monotonic()
        try:
            async with asyncio.timeout(first_byte):
                resp = await client.send(req, stream=True)
        except TimeoutError:
            await client.aclose()
            raise VoxCPMHTTPError(
                status_code=503, detail=f"no response in {first_byte:.1f}s",
            ) from HopTimeout("first_byte", first_byte, VOXCPM_PROVIDER_NAME)
        except httpx.RequestError as exc:
            await client.aclose()
            raise VoxCPMHTTPError(
                status_code=503, detail=f"Request failed: {describe_error(exc)}",
            ) from exc

        if resp.status_code >= 400:
            detail = (await resp.aread()).decode("utf-8", errors="replace")[:500]
            await resp.aclose()
            await client.aclose()
            raise VoxCPMHTTPError(status_code=resp.status_code, detail=detail)

        async def _iter_and_close() -> AsyncIterator[bytes]:
            try:
                async for chunk in resp.aiter_bytes():
                    if chunk:
                        yield chunk
            finally:
                await resp.aclose()
                await client.aclose()

        stream = _iter_and_close()
        remaining = max(0.05, first_byte - (monotonic() - started))
        try:
            head = await first_chunk(stream, remaining, VOXCPM_PROVIDER_NAME)
        except BaseException as exc:
            await stream.aclose()
            if isinstance(exc, HopTimeout):
                raise VoxCPMHTTPError(
                    status_code=503, detail=f"no audio in {first_byte:.1f}s",
                ) from exc
            if isinstance(exc, httpx.RequestError):
                raise VoxCPMHTTPError(
                    status_code=503, detail=f"Request failed: {describe_error(exc)}",
                ) from exc
            raise
        if head is None:
            raise VoxCPMHTTPError(status_code=503, detail="stream ended without audio")

        async def _with_head() -> AsyncIterator[bytes]:
            try:
                yield head
                async for chunk in stream:
                    yield chunk
            finally:
                await stream.aclose()

        return _with_head()


def _auth_headers(api_key: str) -> dict[str, str]:
    # 上游 TTS_API_KEY 留空即不驗證；這裡同樣留空就不送 Authorization。
    return {"Authorization": f"Bearer {api_key}"} if api_key else {}


class VoxCPMHTTPError(Exception):
    """Raised when VoxCPM360 returns an HTTP error."""

    def __init__(self, status_code: int, detail: str = "") -> None:
        self.status_code = status_code
        self.detail = detail
        super().__init__(f"VoxCPM HTTP {status_code}: {detail}")
