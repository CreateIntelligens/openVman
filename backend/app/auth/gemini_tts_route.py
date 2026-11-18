"""Which way Gemini TTS goes: straight to Google, or through the relay service."""

from __future__ import annotations

import logging
from time import monotonic
from typing import Any

from .runtime import AuthRuntime, get_auth_runtime
from .settings_repository import (
    TTS_GEMINI_ROUTE_DIRECT,
    TTS_GEMINI_ROUTE_KEY,
    TTS_GEMINI_ROUTES,
)

logger = logging.getLogger(__name__)

# Backend 跑好幾個 worker，各自有一份快取；後台在任一個 worker 存檔，其他 worker
# 最慢這麼久後讀到。每個 TTS 請求都會問路線，不快取就是每句一次資料庫讀取。
ROUTE_CACHE_SECONDS = 3.0

_cache: tuple[float, str | None] | None = None


def clear_gemini_route_cache() -> None:
    global _cache
    _cache = None


def saved_gemini_route(runtime: AuthRuntime | None = None) -> str | None:
    """The route saved in the Admin, or None when nobody has saved one.

    帶 runtime 時直接讀（後台頁面要看到剛存的值）；不帶時走這個 worker 的短快取。
    """
    if runtime is not None:
        return _read(runtime)
    global _cache
    now = monotonic()
    cached = _cache
    if cached is not None and now - cached[0] < ROUTE_CACHE_SECONDS:
        return cached[1]
    try:
        stored = _read(get_auth_runtime())
    except Exception as exc:  # noqa: BLE001 - 讀不到設定時照部署預設，不能讓語音整個停掉
        logger.warning("gemini tts route setting unavailable: %s", exc)
        stored = None
    _cache = (now, stored)
    return stored


def gemini_route(cfg: Any, runtime: AuthRuntime | None = None) -> str:
    """``direct`` or ``relay``: the Admin's choice, else the deployment default."""
    stored = saved_gemini_route(runtime)
    if stored in TTS_GEMINI_ROUTES:
        return stored
    default = getattr(cfg, "tts_gemini_route", TTS_GEMINI_ROUTE_DIRECT)
    return default if default in TTS_GEMINI_ROUTES else TTS_GEMINI_ROUTE_DIRECT


def _read(runtime: AuthRuntime) -> str | None:
    stored = runtime.settings.get(TTS_GEMINI_ROUTE_KEY)
    return stored if stored in TTS_GEMINI_ROUTES else None


__all__ = [
    "ROUTE_CACHE_SECONDS",
    "clear_gemini_route_cache",
    "gemini_route",
    "saved_gemini_route",
]
