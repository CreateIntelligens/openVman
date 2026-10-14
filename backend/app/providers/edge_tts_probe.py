"""Periodic check that Edge TTS still accepts our connections.

Edge 朗讀不是公開 API：微軟改連線驗證時，舊版 edge-tts 一律被回 403
（2026-10-14 7.2.8 就是這樣），而 Edge 又是其他 TTS 失敗時的保底。以前要等
現場沒聲音才發現；現在定時試念一句，把結果放到 /healthz 與 Prometheus。
"""

from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timezone
from importlib.metadata import PackageNotFoundError, version
from typing import Any

from prometheus_client import Gauge

from app.config import get_tts_config

logger = logging.getLogger("backend")

_PROBE_TEXT = "測試"
_PROBE_TIMEOUT_SECONDS = 15.0

_edge_tts_up = Gauge("vman_edge_tts_up", "1 when the last Edge TTS probe produced audio")
_state: dict[str, Any] = {"status": "pending", "checked_at": None, "error": None}


def _package_version() -> str:
    try:
        return version("edge-tts")
    except PackageNotFoundError:
        return "missing"


async def check_edge_tts() -> dict[str, Any]:
    """Synthesize a short phrase and record whether Edge answered with audio."""
    from app.providers.edge_tts_adapter import _synthesize_async

    voice = get_tts_config().edge_tts_voice
    try:
        audio = await asyncio.wait_for(
            _synthesize_async(_PROBE_TEXT, voice), timeout=_PROBE_TIMEOUT_SECONDS,
        )
        # 微軟偶爾握手成功卻不給音訊，沒有位元組也算壞。
        error = None if audio else "no audio returned"
    except Exception as exc:  # noqa: BLE001 - 任何失敗都是「Edge 不能用」
        error = f"{type(exc).__name__}: {str(exc)[:200]}"
    _state.update(
        status="ready" if error is None else "error",
        checked_at=datetime.now(timezone.utc).isoformat(),
        error=error,
    )
    _edge_tts_up.set(1 if error is None else 0)
    if error is not None:
        logger.warning("edge-tts probe failed (edge-tts %s): %s", _package_version(), error)
    return edge_tts_probe_snapshot()


def edge_tts_probe_snapshot() -> dict[str, Any]:
    """Last probe result for /healthz; never calls Edge itself."""
    return {**_state, "edge_tts_version": _package_version()}


async def run_edge_tts_probe_loop(interval_seconds: int) -> None:
    while True:
        await check_edge_tts()
        await asyncio.sleep(interval_seconds)
