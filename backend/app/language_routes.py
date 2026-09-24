"""Language routes for voice requests (ASR engine and TTS provider).

分流由後台在知識庫設定勾選（存在 Brain：GET /brain/knowledge/settings）。前台可以
在後台開的範圍內臨時取消或勾回，送請求時帶 language_routes；這裡取兩者交集，
前台不能開出後台沒有的語言。有台語分流時：

- ASR 一律用 Breeze（台語直接翻成華語，華語也準），並另請 Brain 聽是不是台語。
- TTS 原本不是 VoxCPM／CosyVoice 就改用 VoxCPM（快）；本來就是這兩家不動。
"""

from __future__ import annotations

import asyncio
import logging
import subprocess
import time

from app.auth.dependencies import CurrentAccount
from app.auth.models import ResourceType
from app.auth.resources import ResourceAccess, resolve_resource
from app.auth.runtime import get_auth_runtime
from app.config import get_tts_config
from app.http_client import SharedAsyncClient

logger = logging.getLogger("language_routes")

CHINESE = "zh"
TAIWANESE = "nan"
KNOWN_ROUTES = ("zh", "en", "es", "nan")
TAIWANESE_ASR_ENGINE = "breeze"
TAIWANESE_TTS_PROVIDERS = ("voxcpm", "cosyvoice")

_INTERNAL_TOKEN_HEADER = "X-Internal-Token"
# 每次語音都要查分流；後台改設定後最多這麼久生效。
_CACHE_SECONDS = 30.0
_cache: dict[str, tuple[float, list[str]]] = {}
_http = SharedAsyncClient(connect=3, read=5)


def resolve_project(current: CurrentAccount, supplied_project_id: str) -> str | None:
    """The project this caller may use: an embed key's own, or one the account can read.

    查不到或沒權限就回 None（當作沒有分流），不讓語音請求失敗。
    """
    if current.embed_key is not None:
        return current.embed_key.project_id
    project_id = (supplied_project_id or "").strip()
    if not project_id:
        return None
    try:
        resolve_resource(
            get_auth_runtime().resources,
            current.user,
            ResourceType.PROJECT,
            project_id,
            access=ResourceAccess.READ,
        )
    except Exception:  # noqa: BLE001 - 沒權限就當沒有分流
        return None
    return project_id


async def admin_routes(project_id: str | None) -> list[str]:
    """Routes the admin ticked for this project's knowledge base."""
    if not project_id:
        return [CHINESE]
    cached = _cache.get(project_id)
    if cached and time.monotonic() - cached[0] < _CACHE_SECONDS:
        return cached[1]
    cfg = get_tts_config()
    try:
        response = await _http.get().get(
            f"{cfg.brain_url.rstrip('/')}/brain/knowledge/settings",
            params={"project_id": project_id},
            headers={_INTERNAL_TOKEN_HEADER: cfg.gateway_internal_token},
        )
        response.raise_for_status()
        routes = [
            route for route in response.json().get("language_routes", [])
            if route in KNOWN_ROUTES
        ]
    except Exception as exc:  # noqa: BLE001 - Brain 查不到就當只有中文
        logger.warning("language routes lookup failed for %s: %s", project_id, exc)
        return [CHINESE]
    routes = [CHINESE, *[route for route in routes if route != CHINESE]]
    _cache[project_id] = (time.monotonic(), routes)
    return routes


def parse_requested(raw: str | list[str] | None) -> list[str] | None:
    """Parse the client's current toggles; None means "no preference, use all"."""
    if raw is None:
        return None
    items = raw.split(",") if isinstance(raw, str) else raw
    return [item.strip() for item in items if item and item.strip()]


async def effective_routes(
    current: CurrentAccount,
    supplied_project_id: str,
    requested: list[str] | None,
) -> list[str]:
    """Admin routes narrowed by the client's toggles; Chinese is always kept."""
    allowed = await admin_routes(resolve_project(current, supplied_project_id))
    if requested is None:
        return allowed
    return [route for route in allowed if route == CHINESE or route in requested]


def taiwanese_tts_provider(provider: str | None) -> str | None:
    """Provider to use when the Taiwanese route is on, or None to keep the current one."""
    if provider in TAIWANESE_TTS_PROVIDERS:
        return None
    return TAIWANESE_TTS_PROVIDERS[0]


def _to_wav_bytes(file_path: str) -> bytes:
    # 判斷模型要 WAV；前台送來的多半是 webm/opus，一律轉 16 kHz 單聲道。
    result = subprocess.run(
        ["ffmpeg", "-nostdin", "-loglevel", "error", "-i", file_path,
         "-ac", "1", "-ar", "16000", "-f", "wav", "pipe:1"],
        capture_output=True,
        timeout=60,
    )
    if result.returncode != 0:
        raise RuntimeError(f"audio conversion failed: {result.stderr[:200]!r}")
    return result.stdout


async def detect_taiwanese(file_path: str) -> str | None:
    """Ask Brain whether the clip is Taiwanese; None when it cannot tell."""
    cfg = get_tts_config()
    try:
        wav_bytes = await asyncio.to_thread(_to_wav_bytes, file_path)
        response = await _http.get().post(
            f"{cfg.brain_url.rstrip('/')}/brain/internal/audio-language",
            content=wav_bytes,
            headers={
                _INTERNAL_TOKEN_HEADER: cfg.gateway_internal_token,
                "Content-Type": "audio/wav",
            },
            timeout=35.0,
        )
        response.raise_for_status()
        language = response.json().get("language")
    except Exception as exc:  # noqa: BLE001
        logger.warning("audio language check failed: %s", exc)
        return None
    return language if language in KNOWN_ROUTES else None
