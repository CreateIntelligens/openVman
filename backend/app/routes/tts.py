"""Buffered and streaming TTS HTTP endpoints, cache, and provider fallbacks."""

from __future__ import annotations

import asyncio
import hashlib
import logging
from collections.abc import AsyncIterator
from typing import Literal

import httpx
from fastapi import APIRouter, Depends, Response
from fastapi.responses import JSONResponse, StreamingResponse
from pydantic import BaseModel, Field

from app import language_routes as language_routes_mod
from app import voice_policy
from app.auth import voice_access
from app.auth.dependencies import CurrentAccount, get_current_account
from app.auth.models import (
    AccountRole,
    ProjectPolicyRecord,
)
from app.auth.project_gemini_credentials import resolve_gemini_credential
from app.auth.runtime import get_auth_runtime
from app.config import get_tts_config
from app.observability import record_fallback_hop
from app.providers.base import NormalizedTTSResult, SynthesizeRequest
from app.providers.cosyvoice_adapter import COSYVOICE_PROVIDER_NAME
from app.providers.gemini_tts_adapter import (
    GEMINI_PROVIDER_NAME,
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


def _cache_scope(
    project_id: str | None,
    policy: ProjectPolicyRecord | None,
    *,
    is_root: bool = False,
) -> str:
    """Cache namespace for a request.

    同一段文字、同一個聲音在每個專案合成出來都一樣，key 本來就含聲音；但快取存的
    可能是 Edge 備援的結果。有聲音限制的專案備援規則不同（可能禁止 Edge 或指定別
    的 Edge 聲音），所以各自一份，避免拿到別的專案備援出來的聲音。沒限制的專案
    共用原本的 key，命中率不變。ROOT 不受專案清單限制、聲音失敗時也照常退回
    Edge，用同一個聲音合成出來的結果可能是成員不准用的 Edge 備援，所以 ROOT 在
    有限制的專案一律另存一份，不論聲音在不在清單內。
    """
    if project_id and policy is not None and policy.restricts_tts:
        if is_root:
            return f"project:{project_id}:root"
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
    is_root = (
        current.embed_key is None
        and getattr(getattr(current, "user", None), "role", None) is AccountRole.ROOT
    )
    edge_fallback_voice = voice_access.tts_fallback_voice(
        runtime, policy, is_root=is_root
    )
    provider = authorized.provider if authorized else body.provider
    voice = authorized.runtime_key if authorized else body.voice
    svc = _get_service()
    cleaned_text = (await prepare_tts_text_async(body.input)) or ""
    request = SynthesizeRequest(
        text=cleaned_text,
        voice_hint=voice,
        usage_scope=usage_scope_for(
            current, project_id=project_id or "", channel="http",
        ),
    )
    cache_key: str | None = None

    if cfg.tts_cache_enabled:
        cache_scope = _cache_scope(project_id, policy, is_root=is_root)
        if project_id and provider in ("", "auto", "gemini-tts"):
            credential = resolve_gemini_credential(project_id, runtime)
            if credential.source == "project" or provider == "gemini-tts":
                fingerprint = hashlib.sha256(
                    credential.api_key.encode("utf-8"),
                ).hexdigest()[:12]
                cache_scope += (
                    f"|project:{project_id}:gemini:"
                    f"{credential.credential_id}:{fingerprint}"
                )
        cache_key = make_cache_key(
            cleaned_text,
            voice,
            provider,
            scope=cache_scope,
        )
        cached = await cache_get(cache_key)
        if cached is not None:
            return _cached_speech_response(cached)

    try:
        output = svc.synthesize(
            request, provider=provider, edge_fallback_voice=edge_fallback_voice,
            order=_project_engine_order(policy),
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
    text: str = Field(..., description="要念的文字")
    character: str = Field(
        "", description="舊欄位，等同 voice；新串接請用 voice",
    )
    provider: str = Field(
        "",
        description=(
            "TTS 引擎（indextts、voxcpm、cosyvoice、gemini-tts、edge-tts 等，"
            "可用的引擎與聲音見 GET /api/v1/tts/providers）。省略時由 voice 推導或用帳號預設"
        ),
    )
    voice: str = Field(
        "",
        description="聲音 ID，須在帳號授權與專案清單內；省略時用專案預設、再來是帳號預設",
    )
    project_id: str = Field(
        "",
        description=(
            "套用該專案的聲音限制與語言分流。用帳號 API key 時要帶，台語自動分流才會生效"
        ),
    )
    # 逗號分隔字串或陣列都收。
    language_routes: list[str] | str | None = Field(
        None,
        description="語言代碼（zh、nan…），只能縮小專案在知識庫設定開的分流；逗號分隔字串或陣列",
    )
    speech_language: str = Field(
        "",
        description=(
            "這一輪使用者語音被 ASR 判成的語言，照抄 /api/v1/asr/transcribe 回應的 language；"
            "有值時優先於 language"
        ),
    )
    language: str = Field(
        "",
        description=(
            "使用者在介面選的語言（zh、en、nan…），打字輸入時用它決定引擎。語言決定引擎："
            "nan（專案分流需含台語）改用 CosyVoice（會把漢字轉成台文，整段合成；CosyVoice "
            "不可用時改 VoxCPM），zh、en 在沒指定 provider 與 voice 時用 IndexTTS。"
            "明確指定 provider 或 voice 時，只有台語會換引擎"
        ),
    )
    # 空字串＝照引擎原樣回傳（前台虛擬人依賴這個行為）。
    format: Literal["", "pcm16k"] = Field(
        "",
        description=(
            "空字串照引擎原樣回傳（WAV／MP3／PCM，看 Content-Type）；pcm16k 一律轉成 "
            "16 kHz、單聲道、s16le raw PCM 串流，給只吃這種格式的對嘴引擎"
        ),
    )


INDEXTTS_PROVIDER = "indextts"
# 需求 VH-384：國語、英文用 IndexTTS。
_INDEXTTS_LANGUAGES = frozenset({"zh", "en"})
TTS_PROVIDER_HEADER = "X-TTS-Provider"


def _project_engine_order(policy) -> tuple[str, ...]:
    return tuple(getattr(policy, "tts_engine_order", ()) or ())


#: /tts/stream 有獨立分支的引擎；順位排到其他家（GCP、Polly）時當它們不在，
#: 交給最後的整段合成鏈依順位處理。
_STREAM_ADAPTERS = {
    VOXCPM_PROVIDER_NAME: "voxcpm_adapter",
    COSYVOICE_PROVIDER_NAME: "cosyvoice_adapter",
    GEMINI_PROVIDER_NAME: "gemini_adapter",
    voice_access.EDGE_TTS_PROVIDER: "edge_adapter",
}


def _stream_engine_running(name: str, cfg) -> bool:
    if name == INDEXTTS_PROVIDER:
        return bool(cfg.tts_indextts_url)
    attribute = _STREAM_ADAPTERS.get(name)
    if attribute is None:
        return False
    adapter = getattr(_get_service(), attribute, None)
    return bool(adapter is not None and getattr(adapter, "enabled", False))


def _taiwanese_providers(
    requested: str | None, order: tuple[str, ...] = (),
) -> tuple[str, ...]:
    """Running engines for a Taiwanese turn, CosyVoice first; empty to keep the current one.

    CosyVoice 會把漢字轉成台文再唸；VoxCPM 照字唸，Brain 的台語回答是華語文字，
    唸出來多半是華語。原本就指定其中一個時不換。專案有引擎順位時，兩家誰先照順位。
    """
    if requested in language_routes_mod.TAIWANESE_TTS_PROVIDERS:
        return ()
    svc = _get_service()
    candidates = list(language_routes_mod.TAIWANESE_TTS_PROVIDERS)
    chain = order or _taiwanese_chain(None)
    ranked = [name for name in chain if name in candidates]
    candidates = ranked + [name for name in candidates if name not in ranked]
    return tuple(
        name for name in candidates
        if getattr(svc, f"{name}_adapter").enabled
    )


def _switch_voice(runtime, policy, providers: tuple[str, ...], *, is_root: bool):
    """(provider, voice) when language routing moves to ``providers``; voice "" = deployment default.

    專案限制了聲音時只能換到清單裡這些引擎的聲音，清單裡沒有就回 None、不換。
    """
    if policy is None or not policy.restricts_tts:
        return providers[0], ""
    return voice_access.project_voice_for_providers(
        runtime, policy, providers, is_root=is_root,
    )


#: VoxCPM 的 CosyVoice 系列聲音用這個前綴接 CosyVoice 的 voice id，兩邊是同一個人。
_VOXCPM_COSY_PREFIX = "voxcpm2-cosy-"


def _taiwanese_chain(policy) -> tuple[str, ...]:
    """Engine order for a Taiwanese turn: the project's, else the deployment's."""
    order = _project_engine_order(policy)
    if order:
        return order
    cfg = get_tts_config()
    raw = getattr(cfg, "tts_taiwanese_fallback_order", "cosyvoice,voxcpm,indextts")
    return tuple(name.strip() for name in raw.split(",") if name.strip())


def _same_person_voice(provider: str, voice: str, target: str) -> str:
    """The voice on ``target`` that is the same person as ``voice`` on ``provider``.

    CosyVoice 與 VoxCPM 的 cosy 系列是同一套參考聲（voxcpm2-cosy-<id> ↔ <id>）；
    IndexTTS 只有部署預設角色跟它們對得上（hayley ↔ young-female-02）。對不到
    就回空字串，讓那家用自己的預設。
    """
    svc = _get_service()
    cfg = get_tts_config()
    if provider == COSYVOICE_PROVIDER_NAME:
        source = voice or getattr(svc.cosyvoice_adapter, "default_voice", "")
    elif provider == VOXCPM_PROVIDER_NAME:
        raw = voice or getattr(svc.voxcpm_adapter, "default_voice", "")
        source = raw.removeprefix(_VOXCPM_COSY_PREFIX) if raw.startswith(_VOXCPM_COSY_PREFIX) else ""
    else:
        source = ""
    if target == VOXCPM_PROVIDER_NAME:
        return f"{_VOXCPM_COSY_PREFIX}{source}" if source else ""
    if target == COSYVOICE_PROVIDER_NAME:
        return source
    if target == INDEXTTS_PROVIDER:
        return cfg.tts_indextts_default_character
    return ""


def _taiwanese_partners(
    runtime, policy, provider: str, voice: str, *, is_root: bool,
    order: tuple[str, ...] = (),
) -> tuple[tuple[str, str], ...]:
    """Engines to try after ``provider`` fails on a Taiwanese turn, before Edge.

    順序就是專案順位（沒設就是 TTS_TAIWANESE_FALLBACK_ORDER），跳過正在用的
    那家與 Edge（Edge 永遠是最後一道，由 edge_fallback_voice 決定能不能退）。
    每一站的聲音都對成同一個人；專案限制了聲音就只能換到清單裡那家的聲音。
    """
    if provider not in language_routes_mod.TAIWANESE_TTS_PROVIDERS:
        return ()
    svc = _get_service()
    cfg = get_tts_config()
    chain = order or _taiwanese_chain(policy)
    partners: list[tuple[str, str]] = []
    for name in chain:
        if name == provider or name == voice_access.EDGE_TTS_PROVIDER or name in dict(partners):
            continue
        if not _stream_engine_running(name, cfg):
            continue
        mapped = _same_person_voice(provider, voice, name)
        if policy is not None and policy.restricts_tts:
            picked = voice_access.project_voice_for_providers(
                runtime, policy, (name,), is_root=is_root,
            )
            if picked is None:
                continue
            if picked[1] and picked[1] != mapped:
                mapped = picked[1]
        partners.append((name, mapped))
    return tuple(partners)


def _stream_audio(
    stream: AsyncIterator[bytes],
    media_type: str,
    output_format: str,
    provider: str,
) -> StreamingResponse:
    if output_format == PCM16K_FORMAT:
        response = StreamingResponse(
            convert_to_pcm16k(stream, media_type),
            media_type=PCM16K_CONTENT_TYPE,
        )
    else:
        response = StreamingResponse(stream, media_type=media_type)
    # /tts/stream 只看 Content-Type 分不出引擎，驗收與排障都靠這個標頭。
    response.headers[TTS_PROVIDER_HEADER] = provider
    return response


def _buffered_audio(
    result: NormalizedTTSResult, output_format: str, provider: str,
) -> Response:
    provider = result.provider or provider
    if output_format == PCM16K_FORMAT:
        return _stream_audio(
            iter_bytes(result.audio_bytes), result.content_type, output_format, provider,
        )
    return Response(
        content=result.audio_bytes,
        media_type=result.content_type,
        headers={TTS_PROVIDER_HEADER: provider},
    )


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
    is_root = (
        current.embed_key is None
        and getattr(getattr(current, "user", None), "role", None) is AccountRole.ROOT
    )
    edge_fallback_voice = voice_access.tts_fallback_voice(
        runtime, policy, is_root=is_root
    )
    # VH-384：依偵測（ASR）或選擇的語言決定引擎，台語 → CosyVoice／VoxCPM，國語、
    # 英文 → IndexTTS。偵測到的語言優先，打字時才看使用者選的語言。
    language = (body.speech_language or body.language).strip()
    switched = None
    if language == language_routes_mod.TAIWANESE and language_routes_mod.TAIWANESE in routes:
        providers = _taiwanese_providers(body.provider, _project_engine_order(policy))
        if providers:
            switched = _switch_voice(runtime, policy, providers, is_root=is_root)
    if switched:
        # 台語換引擎先於帳號的聲音授權判斷，否則只開了別家聲音的帳號會在換家前就被擋下。
        provider, voice = switched
        character = voice
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
        explicit = body.provider.strip() or body.voice.strip() or body.character.strip()
        # 帳號／專案預設本來就是 IndexTTS 的聲音就照用，不換成部署預設。
        if (
            language in _INDEXTTS_LANGUAGES
            and not explicit
            and cfg.tts_indextts_url
            and provider != INDEXTTS_PROVIDER
        ):
            picked = _switch_voice(runtime, policy, (INDEXTTS_PROVIDER,), is_root=is_root)
            if picked:
                provider = INDEXTTS_PROVIDER
                voice = character = picked[1] or cfg.tts_indextts_default_character
    # 台語這一輪才互備：華語指定 CosyVoice 失敗，換成 VoxCPM 照字唸不是使用者要的。
    partners = (
        _taiwanese_partners(
            runtime, policy, provider, voice, is_root=is_root,
            order=_project_engine_order(policy),
        )
        if language == language_routes_mod.TAIWANESE else ()
    )
    cleaned = (await prepare_tts_text_async(body.text.strip())) or ""
    if not cleaned:
        return JSONResponse(status_code=400, content={"error": "empty text"})
    scope = usage_scope_for(
        current, project_id=project_id or "", channel="http",
    )

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
    if provider == GEMINI_PROVIDER_NAME:
        svc = _get_service()
        gemini = svc.gemini_adapter
        gemini_request = SynthesizeRequest(
            text=cleaned, voice_hint=voice, usage_scope=scope,
        )
        if gemini.enabled_for(gemini_request):
            try:
                stream = await gemini.open_stream(gemini_request)
            except GeminiTTSHTTPError as exc:
                return JSONResponse(status_code=exc.status_code, content={"error": exc.detail})
            except RuntimeError as exc:
                return JSONResponse(status_code=502, content={"error": str(exc)})
            _meter_stream(GEMINI_PROVIDER_NAME)
            return _stream_audio(
                stream, GEMINI_STREAM_CONTENT_TYPE, body.format, GEMINI_PROVIDER_NAME,
            )

    # 專案設了引擎順位：沒指定引擎時由順位第一個（有在跑的）決定走哪條串流分支。
    engine_order = _project_engine_order(policy)
    if not provider and engine_order:
        for name in engine_order:
            if _stream_engine_running(name, cfg):
                provider = name
                break

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
                return _stream_audio(
                    stream, VOXCPM_STREAM_CONTENT_TYPE, body.format, VOXCPM_PROVIDER_NAME,
                )
            except (VoxCPMHTTPError, RuntimeError) as exc:
                # GPU 節點掛掉不該讓整個 TTS 失敗：記一筆後往下走 IndexTTS → Edge 的 fallback。
                logger.warning("tts_stream voxcpm error: %s", exc)
                if partners:
                    partner, partner_voice = partners[0]
                    record_fallback_hop(
                        from_target=VOXCPM_PROVIDER_NAME, to_target=partner,
                        reason="provider_unavailable",
                    )
                    try:
                        output = _get_service().synthesize(
                            SynthesizeRequest(
                                text=cleaned, voice_hint=partner_voice, usage_scope=scope,
                            ),
                            provider=partner,
                            edge_fallback_voice=edge_fallback_voice,
                            partners=partners[1:],
                        )
                    except RuntimeError as partner_exc:
                        return JSONResponse(status_code=502, content={"error": str(partner_exc)})
                    return _buffered_audio(output.result, body.format, partner)

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
                partners=partners,
            )
        except RuntimeError as exc:
            return JSONResponse(status_code=502, content={"error": str(exc)})
        return _buffered_audio(output.result, body.format, provider)

    # Primary: proxy stream directly from IndexTTS — 只在沒指定或指定 IndexTTS 時。明確指定
    # Edge（或 VoxCPM 掛掉往下退）卻先送 IndexTTS，IndexTTS 沒在跑時會回 200 空音檔。
    if cfg.tts_indextts_url and provider in ("", INDEXTTS_PROVIDER):
        indextts_stream_url = cfg.tts_indextts_url.rstrip("/") + "/tts_stream"
        proxied = await _proxy_indextts_stream(
            indextts_stream_url=indextts_stream_url,
            text=cleaned,
            character=character,
        )
        if proxied is not None:
            _meter_stream(INDEXTTS_PROVIDER)
            return _stream_audio(
                proxied.body_iterator,
                proxied.media_type or "audio/wav",
                body.format,
                INDEXTTS_PROVIDER,
            )

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
        _meter_stream(voice_access.EDGE_TTS_PROVIDER)
        return _stream_audio(stream, "audio/mpeg", body.format, voice_access.EDGE_TTS_PROVIDER)

    # Fallback (buffered): 其餘 provider 仍走 service chain 一次性回傳。
    try:
        output = svc.synthesize(
            SynthesizeRequest(
                text=cleaned, voice_hint=voice or character, usage_scope=scope,
            ),
            provider=provider,
            edge_fallback_voice=edge_fallback_voice,
            order=engine_order,
        )
    except RuntimeError as exc:
        return JSONResponse(status_code=502, content={"error": str(exc)})

    return _buffered_audio(output.result, body.format, provider)
