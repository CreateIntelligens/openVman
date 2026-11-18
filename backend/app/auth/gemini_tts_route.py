"""Which way Gemini TTS goes: straight to Google, or through the relay service."""

from __future__ import annotations

import logging
import threading
from collections.abc import Callable
from time import monotonic
from typing import Any

from .runtime import AuthRuntime, get_auth_runtime
from .settings_repository import (
    TTS_GEMINI_ROUTE_DIRECT,
    TTS_GEMINI_ROUTE_KEY,
    TTS_GEMINI_ROUTE_RELAY,
    TTS_GEMINI_ROUTES,
)

logger = logging.getLogger(__name__)

# Backend 跑好幾個 worker，各自有一份快取；後台在任一個 worker 存檔，其他 worker
# 最慢這麼久後讀到。每個 TTS 請求都會問路線，不快取就是每句一次資料庫讀取。
ROUTE_CACHE_SECONDS = 3.0

_lock = threading.Lock()
#: (讀取時間, 讀到的值)；None 代表這個 worker 還沒成功讀過，或剛存檔清掉。
_cache: tuple[float, str | None] | None = None
#: 每次存檔清快取就加一。存檔前開始的讀取帶著舊編號，讀完不能把舊值寫回快取。
_generation = 0


def clear_gemini_route_cache(saved: str | None = None) -> None:
    """Forget the cached route; *saved* primes it with the value just committed."""
    global _cache, _generation
    with _lock:
        _generation += 1
        _cache = (monotonic(), saved) if saved in TTS_GEMINI_ROUTES else None


def saved_gemini_route(runtime: AuthRuntime | None = None) -> str | None:
    """The route saved in the Admin, or None when nobody has saved one.

    帶 runtime 時直接讀（後台頁面要看到剛存的值）；不帶時走這個 worker 的短快取。
    """
    if runtime is not None:
        return _read(runtime)
    global _cache
    with _lock:
        cached, generation = _cache, _generation
    now = monotonic()
    if cached is not None and now - cached[0] < ROUTE_CACHE_SECONDS:
        return cached[1]
    try:
        stored = _read(get_auth_runtime())
    except Exception as exc:  # noqa: BLE001 - 讀不到設定時不能讓語音整個停掉
        logger.warning("gemini tts route setting unavailable: %s", type(exc).__name__)
        with _lock:
            if _cache is None:
                return None
            # 查詢失敗不等於沒設定：沿用最近一次讀到（或剛存檔）的路線，過一個
            # 間隔再試。改走部署預設可能把已選轉接的語音改用部署金鑰直連。
            if generation == _generation:
                _cache = (now, _cache[1])
            return _cache[1]
    with _lock:
        if generation == _generation:
            _cache = (now, stored)
    return stored


def gemini_route_usable(
    route: str, *, relay_url: str, has_shared_key: Callable[[], bool],
) -> bool:
    """Whether *route* can synthesize without a project's own key.

    adapter、聲音目錄與後台存檔共用這一條規則：relay 要有轉接網址，direct 要有
    共用金鑰。專案綁了自己的金鑰時一律直連，不受這裡影響。
    """
    if route == TTS_GEMINI_ROUTE_RELAY:
        return bool(relay_url.strip())
    return has_shared_key()


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
    "gemini_route_usable",
    "saved_gemini_route",
]
