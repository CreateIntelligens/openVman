"""Account ASR uploads, admin previews, and project language route discovery."""

from __future__ import annotations

import asyncio
import logging
import os
from time import monotonic

from fastapi import APIRouter, Depends, File, Form, UploadFile
from fastapi.responses import JSONResponse

from app import asr_glossary as asr_glossary_mod
from app import language_routes as language_routes_mod
from app.auth.dependencies import (
    CurrentAccount,
    get_current_account,
    require_admin,
)
from app.config import get_tts_config
from app.error_payloads import upload_failed_response
from app.utils.upload import (
    UploadTooLargeError,
    cleanup_temp_path,
    persist_upload_to_tempfile,
)

logger = logging.getLogger("backend")
router = APIRouter()


@router.post(
    "/api/v1/asr/transcribe",
    tags=["Settings"],
    summary="以這個帳號選定的引擎轉寫一段語音",
)
async def transcribe_for_account(
    account: CurrentAccount = Depends(get_current_account),
    file: UploadFile = File(...),
    project_id: str = Form(""),
    language_routes: str | None = Form(None),
) -> JSONResponse:
    """Transcribe a clip for an ordinary signed-in user.

    跟後台的試辨識走同一條 transcribe()，差別只在權限：這個端點任何登入帳號
    都能用，而引擎由後端依帳號自己查（_account_asr_provider），不接受呼叫端
    指定——否則使用者改個請求就能繞過管理者的開放清單。
    """
    from app.gateway.worker import _account_asr_provider

    suffix = os.path.splitext(file.filename or "")[1] or ".wav"
    tmp_path: str | None = None
    cfg = get_tts_config()
    try:
        tmp_path, _ = await persist_upload_to_tempfile(
            file,
            suffix=suffix,
            max_bytes=cfg.document_max_upload_bytes,
        )
        from app.gateway.ingestion_audio import transcribe

        preferred = _account_asr_provider({"owner_user_id": account.user.id})
        routes = await language_routes_mod.effective_routes(
            account, project_id, language_routes_mod.parse_requested(language_routes),
        )
        prompt = await asr_glossary_mod.project_asr_prompt(account, project_id)
        started = monotonic()
        speech_language: str | None = None
        language_check: dict | None = None
        if language_routes_mod.TAIWANESE in routes:
            # 台語分流：Breeze 把台語直接翻成華語（華語也準），同時請 Brain 聽是不是台語，
            # 轉錄出來的華語文字看不出原本講的是台語。
            preferred = language_routes_mod.TAIWANESE_ASR_ENGINE
            result, heard = await asyncio.gather(
                transcribe(tmp_path, "asr-chat", preferred, prompt=prompt),
                language_routes_mod.detect_taiwanese(tmp_path),
            )
            speech_language = heard.language if heard.language == language_routes_mod.TAIWANESE else None
            language_check = {"result": heard.result, "ms": heard.ms}
        else:
            result = await transcribe(tmp_path, "asr-chat", preferred, prompt=prompt)
        return JSONResponse(content={
            "text": result.content,
            # 實際辨識的引擎：偏好的掛掉由備援接手時不是同一個；全掛時是空字串。
            "provider": result.provider or "",
            "elapsed_seconds": round(monotonic() - started, 2),
            "language": speech_language,
            # 台語分流時才有：判斷結果（語言代碼、timeout、failed）與耗時。
            "language_check": language_check,
            "language_routes": routes,
        })
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


@router.post(
    "/api/v1/asr/preview",
    tags=["ASR"],
    summary="用指定的引擎試辨識一段語音",
)
async def preview_asr(
    _admin: CurrentAccount = Depends(require_admin),
    file: UploadFile = File(...),
    provider: str = Form(""),
) -> JSONResponse:
    """Transcribe an uploaded clip so an operator can hear-test an engine.

    走正式對話用的同一條 transcribe()，所以看到的就是實際會發生的行為，包含
    fallback；回傳實際辨識的引擎，指定的那家掛掉時看得出是備援答的。只影響這
    一次，不會改到任何人的設定。沒指定就用部署預設。
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
        from app.gateway.ingestion_audio import transcribe

        # 只量轉寫本身，不含上傳與轉檔：操作者要比的是引擎誰快，把網路時間
        # 算進去會讓同一個引擎在不同網路下看起來像兩回事。
        started = monotonic()
        result = await transcribe(tmp_path, "asr-preview", preferred=provider or None)
        elapsed = monotonic() - started
        return JSONResponse(content={
            "text": result.content,
            "provider": result.provider or "",
            "elapsed_seconds": round(elapsed, 2),
        })
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
