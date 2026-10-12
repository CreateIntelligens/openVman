"""Which retrieved picture, if any, a reply shows — chosen by the decision chain.

原本直接顯示距離最近那筆引用的圖：問題本身不需要查知識庫時（「我聽不懂，請一步一步說明」），
最近的那筆也只是勉強沾邊，常常是型錄封面。改成把這輪檢索到、附圖的前幾筆交給決策模型，
請它選出最能回答問題的一筆，都沒有就不顯示。決策關閉、失敗或沒有候選時回 None，
呼叫端照原本的方式顯示。
"""

from __future__ import annotations

import contextvars
import json
import logging
import threading
from concurrent.futures import Future, ThreadPoolExecutor
from typing import Any

from config import get_settings

logger = logging.getLogger("core.reference_media")

_MAX_CANDIDATES = 5
_CANDIDATE_CHARS = 300
_NONE = "none"


def media_candidates(tool_steps: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Retrieved knowledge rows that carry a picture, closest first, one per question."""
    rows: list[dict[str, Any]] = []
    for step in tool_steps:
        if not isinstance(step, dict) or step.get("name") != "search_knowledge":
            continue
        result = step.get("result")
        try:
            data = (json.loads(result) if isinstance(result, str) else result or {}).get("data") or {}
        except (json.JSONDecodeError, AttributeError):
            continue
        for row in data.get("results") or []:
            if isinstance(row, dict) and str(row.get("image_id") or "").strip():
                rows.append(row)
    rows.sort(key=lambda row: float(row.get("_distance", 999.0)))
    candidates: list[dict[str, Any]] = []
    seen: set[str] = set()
    for row in rows:
        key = str(row.get("chunk_id") or row.get("text") or "")
        if key in seen:
            continue
        seen.add(key)
        candidates.append({
            "image_id": str(row["image_id"]).strip(),
            "url": str(row.get("url") or "").strip(),
            "text": str(row.get("text") or ""),
        })
        if len(candidates) == _MAX_CANDIDATES:
            break
    return candidates


def choose_reference_media(
    user_text: str, tool_steps: list[dict[str, Any]],
) -> dict[str, str] | None:
    """The picture to show (``{}`` for none), or None to fall back to the closest citation."""
    settings = get_settings()
    if not getattr(settings, "chat_reference_media_decision_enabled", True):
        return None
    candidates = media_candidates(tool_steps)
    if not candidates or not user_text.strip():
        return None

    criteria = {
        f"c{index}": candidate["text"][:_CANDIDATE_CHARS].replace("\n", " ")
        for index, candidate in enumerate(candidates)
    }
    criteria[_NONE] = "None of these answers the user's question."
    questions = {"pick": {
        "type": "choice",
        "instructions": "Which reference item best answers the user's question?",
        "criteria": criteria,
    }}
    try:
        from core.decision_router import decide

        answer = decide(
            {"user_question": user_text[:500]},
            questions,
            timeout=float(getattr(settings, "chat_reference_media_timeout_seconds", 1.0)),
            per_hop_timeout=float(getattr(settings, "turn_decisions_hop_timeout_seconds", 0.6)),
            purpose="reference_media",
        ).answers["pick"]
    except Exception as exc:  # 決策掛掉不影響回答，照原本顯示最近那筆
        logger.warning("reference media decision unavailable error_type=%s", type(exc).__name__)
        return None

    choice = answer.get("choice")
    # Clef 沒把握時仍會硬選一筆（信心 0.08～0.5），選對的多在 0.6 以上。
    min_confidence = float(getattr(settings, "chat_reference_media_min_confidence", 0.6))
    if choice == _NONE or float(answer.get("confidence") or 0) < min_confidence:
        return {}
    picked = candidates[int(str(choice)[1:])]
    media = {"image_id": picked["image_id"]}
    if picked["url"]:
        media["url"] = picked["url"]
    return media


class ReplyMediaChoice:
    """Pick the reply picture in the background as soon as retrieval results exist.

    選圖只需要問題與檢索結果，跟模型寫回答同時進行；查完知識庫就開始選，
    之後的工具輪若帶來不同的附圖候選就重選一次，收尾時拿最後一次的結果。
    """

    def __init__(self, user_text: str) -> None:
        self._user_text = user_text
        self._key: tuple[str, ...] | None = None
        self._future: Future[dict[str, str] | None] | None = None
        self._lock = threading.Lock()

    def on_tool_round(self, tool_steps: list[dict[str, Any]]) -> None:
        key = _candidate_key(tool_steps)
        if not key:
            return
        with self._lock:
            if key == self._key:
                return
            self._key = key
            # 帶著目前的 usage scope 與工具 context，決策用量才記在這一輪名下。
            context = contextvars.copy_context()
            self._future = _executor.submit(
                context.run, choose_reference_media, self._user_text, list(tool_steps),
            )

    def result(self, tool_steps: list[dict[str, Any]]) -> dict[str, str] | None:
        with self._lock:
            future = self._future if self._key == _candidate_key(tool_steps) else None
        if future is None:
            return choose_reference_media(self._user_text, tool_steps)
        timeout = float(getattr(get_settings(), "chat_reference_media_timeout_seconds", 1.0))
        try:
            return future.result(timeout=timeout)
        except Exception:  # 等不到就照原本顯示最近那筆
            return None


def _candidate_key(tool_steps: list[dict[str, Any]]) -> tuple[str, ...]:
    return tuple(f"{c['image_id']}\x00{c['text'][:80]}" for c in media_candidates(tool_steps))


_executor = ThreadPoolExecutor(max_workers=4, thread_name_prefix="reply-media")
