"""What a turn reads before the model answers — shared by HTTP chat and Gemini Live.

每輪決策之後「要先查哪些、用什麼查詢」原本 HTTP（agent_loop）與 Live（gemini_turns）各寫
一份，兩邊分歧：Live 的追問句只用這一句去查，查不到上一句講的型號；關閉記憶回想的
處理也各寫一次。這裡只決定查什麼、怎麼組查詢；實際執行、時限與怎麼把結果放回對話，
仍由各入口依自己的協定處理。
"""

from __future__ import annotations

from dataclasses import replace
from typing import Any

from core.turn_decisions import TurnDecision

KNOWLEDGE_SEARCH = "search_knowledge"
WEB_SEARCH = "search_web"
MEMORY_SEARCH = "search_memory"

# 追問句（「那價格呢？」）自己查不到東西，把上一句問題接在前面當第二條查詢；
# 上一句只取開頭，太長會把這一句的意思稀釋掉。
_PREVIOUS_CONTEXT_CHARS = 200


def message_text(content: Any) -> str:
    """Text of a plain or multimodal (``[{"type": "text", ...}, {"type": "image_url", ...}]``) message."""
    if isinstance(content, str):
        return content.strip()
    if isinstance(content, list):
        return "\n".join(
            part["text"].strip()
            for part in content
            if isinstance(part, dict)
            and part.get("type") == "text"
            and isinstance(part.get("text"), str)
        ).strip()
    return ""


def user_texts(messages: list[dict[str, Any]]) -> list[str]:
    # 每個 user 訊息都留一筆（沒文字的是空字串），最後一筆才一定是那一句：
    # 只收純文字訊息時，這一句若是圖文混合，會把上一句當成這一句。
    return [message_text(m.get("content")) for m in messages if m.get("role") == "user"]


def previous_user_text(messages: list[dict[str, Any]], current_text: str) -> str:
    """The latest earlier user question; *messages* may or may not already end with this turn."""
    texts = user_texts(messages)
    # HTTP 的對話最後一筆就是這一句；Live 的轉錄在決策前已寫進歷史。兩種都先去掉這一句。
    if texts and texts[-1] == current_text:
        texts = texts[:-1]
    return next((text for text in reversed(texts) if text), "")


def knowledge_queries(current_text: str, previous_text: str) -> list[str]:
    """This turn's words, plus the previous question joined in front of them.

    換話題時兩條查詢都會命中新主題（鶴記dev 換題對照答案不受上一句影響）。
    """
    queries = [current_text]
    if previous_text and current_text:
        queries.append(f"{previous_text[:_PREVIOUS_CONTEXT_CHARS]}\n{current_text}")
    return queries


def planned_reads(
    *,
    current_text: str,
    previous_text: str = "",
    knowledge: bool,
    web: bool,
    memory: bool,
) -> list[tuple[str, dict[str, Any]]]:
    """The read-only tool calls a decided turn needs, in a fixed order; empty without text."""
    if not current_text:
        return []
    reads: list[tuple[str, dict[str, Any]]] = []
    if knowledge:
        reads.append((KNOWLEDGE_SEARCH, {"queries": knowledge_queries(current_text, previous_text)}))
    if web:
        reads.append((WEB_SEARCH, {"query": current_text}))
    if memory:
        reads.append((MEMORY_SEARCH, {"queries": [current_text]}))
    return reads


def without_disabled_recall(
    decision: TurnDecision, session_id: str, project_id: str,
) -> TurnDecision:
    """Drop a positive memory read when the user turned session recall off."""
    if decision.policy.needs_memory is not True:
        return decision
    from memory.memory import is_session_recall_disabled

    if not is_session_recall_disabled(session_id, project_id):
        return decision
    return replace(
        decision,
        policy=replace(decision.policy, needs_memory=None, auto_recall=False),
    )
