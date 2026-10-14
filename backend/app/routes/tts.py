"""Buffered and streaming TTS HTTP endpoints, cache, and provider fallbacks."""

from __future__ import annotations

import asyncio
import logging
from collections.abc import AsyncIterator
from typing import Literal

import httpx
from fastapi import APIRouter, Depends, Response
from fastapi.responses import JSONResponse, StreamingResponse
from pydantic import BaseModel

from app import language_routes as language_routes_mod
from app import voice_policy
from app.auth import voice_access
from app.auth.dependencies import CurrentAccount, get_current_account
from app.auth.models import ProjectPolicyRecord
from app.auth.runtime import get_auth_runtime
from app.config import get_tts_config
from app.providers.base import NormalizedTTSResult, SynthesizeRequest
from app.providers.cosyvoice_adapter import COSYVOICE_PROVIDER_NAME
from app.providers.gemini_tts_adapter import (
    GEMINI_STREAM_CONTENT_TYPE,
    GeminiTTSHTTPError,
)
from app.providers.voxcpm_adapter import (
    VOXCPM_PROVIDER_NAME,
    VOXCPM_STREAM_CONTENT_TYPE,
    VoxCPMHTTPError,
)
from app.service import TTSRouterService
from app.tts_cache import CachedTTSEntry, cache_get, cache_put, make_cache_key
from app.tts_pcm import (
    PCM16K_CONTENT_TYPE,
    PCM16K_FORMAT,
    convert_to_pcm16k,
    iter_bytes,
)
from app.tts_text import prepare_tts_text_async
from app.usage_ledger_client import (
    UNIT_CHARS,
    record_usage_event,
    usage_scope_for,
)

logger = logging.getLogger("backend")
router = APIRouter()
_service: TTSRouterService | None = None


def _get_service() -> TTSRouterService:
    global _service
    _service = _service or TTSRouterService(get_tts_config())
    return _service


def _cached_speech_response(entry: CachedTTSEntry) -> Response:
    return Response(
        content=entry.audio_bytes,
        media_type=entry.content_type,
        headers={
            "X-TTS-Latency-Ms": "0",
            "X-TTS-Provider": entry.provider,
            "X-TTS-Cache-Hit": "true",
        },
    )


def _to_cached_tts_entry(result: NormalizedTTSResult) -> CachedTTSEntry:
    return CachedTTSEntry(
        audio_bytes=result.audio_bytes,
        content_type=result.content_type,
        provider=result.provider,
        route_kind=result.route_kind,
        route_target=result.route_target,
        sample_rate=result.sample_rate,
    )


class SpeechRequest(BaseModel):
    input: str
    voice: str = ""
    provider: str = ""
    response_format: str = "wav"
    speed: float = 1.0
    # 選填：套用這個專案的聲音限制（Embed key 一律用金鑰綁定的專案）。
    project_id: str = ""


def _cache_scope(project_id: str | None, policy: ProjectPolicyRecord | None) -> str:
    """Cache namespace for a request.

    同一段文字、同一個聲音在每個專案合成出來都一樣，key 本來就含聲音；但快取存的
    可能是 Edge 備援的結果。有聲音限制的專案備援規則不同（可能禁止 Edge 或指定別
    的 Edge 聲音），所以各自一份，避免拿到別的專案備援出來的聲音。沒限制的專案
    共用原本的 key，命中率不變。
    """
    if project_id and policy is not None and policy.restricts_tts:
        return f"project:{project_id}"
    return ""


@router.post("/v1/audio/speech", tags=["TTS"], summary="文字轉語音")
async def create_speech(
    body: SpeechRequest,
    current: CurrentAccount = Depends(get_current_account),
) -> Response:
    cfg = get_tts_config()
    runtime = get_auth_runtime()
    project_id, policy = voice_policy.request_policy(runtime, current, body.project_id)
    authorized = voice_access.resolve_tts_voice(
        current,
        runtime,
        requested_provider=body.provider,
        requested_voice=body.voice,
        project_id=project_id,
    )
    edge_fallback_voice = voice_access.tts_fallback_voice(runtime, policy)
    provider = authorized.provider if authorized else body.provider
    voice = authorized.runtime_key if authorized else body.voice
    svc = _get_service()
    cleaned_text = (await prepare_tts_text_async(body.input)) or ""
    request = SynthesizeRequest(
        text=cleaned_text,
        voice_hint=voice,
        usage_scope=usage_scope_for(current, channel="http"),
    )
    cache_key: str | None = None

    if cfg.tts_cache_enabled:
        cache_key = make_cache_key(
            cleaned_text, voice, provider, scope=_cache_scope(project_id, policy),
        )
        cached = await cache_get(cache_key)
        if cached is not None:
            return _cached_speech_response(cached)

    try:
        output = svc.synthesize(
            request, provider=provider, edge_fallback_voice=edge_fallback_voice,
        )
    except RuntimeError as exc:
        return JSONResponse(status_code=502, content={"error": str(exc)})

    headers = {
        "X-TTS-Latency-Ms": str(round(output.result.latency_ms, 2)),
        "X-TTS-Provider": output.result.provider,
        "X-TTS-Cache-Hit": "false",
    }
    if output.fallback:
        headers["X-TTS-Fallback"] = "true"
        headers["X-TTS-Fallback-Reason"] = output.fallback_reason

    if cache_key is not None:
        asyncio.create_task(cache_put(cache_key, _to_cached_tts_entry(output.result), cfg.tts_cache_ttl_seconds))

    return Response(content=output.result.audio_bytes, media_type=output.result.content_type, headers=headers)


class TtsStreamRequest(BaseModel):
    text: str
    character: str = ""
    provider: str = ""
    voice: str = ""
    # 語言分流：有台語分流時 TTS 原本不是 VoxCPM／CosyVoice 就改用 VoxCPM。
    project_id: str = ""
    # 逗號分隔字串或陣列都收。
    language_routes: list[str] | str | None = None
    # 這一輪使用者語音被 ASR 判成的語言；只有 "nan"（真的講台語）才換 VoxCPM。
    # 打字、快速問答、講華語都沒有這個值，照使用者選的 TTS。
    speech_language: str = ""
    # 空字串＝照引擎原樣回傳（前台虛擬人依賴這個行為）；"pcm16k"＝不論引擎都轉成
    # 16 kHz mono s16le raw PCM 串流，給 MatesX 等只吃這種格式的對嘴引擎。
    format: Literal["", "pcm16k"] = ""


def _stream_audio(
    stream: AsyncIterator[bytes],
    media_type: str,
    output_format: str,
) -> StreamingResponse:
    if output_format == PCM16K_FORMAT:
        return StreamingResponse(
            convert_to_pcm16k(stream, media_type),
            media_type=PCM16K_CONTENT_TYPE,
        )
    return StreamingResponse(stream, media_type=media_type)


def _buffered_audio(result: NormalizedTTSResult, output_format: str) -> Response:
    if output_format == PCM16K_FORMAT:
        return _stream_audio(
            iter_bytes(result.audio_bytes), result.content_type, output_format,
        )
    return Response(content=result.audio_bytes, media_type=result.content_type)


async def _proxy_indextts_stream(
    *,
    indextts_stream_url: str,
    text: str,
    character: str,
) -> StreamingResponse | None:
    cfg = get_tts_config()
    client = httpx.AsyncClient(timeout=httpx.Timeout(60.0, connect=10.0))
    try:
        request = client.build_request(
            "POST",
            indextts_stream_url,
            json={"text": text, "character": character},
            headers={"X-Internal-Token": cfg.gateway_internal_token},
        )
        resp = await client.send(request, stream=True)
    except Exception as exc:
        await client.aclose()
        logger.error("tts_stream proxy error: %s", exc)
        return None

    if resp.status_code >= 400:
        detail = ""
        try:
            detail = (await resp.aread()).decode("utf-8", errors="replace")[:500]
        finally:
            await resp.aclose()
            await client.aclose()
        logger.warning(
            "tts_stream indextts error status=%s detail=%s",
            resp.status_code,
            detail,
        )
        return None

    async def _proxy_stream() -> AsyncIterator[bytes]:
        try:
            async for chunk in resp.aiter_bytes(chunk_size=4096):
                if chunk:
                    yield chunk
        except Exception as exc:
            logger.error("tts_stream proxy read error: %s", exc)
        finally:
            await resp.aclose()
            await client.aclose()

    return StreamingResponse(
        _proxy_stream(),
        media_type=resp.headers.get("content-type", "audio/wav") or "audio/wav",
    )


@router.post("/api/v1/tts/stream", tags=["TTS"], summary="串流 TTS 合成")
async def tts_stream_endpoint(
    body: TtsStreamRequest,
    current: CurrentAccount = Depends(get_current_account),
) -> Response:
    cfg = get_tts_config()
    runtime = get_auth_runtime()
    routes = await language_routes_mod.effective_routes(
        current, body.project_id, language_routes_mod.parse_requested(body.language_routes),
    )
    project_id, policy = voice_policy.request_policy(runtime, current, body.project_id)
    edge_fallback_voice = voice_access.tts_fallback_voice(runtime, policy)
    override = (
        language_routes_mod.taiwanese_tts_provider(body.provider)
        if language_routes_mod.TAIWANESE in routes
        and body.speech_language == language_routes_mod.TAIWANESE
        else None
    )
    override_voice = ""
    if override and policy is not None and policy.restricts_tts:
        # 專案限制了聲音：台語只能換到清單裡 VoxCPM／CosyVoice 的聲音；清單裡沒有
        # 就不換，照一般流程用專案允許的聲音唸。
        picked = voice_access.project_voice_for_providers(
            runtime, policy, language_routes_mod.TAIWANESE_TTS_PROVIDERS,
        )
        override, override_voice = picked if picked else (None, "")
    if override:
        # 台語分流：原本不是 VoxCPM／CosyVoice 就改用 VoxCPM 的部署預設聲音。先於帳號的
        # 聲音授權判斷，否則只開了別家聲音的帳號會在換家前就被擋下。
        provider, voice, character = override, override_voice, override_voice
    else:
        authorized = voice_access.resolve_tts_voice(
            current,
            runtime,
            requested_provider=body.provider,
            requested_voice=body.voice or body.character,
            project_id=project_id,
        )
        provider = authorized.provider if authorized else body.provider
        character = authorized.runtime_key if authorized else (body.character or cfg.tts_indextts_default_character)
        voice = authorized.runtime_key if authorized else body.voice
    cleaned = (await prepare_tts_text_async(body.text.strip())) or ""
    if not cleaned:
        return JSONResponse(status_code=400, content={"error": "empty text"})
    scope = usage_scope_for(current, channel="http")

    def _meter_stream(stream_provider: str) -> None:
        """串流路徑不經過 service 的 fallback chain，所以在這裡自行記帳。

        串流一旦開啟就代表上游已接受並開始計費，因此以送出的字元數計量，
        不等串流讀完（客戶端中途斷線仍然算數）。
        """
        record_usage_event(
            provider=stream_provider,
            model=voice,
            kind="tts",
            unit_type=UNIT_CHARS,
            units=len(cleaned),
            scope=scope,
            raw={"streaming": True},
        )

    # Gemini TTS Console 支援 stream=true，邊生成邊吐 raw PCM（24000Hz），
    # 避免等整段合成完的高延遲。content-type 帶 rate 讓前端知道要重採樣。
    if provider == "gemini-tts":
        svc = _get_service()
        gemini = svc.gemini_adapter
        if gemini.enabled:
            try:
                stream = await gemini.open_stream(
                    SynthesizeRequest(text=cleaned, voice_hint=voice, usage_scope=scope)
                )
            except GeminiTTSHTTPError as exc:
                return JSONResponse(status_code=exc.status_code, content={"error": exc.detail})
            except RuntimeError as exc:
                return JSONResponse(status_code=502, content={"error": str(exc)})
            _meter_stream("gemini-tts")
            return _stream_audio(stream, GEMINI_STREAM_CONTENT_TYPE, body.format)

    # provider 未指定（auto）且沒有 IndexTTS 時，VoxCPM 是 fallback 鏈的第一站，
    # 直接走它的串流端點，否則 auto 會掉到整段合成的路徑，前端要等好幾秒。
    if not provider and not cfg.tts_indextts_url and _get_service().voxcpm_adapter.enabled:
        provider = VOXCPM_PROVIDER_NAME

    # VoxCPM 支援 /api/v1/synthesize/stream 串流，邊生成邊吐 48kHz mono WAV。
    if provider == VOXCPM_PROVIDER_NAME:
        voxcpm = _get_service().voxcpm_adapter
        if voxcpm.enabled:
            try:
                stream = await voxcpm.open_stream(
                    SynthesizeRequest(text=cleaned, voice_hint=voice, usage_scope=scope),
                    # 要 16 kHz 就請 VoxCPM 直接出，轉換器只需剝檔頭。
                    sample_rate=16000 if body.format == "pcm16k" else None,
                )
                _meter_stream(VOXCPM_PROVIDER_NAME)
                return _stream_audio(stream, VOXCPM_STREAM_CONTENT_TYPE, body.format)
            except (VoxCPMHTTPError, RuntimeError) as exc:
                # GPU 節點掛掉不該讓整個 TTS 失敗：記一筆後往下走 IndexTTS → Edge 的 fallback。
                logger.warning("tts_stream voxcpm error: %s", exc)

    # 明確指定的非串流 provider（CosyVoice 等）直接走整段合成。不這樣做的話
    # 會掉進下面的 IndexTTS／Edge 串流，回的是別的引擎的聲音——CosyVoice 是
    # 台語，被換成 Edge 的華語音色不會報錯，只會默默唸錯語言。
    if provider == COSYVOICE_PROVIDER_NAME:
        svc = _get_service()
        try:
            output = svc.synthesize(
                SynthesizeRequest(
                    text=cleaned, voice_hint=voice or character, usage_scope=scope,
                ),
                provider=provider,
                edge_fallback_voice=edge_fallback_voice,
            )
        except RuntimeError as exc:
            return JSONResponse(status_code=502, content={"error": str(exc)})
        return _buffered_audio(output.result, body.format)

    # Primary: proxy stream directly from IndexTTS — 只在沒指定或指定 IndexTTS 時。明確指定
    # Edge（或 VoxCPM 掛掉往下退）卻先送 IndexTTS，IndexTTS 沒在跑時會回 200 空音檔。
    if cfg.tts_indextts_url and provider in ("", "indextts"):
        indextts_stream_url = cfg.tts_indextts_url.rstrip("/") + "/tts_stream"
        proxied = await _proxy_indextts_stream(
            indextts_stream_url=indextts_stream_url,
            text=cleaned,
            character=character,
        )
        if proxied is not None:
            _meter_stream("indextts")
            if body.format:
                return _stream_audio(
                    proxied.body_iterator, proxied.media_type or "audio/wav", body.format,
                )
            return proxied

    svc = _get_service()

    # Fallback streaming: Edge-TTS 邊合成邊吐，避免等整句。
    # voice 已經過 resolve_tts_voice 授權；Edge adapter 會把非 Edge 格式的
    # 名稱（例如 IndexTTS 角色名）退回自身預設 voice，這裡不需再清掉。
    # 專案限制了聲音又沒開 Edge 時不能在這裡默默換成 Edge（edge_fallback_voice 是 None）。
    edge = svc.edge_adapter
    is_edge = provider == voice_access.EDGE_TTS_PROVIDER
    if edge.enabled and (is_edge or edge_fallback_voice is not None):
        edge_voice = voice if is_edge or not edge_fallback_voice else edge_fallback_voice
        stream = edge.synthesize_stream(
            SynthesizeRequest(text=cleaned, voice_hint=edge_voice, usage_scope=scope)
        )
        _meter_stream("edge-tts")
        return _stream_audio(stream, "audio/mpeg", body.format)

    # Fallback (buffered): 其餘 provider 仍走 service chain 一次性回傳。
    try:
        output = svc.synthesize(
            SynthesizeRequest(
                text=cleaned, voice_hint=voice or character, usage_scope=scope,
            ),
            provider=provider,
            edge_fallback_voice=edge_fallback_voice,
        )
    except RuntimeError as exc:
        return JSONResponse(status_code=502, content={"error": str(exc)})

    return _buffered_audio(output.result, body.format)
