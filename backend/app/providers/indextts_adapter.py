"""IndexTTS adapter for TTS routing."""

from __future__ import annotations

import logging
from time import monotonic

import httpx

from app.config import TTSRouterConfig
from app.providers.base import NormalizedTTSResult, SynthesizeRequest

logger = logging.getLogger("provider.indextts")

_NOT_LOADED = object()
_INTERNAL_TOKEN_HEADER = "X-Internal-Token"

INDEXTTS_PROVIDER_NAME = "indextts"
# 第二台 IndexTTS（nurse24h）：同一套 API、不同的聲音，選了才用，不進部署備援鏈。
INDEXTTS_NURSE_PROVIDER_NAME = "indextts-nurse"
INDEXTTS_NURSE_DEFAULT_CHARACTER = "hayley"
# 兩台都有 hayley 這類同名聲音，資源表只認 resource_id，nurse 的聲音登錄成
# 「indextts-nurse:<名稱>」，送上游時用 metadata 的 runtime_key（原名稱）。
INDEXTTS_NURSE_VOICE_PREFIX = f"{INDEXTTS_NURSE_PROVIDER_NAME}:"


def indextts_nurse_url(config: object) -> str:
    return (getattr(config, "tts_indextts_nurse_url", "") or "").strip()


def indextts_nurse_default_character(config: object) -> str:
    raw = getattr(config, "tts_indextts_nurse_default_character", "") or ""
    return raw.strip() or INDEXTTS_NURSE_DEFAULT_CHARACTER


def indextts_nurse_voice_id(name: str) -> str:
    """nurse 上游的聲音名稱 → 資源表與選單用的聲音 ID。"""
    return f"{INDEXTTS_NURSE_VOICE_PREFIX}{name}" if name else ""


def indextts_nurse_runtime_voice(voice: str) -> str:
    """選單 ID 或原名稱都收，回上游認得的角色名。"""
    return voice.removeprefix(INDEXTTS_NURSE_VOICE_PREFIX)


class IndexTTSAdapter:
    """Synthesize speech via IndexTTS (HTTP) and return a NormalizedTTSResult.

    預設接 ``TTS_INDEXTTS_URL``；同一套 API 的另一台（nurse24h）用 ``for_nurse``
    建立，provider 名稱、網址、預設角色各自獨立。
    """

    def __init__(
        self,
        config: TTSRouterConfig,
        *,
        provider_name: str = INDEXTTS_PROVIDER_NAME,
        base_url: str | None = None,
        default_character: str | None = None,
        send_internal_token: bool = True,
    ) -> None:
        self._config = config
        self._provider_name = provider_name
        raw_base = config.tts_indextts_url if base_url is None else base_url
        base = raw_base.strip().rstrip("/") if raw_base else ""
        self._url = f"{base}/tts" if base else ""
        self._default_character = (
            config.tts_indextts_default_character
            if default_character is None else default_character
        )
        # 內部 token 只給自家部署的那台；外部節點不需要驗證，也不該拿到它。
        self._internal_headers = (
            {_INTERNAL_TOKEN_HEADER: config.gateway_internal_token}
            if send_internal_token else {}
        )
        self._client = httpx.Client(timeout=60.0)
        self._opencc_t2s = _NOT_LOADED

    @classmethod
    def for_nurse(cls, config: TTSRouterConfig) -> IndexTTSAdapter:
        return cls(
            config,
            provider_name=INDEXTTS_NURSE_PROVIDER_NAME,
            base_url=indextts_nurse_url(config),
            default_character=indextts_nurse_default_character(config),
            send_internal_token=False,
        )

    def _get_opencc(self):
        if self._opencc_t2s is _NOT_LOADED:
            try:
                import opencc
                self._opencc_t2s = opencc.OpenCC("t2s")
            except ImportError:
                logger.warning("opencc-python-reimplemented not installed, skipping t2s conversion")
                self._opencc_t2s = None
        return self._opencc_t2s

    @property
    def provider_name(self) -> str:
        return self._provider_name

    @property
    def enabled(self) -> bool:
        return bool(self._url)

    def synthesize(self, request: SynthesizeRequest) -> NormalizedTTSResult:
        """POST to /tts on the IndexTTS worker."""
        if not self._url:
            raise RuntimeError("IndexTTS URL is not configured")

        text = request.text
        if converter := self._get_opencc():
            text = converter.convert(text)

        character = request.voice_hint or self._default_character
        if self._provider_name == INDEXTTS_NURSE_PROVIDER_NAME:
            character = indextts_nurse_runtime_voice(character)
        payload = {
            "text": text,
            "character": character,
        }

        t0 = monotonic()
        try:
            resp = self._client.post(
                self._url,
                json=payload,
                headers=self._internal_headers,
            )
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
                provider=self._provider_name,
                route_kind="provider",
                route_target=self._provider_name,
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
