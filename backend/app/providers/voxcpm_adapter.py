"""VoxCPM360 adapter for TTS routing.

Talks to the VoxCPM360 studio API: ``POST /api/v1/synthesize`` for one-shot
synthesis and ``POST /api/v1/synthesize/stream`` for incremental playback.
Both take multipart form fields, not JSON — see ``/api/v1/catalog`` for the
engines and reference presets a given deployment exposes.
"""

from __future__ import annotations

import logging
from collections.abc import AsyncIterator
from time import monotonic

import httpx

from app.config import TTSRouterConfig
from app.providers.base import NormalizedTTSResult, SynthesizeRequest

logger = logging.getLogger("provider.voxcpm")

VOXCPM_PROVIDER_NAME = "voxcpm"
# /api/v1/catalog 公布的引擎 id；這個部署只有 voxcpm2。
VOXCPM_ENGINE_ID = "voxcpm2"
# 無 TTS_VOXCPM_DEFAULT_VOICE 時的保底語音。VoxCPM2 依文字內容推斷語言，
# 參考音只決定音色，所以台語參考音唸華語文字仍是華語。
VOXCPM_DEFAULT_VOICE = "voxcpm2-cosy-young-female-01"
# VoxCPM2 輸出 48kHz WAV，gateway 再以 ffmpeg 轉 mp3（取樣率不變）。
# mp3 由瀏覽器自行解碼，此值只作為 cache metadata。
VOXCPM_SAMPLE_RATE = 48000
VOXCPM_CONTENT_TYPE = "audio/mpeg"
VOXCPM_STREAM_CONTENT_TYPE = "audio/wav; rate=48000"
# 一次合成整段（非串流），GPU 排隊時可能超過一分鐘；上游 nginx 為 900s。
_REQUEST_TIMEOUT_SECONDS = 120.0


def _resolve_reference_preset(voice: str) -> str:
    """從 voice_id 解析出 reference_preset_id（去除 voxcpm2- 前綴）。"""
    return voice.removeprefix("voxcpm2-")


def equivalent_preset(voice: str) -> str:
    """CosyVoice 聲線在 VoxCPM 的等價 preset，沒有就回空字串。

    兩邊的臺語聲線出自同一組參考音，VoxCPM 只是多了 ``cosy-`` 前綴。這個
    對應讓 CosyVoice 的請求能改走 VoxCPM 的串流端點：同一句話整段合成要等
    14.7 秒才出聲，串流 0.47 秒就開始播。沒有對應的（例如 CosyVoice 獨有的
    young-female-02）回空字串，呼叫端照原本的整段路徑走。
    """
    if not voice or voice.startswith("voxcpm2-"):
        return ""
    candidate = f"cosy-{voice}"
    return candidate if candidate in _VOXCPM_PRESETS else ""


# /api/v1/catalog 公布的 reference presets。寫死而不是開機時抓：抓失敗的話
# 整個 TTS 就沒有串流可走，而這份清單變動的頻率遠低於服務重啟的頻率。
_VOXCPM_PRESETS = frozenset({
    "cosy-child-female-01",
    "cosy-child-male-01",
    "cosy-child-male-02",
    "cosy-senior-female-01",
    "cosy-senior-male-01",
    "cosy-teen-female-01",
    "cosy-teen-female-02",
    "cosy-teen-female-03",
    "cosy-teen-male-01",
    "cosy-teen-male-02",
    "cosy-young-female-01",
    "cosy-young-male-01",
    "cosy-young-male-02",
    "cosy-young-male-03",
})


class VoxCPMAdapter:
    """Synthesize speech via VoxCPM360 (HTTP) and return a NormalizedTTSResult or stream."""

    def __init__(self, config: TTSRouterConfig) -> None:
        base_url = config.tts_voxcpm_url.rstrip("/") if config.tts_voxcpm_url else ""
        self._url = f"{base_url}/api/v1/synthesize" if base_url else ""
        # 從 _url 衍生而不是各寫一次：這兩個 URL 分開寫正是上一個 bug 的形狀
        # ——批次那份路徑寫錯了，而串流那份是對的，於是沒人發現。
        self._stream_url = f"{self._url}/stream" if self._url else ""
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
        """Build the multipart form both synthesis endpoints expect.

        兩條路徑送同一組欄位，差別只在串流與否；分開寫過一次，結果非串流
        那份帶著錯的路徑與 JSON body 沉了幾個月都沒人發現。
        """
        voice_raw = request.voice_hint or self._default_voice
        return {
            "engine_id": VOXCPM_ENGINE_ID,
            "text": request.text,
            "reference_preset_id": _resolve_reference_preset(voice_raw),
            "cfg_value": "2.0",
            "inference_timesteps": "30",
            "normalize": "true",
            "denoise": "false",
            "speed": "1.0",
        }

    def synthesize(self, request: SynthesizeRequest) -> NormalizedTTSResult:
        """POST to /api/v1/synthesize on the VoxCPM360 studio API."""
        if not self._url:
            raise RuntimeError("VoxCPM URL is not configured")

        payload = self._build_payload(request)

        t0 = monotonic()
        try:
            response = self._client.post(
                self._url,
                data=payload,
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
                    "reference_preset_id": payload["reference_preset_id"],
                    "status_code": response.status_code,
                    "request_id": response.headers.get("X-Request-ID", ""),
                },
            )
        except httpx.RequestError as exc:
            raise VoxCPMHTTPError(status_code=503, detail=f"Request failed: {exc}")

    async def open_stream(
        self, request: SynthesizeRequest,
    ) -> AsyncIterator[bytes]:
        """驗證第一個回應沒有錯誤後，回傳串流音訊 chunk 的 async iterator。

        向 VoxCPM360 的 /api/v1/synthesize/stream 送出表單資料，
        即時串流回傳 48kHz mono WAV (帶 44-byte WAV header 之後接 PCM16)。
        """
        if not self._stream_url:
            raise RuntimeError("VoxCPM URL is not configured")

        form_data = self._build_payload(request)

        client = httpx.AsyncClient(timeout=_REQUEST_TIMEOUT_SECONDS)
        req = client.build_request(
            "POST",
            self._stream_url,
            data=form_data,
            headers=self._headers,
        )
        try:
            resp = await client.send(req, stream=True)
        except httpx.RequestError as exc:
            await client.aclose()
            raise VoxCPMHTTPError(status_code=503, detail=f"Request failed: {exc}")

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

        return _iter_and_close()


def _auth_headers(api_key: str) -> dict[str, str]:
    # 上游 TTS_API_KEY 留空即不驗證；這裡同樣留空就不送 Authorization。
    return {"Authorization": f"Bearer {api_key}"} if api_key else {}


class VoxCPMHTTPError(Exception):
    """Raised when VoxCPM360 returns an HTTP error."""

    def __init__(self, status_code: int, detail: str = "") -> None:
        self.status_code = status_code
        self.detail = detail
        super().__init__(f"VoxCPM HTTP {status_code}: {detail}")
