"""Account ASR uploads, admin previews, and project language route discovery."""

from __future__ import annotations

import asyncio
import logging
import math
import os
import subprocess
import wave
from time import monotonic
from typing import Annotated, Any

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from fastapi.responses import JSONResponse
from pydantic import BaseModel

from app import asr_glossary as asr_glossary_mod
from app import language_routes as language_routes_mod
from app.auth.asr_selection import asr_user_choices
from app.auth.dependencies import (
    CurrentAccount,
    get_current_account,
    require_admin,
)
from app.auth.runtime import AuthRuntime, get_auth_runtime
from app.auth.settings_repository import SERVER_ASR_PROVIDERS
from app.config import get_tts_config
from app.error_payloads import upload_failed_response
from app.usage_ledger_client import (
    UNIT_SECONDS,
    record_usage_event,
    usage_scope_for,
)
from app.utils.upload import (
    UploadTooLargeError,
    cleanup_temp_path,
    persist_upload_to_tempfile,
)

logger = logging.getLogger("backend")
router = APIRouter()


class AsrTranscription(BaseModel):
    text: str
    provider: str
    elapsed_seconds: float
    language: str | None
    language_check: dict[str, Any] | None
    language_routes: list[str]
    glossary: str


def _audio_seconds(file_path: str) -> float | None:
    """Measure media duration; compressed bytes are not a duration estimate."""
    try:
        with wave.open(file_path, "rb") as audio:
            return audio.getnframes() / audio.getframerate()
    except (wave.Error, EOFError, OSError):
        pass
    try:
        probe = subprocess.run(
            [
                "ffprobe", "-v", "error", "-show_entries",
                "format=duration", "-of", "default=noprint_wrappers=1:nokey=1",
                file_path,
            ],
            capture_output=True,
            text=True,
            check=True,
            timeout=5,
        )
        seconds = float(probe.stdout.strip())
        return seconds if math.isfinite(seconds) and seconds > 0 else None
    except (OSError, subprocess.SubprocessError, ValueError):
        return None


async def _record_transcription_usage(
    account: CurrentAccount,
    file_path: str,
    *,
    project_id: str,
    provider: str,
    elapsed_seconds: float,
) -> None:
    if not provider:
        return
    try:
        seconds = await asyncio.to_thread(_audio_seconds, file_path)
        if seconds is None or seconds <= 0:
            logger.warning("ASR duration unavailable; usage event skipped")
            return
        record_usage_event(
            provider=provider,
            kind="asr",
            unit_type=UNIT_SECONDS,
            units=seconds,
            latency_ms=elapsed_seconds * 1000,
            scope=usage_scope_for(
                account,
                project_id=language_routes_mod.resolve_project(
                    account, project_id,
                ) or "",
                channel="http",
            ),
            raw={"streaming": False},
        )
    except Exception as exc:
        # 記帳故障不能把已完成的辨識變成上傳失敗。
        logger.warning("ASR usage recording failed: %s", type(exc).__name__)


async def _transcribe_routed(
    account: CurrentAccount,
    tmp_path: str,
    *,
    project_id: str,
    language_routes: str | None,
    preferred: str | None,
    trace_id: str,
    taiwanese_uses_breeze: bool,
    allowed_providers: set[str] | None = None,
    strict_provider: bool = False,
) -> dict:
    """Transcribe with the project's glossary and language routes, as a real chat turn does."""
    from app.gateway.ingestion_audio import transcribe

    routes = await language_routes_mod.effective_routes(
        account, project_id, language_routes_mod.parse_requested(language_routes),
    )
    prompt = await asr_glossary_mod.project_asr_prompt(account, project_id)
    scope = (
        {"allowed_providers": allowed_providers}
        if allowed_providers is not None else {}
    )
    # 只量轉寫本身，不含上傳與轉檔：比的是引擎誰快，網路時間算進去會讓同一個引擎在
    # 不同網路下看起來像兩回事。
    started = monotonic()
    speech_language: str | None = None
    language_check: dict | None = None
    if language_routes_mod.TAIWANESE in routes:
        # 台語分流：Breeze 把台語直接翻成華語（華語也準），同時請 Brain 聽是不是台語，
        # 轉錄出來的華語文字看不出原本講的是台語。後台試辨識照操作者選的引擎跑，
        # 才比得出各家聽台語的差別。
        if taiwanese_uses_breeze:
            preferred = language_routes_mod.TAIWANESE_ASR_ENGINE
        result, heard = await asyncio.gather(
            transcribe(
                tmp_path, trace_id, preferred, prompt=prompt, routes=routes,
                **scope,
            ),
            language_routes_mod.detect_taiwanese(tmp_path),
        )
        speech_language = heard.language if heard.language == language_routes_mod.TAIWANESE else None
        language_check = {"result": heard.result, "ms": heard.ms}
    else:
        result = await transcribe(
            tmp_path, trace_id, preferred, prompt=prompt, routes=routes, **scope,
        )
    if strict_provider and result.provider != preferred:
        raise HTTPException(status_code=502, detail="Requested ASR provider failed")
    elapsed_seconds = round(monotonic() - started, 2)
    await _record_transcription_usage(
        account, tmp_path,
        project_id=project_id,
        provider=result.provider or "",
        elapsed_seconds=elapsed_seconds,
    )
    return {
        "text": result.content,
        # 實際辨識的引擎：指定的掛掉由備援接手時不是同一個；全掛時是空字串。
        "provider": result.provider or "",
        "elapsed_seconds": elapsed_seconds,
        "language": speech_language,
        # 台語分流時才有：判斷結果（語言代碼、timeout、failed）與耗時。
        "language_check": language_check,
        "language_routes": routes,
        # 這次實際送給引擎的詞表（空字串：專案沒設、拿不到，或沒帶專案）。
        "glossary": prompt,
    }


@router.post(
    "/api/v1/asr/transcribe",
    tags=["ASR"],
    response_model=AsrTranscription,
    responses={
        403: {"description": "指定引擎未授權"},
        422: {"description": "無效的批次引擎或請求欄位"},
        502: {"description": "明確指定的辨識引擎失敗，不執行備援"},
        503: {"description": "指定引擎尚未完成部署設定"},
    },
    summary="以已授權的引擎轉寫語音，可於單次請求指定 provider",
)
async def transcribe_for_account(
    account: CurrentAccount = Depends(get_current_account),
    file: UploadFile = File(...),
    project_id: str = Form(""),
    language_routes: str | None = Form(None),
    provider: Annotated[str, Form()] = "",
    runtime: AuthRuntime = Depends(get_auth_runtime),
) -> JSONResponse:
    """Transcribe a clip for an ordinary signed-in user.

    明確指定時先驗證批次模式、授權與部署設定，只執行該引擎，不修改帳號偏好。
    省略時保留帳號偏好與部署預設；備援限於授權引擎及既有部署預設。
    """
    from app.gateway.worker import _account_asr_provider

    suffix = os.path.splitext(file.filename or "")[1] or ".wav"
    tmp_path: str | None = None
    cfg = get_tts_config()
    try:
        requested = provider.strip()
        allowed = (
            set(asr_user_choices(runtime, account.user))
            if account.embed_key is None else set()
        )
        if requested:
            from app.gateway.ingestion_audio import configured_providers

            if requested not in SERVER_ASR_PROVIDERS:
                raise HTTPException(status_code=422, detail="Invalid batch ASR provider")
            if account.embed_key is not None or requested not in allowed:
                raise HTTPException(status_code=403, detail="ASR provider not allowed")
            if requested not in configured_providers():
                raise HTTPException(status_code=503, detail="ASR provider not configured")
        preferred = requested or _account_asr_provider(
            {"owner_user_id": account.user.id},
        )
        # The deployment default remains an implicit choice for existing clients
        # without explicit grants. A fallback must not expose other engines.
        providers = (
            {requested} if requested else allowed | {cfg.asr_provider}
        )
        tmp_path, _ = await persist_upload_to_tempfile(
            file,
            suffix=suffix,
            max_bytes=cfg.document_max_upload_bytes,
        )
        return JSONResponse(content=await _transcribe_routed(
            account, tmp_path,
            project_id=project_id,
            language_routes=language_routes,
            preferred=preferred,
            trace_id="asr-chat",
            taiwanese_uses_breeze=not bool(requested),
            allowed_providers=providers,
            strict_provider=bool(requested),
        ))
    except HTTPException:
        raise
    except UploadTooLargeError as exc:
        limit_mb = exc.limit_bytes / (1024 * 1024)
        return upload_failed_response(
            status_code=413,
            error=f"音檔超過大小限制（上限 {limit_mb:.0f} MB）",
        )
    except Exception as exc:
        logger.error("asr transcribe failed: %s", exc)
        return upload_failed_response(status_code=500, error=str(exc))
    finally:
        await file.close()
        cleanup_temp_path(tmp_path)


@router.get(
    "/api/v1/language-routes",
    tags=["Settings"],
    summary="這個專案後台開了哪些語言分流",
)
async def get_language_routes(
    project_id: str = "",
    current: CurrentAccount = Depends(get_current_account),
) -> JSONResponse:
    """前台據此列出可臨時開關的分流；至少要留一條。"""
    project = language_routes_mod.resolve_project(current, project_id)
    return JSONResponse(content={
        "project_id": project,
        "available": await language_routes_mod.admin_routes(project),
    })


@router.get(
    "/api/v1/asr/engines",
    tags=["ASR"],
    summary="列出這個部署設定齊全的伺服器端 ASR 引擎",
)
async def list_asr_engines(
    admin: CurrentAccount = Depends(require_admin),
) -> JSONResponse:
    """Engines the admin test bench can actually reach, so dead ones are not offered.

    ``engines`` 是批次（音檔上傳），``stream`` 是串流（/api/v1/asr/stream）；瀏覽器內建
    辨識在使用者裝置上跑，後端不知道能不能用，不列。
    """
    from app.gateway.asr_stream import configured_stream_engines
    from app.gateway.ingestion_audio import configured_providers

    return JSONResponse(content={
        "engines": configured_providers(),
        "stream": configured_stream_engines(),
    })


@router.post(
    "/api/v1/asr/preview",
    tags=["ASR"],
    response_model=AsrTranscription,
    summary="用指定的引擎試辨識一段語音",
)
async def preview_asr(
    admin: CurrentAccount = Depends(require_admin),
    file: UploadFile = File(...),
    provider: str = Form(""),
    project_id: str = Form(""),
    language_routes: str | None = Form(None),
) -> JSONResponse:
    """Transcribe an uploaded clip so an operator can hear-test an engine.

    走正式對話用的同一條 transcribe()，所以看到的就是實際會發生的行為，包含
    fallback；回傳實際辨識的引擎，指定的那家掛掉時看得出是備援答的。帶了專案就
    跟正式對話一樣套用專案詞表與語言分流（開台語分流時也聽是不是台語），但引擎
    照這裡選的跑，不換成 Breeze。只影響這一次，不會改到任何人的設定。
    """
    from app.auth.settings_repository import SERVER_ASR_PROVIDERS

    if provider and provider not in SERVER_ASR_PROVIDERS:
        return upload_failed_response(
            status_code=422,
            error=f"provider must be one of: {', '.join(sorted(SERVER_ASR_PROVIDERS))}",
        )
    suffix = os.path.splitext(file.filename or "")[1] or ".wav"
    tmp_path: str | None = None
    cfg = get_tts_config()
    try:
        tmp_path, _ = await persist_upload_to_tempfile(
            file,
            suffix=suffix,
            max_bytes=cfg.document_max_upload_bytes,
        )
        return JSONResponse(content=await _transcribe_routed(
            admin, tmp_path,
            project_id=project_id,
            language_routes=language_routes,
            preferred=provider or None,
            trace_id="asr-preview",
            taiwanese_uses_breeze=False,
        ))
    except UploadTooLargeError as exc:
        limit_mb = exc.limit_bytes / (1024 * 1024)
        return upload_failed_response(
            status_code=413,
            error=f"音檔超過大小限制（上限 {limit_mb:.0f} MB）",
        )
    except Exception as exc:
        logger.error("asr preview failed: %s", exc)
        return upload_failed_response(status_code=500, error=str(exc))
    finally:
        await file.close()
        cleanup_temp_path(tmp_path)
