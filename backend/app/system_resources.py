"""Register the system-provided resources that accounts can be granted.

Voices, ASR engines, mascots and backgrounds become ``system_public``
resources at startup so the admin pages can grant them one by one.
"""

from __future__ import annotations

import logging
from typing import Any

from app.auth.models import ResourceType
from app.auth.runtime import AuthRuntime
from app.http_client import SharedAsyncClient
from app.providers.cosyvoice_adapter import COSYVOICE_PROVIDER_NAME
from app.providers.gemini_tts_adapter import GEMINI_PROVIDER_NAME
from app.providers.voice_catalog import (
    EDGE_TTS_VOICE_LABELS,
    EDGE_TTS_VOICES,
    excluded_voices,
    fetch_cosyvoice_voices,
    fetch_gemini_voices,
    fetch_indextts_voices,
    fetch_voxcpm_voices,
)
from app.providers.voxcpm_adapter import VOXCPM_PROVIDER_NAME

logger = logging.getLogger("backend")

# 與 frontend/app/src/types/avatarBackground.ts 的 AVATAR_BACKGROUND_IDS 對應，
# label 沿用前台選單（SettingsModal）的中文名稱。
BUILTIN_AVATAR_BACKGROUNDS = (
    ("dark", "深色"),
    ("clinic", "診間"),
    ("studio", "棚拍"),
)

# 引擎清單是程式碼決定的（_TRANSCRIBERS 加 browser），不像聲音要跟外部服務
# 查。label 與前台選單一致，後台授權時看得懂在給什麼。
ASR_ENGINE_LABELS = {
    "breeze": "Breeze-ASR-26（臺語轉華語）",
    "r2t2": "Confucius4-R2T2（.35，華英混合，自動轉繁）",
    "r2t2-dev": "Confucius4-R2T2 dev（.37）",
    "sensevoice": "SenseVoice-Small（臺語漢字）",
    "openai": "OpenAI Whisper（語音送往外部服務）",
    "browser": "瀏覽器內建辨識（由瀏覽器廠商處理，不經本站伺服器）",
    "r2t2-live": "Confucius4-R2T2 串流辨識（.35，邊講邊出字，帶專案詞表）",
    "r2t2-dev-live": "Confucius4-R2T2 dev 串流辨識（.37）",
    "gemini-live": "Gemini 串流辨識（邊講邊出字，語音送往 Google）",
}


def sync_asr_engines(runtime: AuthRuntime) -> None:
    """Register the ASR engines so they can be granted per account.

    跟聲音一樣註冊成 system_public 資源，管理者才能在帳號頁逐一授權。這裡不
    管哪一家「設定齊全」——沒填 URL 的引擎照樣列出來，否則管理者會看到清單
    隨部署設定忽隱忽現，反而難判斷。實際可不可用由 fallback chain 決定。
    """
    for engine_id, label in ASR_ENGINE_LABELS.items():
        try:
            runtime.resources.upsert_system_resource(
                resource_type=ResourceType.ASR_ENGINE,
                resource_id=engine_id,
                metadata={"label": label},
            )
        except Exception as exc:
            logger.warning("failed to register asr engine %s: %s", engine_id, exc)
    drop_retired_asr_engines(runtime)


def drop_retired_asr_engines(runtime: AuthRuntime) -> None:
    """Forget engines removed from the code, along with their grants and choices.

    upsert 只會新增不會刪：拿掉的引擎（例如 xiaomi）會一直留在後台授權清單，
    帳號存的偏好也還指著它。刪資源時 resource_grants 與 admin_resource_scopes
    靠外鍵 ON DELETE CASCADE 一起清掉；偏好改回空字串，等於沒選過、用部署預設。
    """
    try:
        for record in runtime.resources.list_by_type(ResourceType.ASR_ENGINE):
            if record.resource_id not in ASR_ENGINE_LABELS:
                runtime.resources.unregister(ResourceType.ASR_ENGINE, record.resource_id)
                logger.info("removed retired asr engine %s", record.resource_id)
        cleared = runtime.account_access.clear_asr_providers_except(ASR_ENGINE_LABELS)
        if cleared:
            logger.info("cleared %d asr preferences naming a retired engine", cleared)
    except Exception as exc:
        logger.warning("failed to drop retired asr engines: %s", exc)


async def sync_system_resources(
    runtime: AuthRuntime,
    cfg: Any,
    http: SharedAsyncClient,
) -> None:
    """Register voices from enabled providers, mascots and backgrounds."""
    if cfg.edge_tts_enabled:
        edge_voices = list(EDGE_TTS_VOICES)
        if cfg.edge_tts_voice and cfg.edge_tts_voice not in edge_voices:
            edge_voices.insert(0, cfg.edge_tts_voice)
        for voice_id in edge_voices:
            label = EDGE_TTS_VOICE_LABELS.get(voice_id, f"{voice_id} (Edge-TTS)")
            try:
                runtime.resources.upsert_system_resource(
                    resource_type=ResourceType.CUSTOM_VOICE,
                    resource_id=voice_id,
                    metadata={"provider": "edge-tts", "label": label},
                )
            except Exception as exc:
                logger.warning("failed to register edge-tts voice %s: %s", voice_id, exc)

    if cfg.tts_indextts_url:
        try:
            fetched_voices = await fetch_indextts_voices(
                http,
                cfg.tts_indextts_url,
                cfg.gateway_internal_token,
            )
            for voice_id in fetched_voices:
                runtime.resources.upsert_system_resource(
                    resource_type=ResourceType.CUSTOM_VOICE,
                    resource_id=voice_id,
                    metadata={"provider": "indextts", "label": voice_id},
                )
        except Exception as exc:
            logger.warning("failed to sync indextts voices: %s", exc)

    if cfg.tts_gemini_url:
        try:
            gemini_voices = await fetch_gemini_voices(http, cfg.tts_gemini_url)
            for voice_id in gemini_voices:
                runtime.resources.upsert_system_resource(
                    resource_type=ResourceType.CUSTOM_VOICE,
                    resource_id=voice_id,
                    metadata={"provider": GEMINI_PROVIDER_NAME, "label": voice_id},
                )
        except Exception as exc:
            logger.warning("failed to sync gemini voices: %s", exc)

    if cfg.tts_voxcpm_url:
        try:
            for voice_id, label in await fetch_voxcpm_voices(
                http,
                cfg.tts_voxcpm_url,
                excluded_voices(cfg, "tts_voxcpm_excluded_voices"),
            ):
                runtime.resources.upsert_system_resource(
                    resource_type=ResourceType.CUSTOM_VOICE,
                    resource_id=voice_id,
                    metadata={"provider": VOXCPM_PROVIDER_NAME, "label": label},
                )
        except Exception as exc:
            logger.warning("failed to sync voxcpm voices: %s", exc)

    if cfg.tts_cosyvoice_url:
        try:
            for voice_id, label in await fetch_cosyvoice_voices(
                http,
                cfg.tts_cosyvoice_url,
                cfg.tts_cosyvoice_api_key,
                excluded_voices(cfg, "tts_cosyvoice_excluded_voices"),
            ):
                runtime.resources.upsert_system_resource(
                    resource_type=ResourceType.CUSTOM_VOICE,
                    resource_id=voice_id,
                    metadata={"provider": COSYVOICE_PROVIDER_NAME, "label": label},
                )
        except Exception as exc:
            logger.warning("failed to sync cosyvoice voices: %s", exc)

    if cfg.tts_gcp_enabled and cfg.tts_gcp_voice_name:
        try:
            runtime.resources.upsert_system_resource(
                resource_type=ResourceType.CUSTOM_VOICE,
                resource_id=cfg.tts_gcp_voice_name,
                metadata={"provider": "gcp", "label": f"{cfg.tts_gcp_voice_name} (GCP)"},
            )
        except Exception as exc:
            logger.warning("failed to register gcp voice: %s", exc)

    if cfg.tts_aws_enabled and cfg.tts_aws_polly_voice_id:
        try:
            runtime.resources.upsert_system_resource(
                resource_type=ResourceType.CUSTOM_VOICE,
                resource_id=cfg.tts_aws_polly_voice_id,
                metadata={"provider": "aws", "label": f"{cfg.tts_aws_polly_voice_id} (AWS)"},
            )
        except Exception as exc:
            logger.warning("failed to register aws voice: %s", exc)

    try:
        from app.routes.mascots import get_store as get_mascot_store
        for mascot in get_mascot_store().list_mascots():
            mid = mascot.get("mascot_id")
            mlabel = mascot.get("label") or mid
            if mid:
                runtime.resources.upsert_system_resource(
                    resource_type=ResourceType.AVATAR_MASCOT,
                    resource_id=mid,
                    metadata={"label": mlabel},
                )
    except Exception as exc:
        logger.warning("failed to sync mascots: %s", exc)

    try:
        from app.routes.backgrounds import get_store as get_background_store
        for bg in get_background_store().list_backgrounds():
            bid = bg.get("background_id")
            blabel = bg.get("label") or bid
            if bid:
                runtime.resources.upsert_system_resource(
                    resource_type=ResourceType.AVATAR_BACKGROUND,
                    resource_id=bid,
                    metadata={"label": blabel},
                )
    except Exception as exc:
        logger.warning("failed to sync backgrounds: %s", exc)

    # 前端內建的純 CSS 背景（AvatarCanvas 直接渲染，沒有實體檔案），
    # 仍要註冊成資源，否則管理端的權限選單看不到、也就無法指定成預設。
    for bid, blabel in BUILTIN_AVATAR_BACKGROUNDS:
        try:
            runtime.resources.upsert_system_resource(
                resource_type=ResourceType.AVATAR_BACKGROUND,
                resource_id=bid,
                metadata={"label": blabel, "builtin": True},
            )
        except Exception as exc:
            logger.warning("failed to register builtin background %s: %s", bid, exc)
