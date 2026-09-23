import json
import logging
import re
from typing import Any

from tools.context import (
    active_persona_id,
    active_project_id,
    active_user_message,
)

from .knowledge_tools import _search_tool

logger = logging.getLogger(__name__)

# Jev 無法使用時的退路。它只看關鍵字：「你記得上次…」「會議記錄」會誤放行，
# 「幫我記下來」「把生日存起來」反而擋掉（2026-09-23 自寫 20 題 5/20）。
_EXPLICIT_MEMORY_REQUEST = re.compile(
    r"(?:記住|記得|記錄|紀錄|保存|保留|remember|memorize|save\s+this)",
    re.IGNORECASE,
)
# 與 scripts/experiments/jev/eval_replacements.py 同一題（同批 20 題 Jev 20/20）。
_MEMORY_REQUEST_QUESTION = {
    "instructions": "這句使用者訊息是否明確要求助理把某項資訊長期記住，供之後的對話使用？",
    "criteria": {
        "true": "使用者要求助理記住、儲存或之後沿用某項關於自己的資訊或偏好",
        "false": "只是提到記憶、紀錄、保存等字眼，或詢問過去，或要求不要記",
    },
}


def is_explicit_memory_request(user_message: str) -> bool:
    """Whether the current user turn explicitly asks to persist something.

    Only the user's own words authorize a long-term write: a model must not be
    able to persist instructions merely because they appeared in retrieved
    knowledge or another tool result.
    """
    text = (user_message or "").strip()
    if not text:
        return False
    from config import get_settings
    from core.jev_client import jev_available, jev_noul

    cfg = get_settings()
    if cfg.jev_memory_gate_enabled and jev_available():
        try:
            score = jev_noul(
                text, _MEMORY_REQUEST_QUESTION,
                timeout=cfg.jev_gate_timeout_seconds,
            )
            logger.info(json.dumps(
                {"event": "memory_gate", "source": "jev", "score": score},
            ))
            return score >= 0.5
        except Exception as exc:
            # 例外訊息可能夾帶回應內容；只記型別，退回規則。
            logger.warning(json.dumps(
                {"event": "memory_gate", "source": "regex_fallback",
                 "error_type": type(exc).__name__},
            ))
    return bool(_EXPLICIT_MEMORY_REQUEST.search(text))



def _save_memory(args: dict[str, Any]) -> dict[str, Any]:
    content = str(args.get("content", "")).strip()
    if not content:
        raise ValueError("content 不可為空")
    if not is_explicit_memory_request(active_user_message.get()):
        raise ValueError("只有使用者明確要求記憶時才能寫入長期記憶")
    if len(content) > 2000:
        raise ValueError("content 過長")
    from memory.embedder import encode_text
    from memory.memory import add_memory as store_memory
    vector = encode_text(content)
    store_memory(
        text=content,
        vector=vector,
        source="agent",
        persona_id=active_persona_id.get(),
        project_id=active_project_id.get(),
    )
    return {"saved": True, "content": content}

def save_memory_tool():
    from ..tool_registry import Tool
    return Tool(
        name="save_memory",
        description="將重要的使用者偏好、事實或指令儲存為長期記憶。只在使用者明確要求記住某事、或對話中出現值得長期保留的資訊時使用。儲存簡潔的陳述句，不要儲存閒聊或問題。",
        parameters={
            "type": "object",
            "properties": {
                "content": {
                    "type": "string",
                    "description": "要記住的內容，用簡潔的陳述句表達，例如「使用者是男生」、「使用者偏好繁體中文」",
                },
            },
            "required": ["content"],
        },
        handler=_save_memory,
    )

def search_memory_tool():
    from ..tool_registry import Tool
    return Tool(
        name="search_memory",
        description=(
            "搜尋與目前 persona / 專案相關的長期記憶。"
            "若使用者提到先前對話、偏好、過去事實，或可能在記憶中保存過的個人資訊，請優先呼叫此工具。"
            "若一次涉及多個主題，請拆成多個 queries 同時送出。"
        ),
        parameters={
            "type": "object",
            "properties": {
                "queries": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": (
                        "要搜尋的查詢列表，每筆為一個獨立、可獨立檢索的完整問題描述（含必要上下文）。"
                        "若使用者只有一個問題，仍以單元素陣列回傳。"
                    ),
                },
                "top_k": {"type": "integer", "description": "每個 query 最多回傳幾筆結果（合併後上限相同）"},
            },
            "required": ["queries"],
        },
        handler=lambda args: _search_tool("memories", args),
    )
