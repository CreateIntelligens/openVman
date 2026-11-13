"""Keep accounts without 「AI 整理排版」 away from the knowledge base's LLM cleanup.

Brain 不認得帳號，所以在 Backend 轉給 Brain 之前擋。會呼叫 LLM 整理文件的入口只有三個：
匯入時帶 ``normalize``、預覽整理、直接整理。套用預覽（``renormalize/apply``）只是存下已經
整理好的內容，跟一般存檔一樣，不擋。
"""

from __future__ import annotations

import json
from typing import Any

from app.auth.dependencies import CurrentAccount
from app.auth.models import has_ai_cleanup_access

REFUSAL = "這個帳號沒有開放「AI 整理排版」。請改用「直接放進知識庫」，或請管理員在帳號設定開放。"
_COMMIT_PATH = "knowledge/raw/commit"
_CLEANUP_PATHS = frozenset({"knowledge/renormalize", "knowledge/renormalize/preview"})


class AiCleanupRefused(PermissionError):
    """The caller asked for LLM cleanup without the permission."""


def _allowed(current: CurrentAccount | None) -> bool:
    # 嵌入金鑰給的是網站上的訪客，不是工作人員；API 金鑰照它所屬帳號的權限。
    if current is None or current.embed_key is not None:
        return False
    return has_ai_cleanup_access(current.user)


def guard_ai_cleanup(path: str, method: str, body: bytes, current: CurrentAccount | None) -> bytes:
    """Return the body to forward, or raise :class:`AiCleanupRefused`.

    匯入沒帶 ``normalize`` 時 Brain 預設會整理；沒有權限的人照「直接放進知識庫」處理，
    改寫成 ``false`` 而不是擋下，舊的整合方照樣匯入得了，只是不經過 AI。
    明確要求整理（``true``）才擋，讓呼叫端知道為什麼。
    """
    if method.upper() != "POST" or _allowed(current):
        return body
    if path in _CLEANUP_PATHS:
        raise AiCleanupRefused(REFUSAL)
    if path != _COMMIT_PATH:
        return body
    try:
        payload: Any = json.loads(body or b"{}")
    except ValueError:
        return body
    if not isinstance(payload, dict):
        return body
    if payload.get("normalize") is True:
        raise AiCleanupRefused(REFUSAL)
    if "normalize" in payload and payload["normalize"] is False:
        return body
    return json.dumps({**payload, "normalize": False}, ensure_ascii=False).encode("utf-8")
