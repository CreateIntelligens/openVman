"""Forward non-LLM usage events to Brain's ledger.

帳本由 Brain 單一擁有（`brain/api/infra/usage_ledger.py`）。Backend 的 TTS 不能
直接開同一個 SQLite 檔——兩個服務同時寫會有鎖競爭，也會讓「誰擁有帳本」這件事
失去單一答案。所以走既有的 internal token，POST 到 Brain，跟 Backend 代理讀取
`/brain/usage/summary` 的方向對稱。

寫入是盡力而為：記帳失敗不可以讓使用者的語音合成失敗。
"""

from __future__ import annotations

import logging
import threading
from typing import Any

import httpx

from app.config import get_tts_config

logger = logging.getLogger("usage.ledger_client")

_INTERNAL_TOKEN_HEADER = "X-Internal-Token"
_TIMEOUT_SECONDS = 5.0

UNIT_CHARS = "chars"
UNIT_SECONDS = "seconds"

_EMBED_PRINCIPAL_TYPE = "embed_key"
_SESSION_PRINCIPAL_TYPE = "user"


def usage_scope_for(
    current: Any | None,
    *,
    project_id: str = "",
    session_id: str = "",
    channel: str = "",
) -> dict[str, Any]:
    """Build the ledger attribution fields for an authenticated caller.

    主體判定與 `brain_proxy._trusted_upstream_headers()` 一致：有 embed key 就
    記成金鑰主體，否則記成帳號主體。這樣 TTS 的用量才跟 LLM 的用量用同一套
    維度彙總，Usage 頁面的「主體」篩選對兩者都成立。

    `current` 為 None（系統自己觸發、沒有帳號脈絡）時回傳空 dict，事件仍會
    入帳但不記名。
    """
    if current is None or getattr(current, "user", None) is None:
        return {}

    user = current.user
    embed_key = getattr(current, "embed_key", None)
    if embed_key is not None:
        principal_type = _EMBED_PRINCIPAL_TYPE
        principal_id = embed_key.key_id
    else:
        principal_type = _SESSION_PRINCIPAL_TYPE
        principal_id = user.id

    scope: dict[str, Any] = {
        "user_id": user.id,
        "role": getattr(user.role, "value", str(user.role)),
        "principal_type": principal_type,
        "principal_id": principal_id,
    }
    if project_id:
        scope["project_id"] = project_id
    if session_id:
        scope["session_id"] = session_id
    if channel:
        scope["channel"] = channel
    return scope


def record_usage_event(
    *,
    provider: str,
    model: str = "",
    kind: str = "tts",
    unit_type: str,
    units: float,
    latency_ms: float = 0.0,
    scope: dict[str, Any] | None = None,
    raw: dict[str, Any] | None = None,
) -> None:
    """Send one usage event to Brain, in a background thread.

    合成是同步路徑，記帳不該讓它多等一次網路往返，所以丟背景執行緒。
    """
    payload: dict[str, Any] = {
        "provider": provider,
        "model": model,
        "kind": kind,
        "unit_type": unit_type,
        "units": float(units),
        "latency_ms": float(latency_ms),
        **(scope or {}),
    }
    if raw:
        payload["raw"] = raw

    thread = threading.Thread(
        target=_post, args=(payload,), name="usage-ledger-write", daemon=True,
    )
    thread.start()


def _post(payload: dict[str, Any]) -> None:
    cfg = get_tts_config()
    # 沒有 internal token 就不是可用的部署（測試、本機裸跑），直接跳過而不是
    # 每次合成都打一次註定失敗的網路請求。
    if not cfg.gateway_internal_token:
        return
    url = f"{cfg.brain_url.rstrip('/')}/brain/usage/events"
    try:
        response = httpx.post(
            url,
            json=payload,
            headers={_INTERNAL_TOKEN_HEADER: cfg.gateway_internal_token},
            timeout=_TIMEOUT_SECONDS,
        )
        if response.status_code >= 400:
            logger.warning(
                "usage ledger rejected event provider=%s status=%s",
                payload.get("provider"),
                response.status_code,
            )
    except Exception as exc:
        logger.warning(
            "usage ledger write failed provider=%s: %s", payload.get("provider"), exc,
        )
