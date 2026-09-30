"""The project's speech glossary, fetched from Brain for ASR engines that take a prompt.

詞表存在 Brain 的專案 workspace（ASR_PROMPT.md）；Breeze 與 OpenAI 辨識可以把它當
Whisper 前文，「污泥泵」「DIVA」這類專有名詞就不會被聽成同音字（Breeze 12 句合成音
12 句修正，台語回歸沒有硬塞詞表的字）。只帶正確的詞，Brain 會把「常見誤聽」對照行拿掉。
"""

from __future__ import annotations

import logging
import time

from app.auth.dependencies import CurrentAccount
from app.config import get_tts_config
from app.http_client import SharedAsyncClient
from app.language_routes import resolve_project

logger = logging.getLogger("asr_glossary")

_INTERNAL_TOKEN_HEADER = "X-Internal-Token"
# 每句語音都要用；後台改詞表後最多這麼久生效。
_CACHE_SECONDS = 60.0
_cache: dict[str, tuple[float, str]] = {}
_http = SharedAsyncClient(connect=2, read=2)


async def project_asr_prompt(current: CurrentAccount, supplied_project_id: str) -> str:
    """Correct terms for this caller's project, or "" (no project, none set, Brain down)."""
    project_id = resolve_project(current, supplied_project_id)
    if not project_id:
        return ""
    cached = _cache.get(project_id)
    if cached and time.monotonic() - cached[0] < _CACHE_SECONDS:
        return cached[1]
    cfg = get_tts_config()
    try:
        response = await _http.get().get(
            f"{cfg.brain_url.rstrip('/')}/brain/internal/asr-glossary",
            params={"project_id": project_id},
            headers={_INTERNAL_TOKEN_HEADER: cfg.gateway_internal_token},
        )
        response.raise_for_status()
        terms = str(response.json().get("terms") or "").strip()
    except Exception as exc:  # noqa: BLE001 - 詞表只是加分，拿不到照樣辨識
        logger.warning("asr glossary unavailable: %s", type(exc).__name__)
        return ""
    _cache[project_id] = (time.monotonic(), terms)
    return terms
