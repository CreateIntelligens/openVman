"""語意查詢擴展 — 用 LLM 產生最多 N 個替代搜尋詞,供多路檢索 RRF 融合。

失敗時一律回傳空 list,不阻斷檢索主流程。
"""

from __future__ import annotations

import logging
import re

logger = logging.getLogger(__name__)

_EXPANSION_SYSTEM_PROMPT = (
    "你是檢索查詢擴展器。給定一個搜尋查詢,產生語意相近的替代搜尋詞"
    "(同義詞、改寫、相關術語),幫助找到字面不同但內容相關的文件。"
    "規則:每行一個詞,不要編號、不要符號、不要解釋;"
    "不要重複原查詢;最多 {max_terms} 個;若無合適擴展,輸出 NONE。"
)

_MAX_TERM_CHARS = 80

# 行首的「1. / 2、/ 3) / - / * / •」等編號或項目符號(不誤傷「3D列印」這類詞首數字)
_LINE_PREFIX_RE = re.compile(r"^(\d+\s*[.、)]|[-*•])\s*")


def expand_query(
    query: str,
    *,
    max_terms: int = 3,
    model: str | None = None,
    trace_id: str = "",
) -> list[str]:
    """以 LLM 產生最多 *max_terms* 個語意擴展詞。

    空查詢、max_terms <= 0、LLM 失敗或回 NONE 時回傳 []。
    """
    if not query.strip() or max_terms <= 0:
        return []

    from core.llm_client import generate_chat_reply

    messages = [
        {"role": "system", "content": _EXPANSION_SYSTEM_PROMPT.format(max_terms=max_terms)},
        {"role": "user", "content": f"查詢：{query.strip()}"},
    ]
    try:
        reply = generate_chat_reply(
            messages,
            model_override=model or None,
            trace_id=trace_id,
            privacy_source="query_expansion",
        )
    except Exception as exc:
        logger.warning("query expansion LLM call failed: %s", exc)
        return []

    return parse_expansion_terms(reply, query, max_terms)


def parse_expansion_terms(reply: str, query: str, max_terms: int) -> list[str]:
    """解析 LLM 回覆為擴展詞 list:逐行、去前綴符號、去重、去原查詢、截斷。"""
    if not reply or reply.strip().upper() == "NONE":
        return []

    original = query.strip().casefold()
    seen: set[str] = set()
    terms: list[str] = []

    for line in reply.splitlines():
        term = _LINE_PREFIX_RE.sub("", line.strip()).strip()
        if not term or len(term) > _MAX_TERM_CHARS:
            continue
        normalized = term.casefold()
        if normalized == original or normalized in seen:
            continue
        seen.add(normalized)
        terms.append(term)
        if len(terms) >= max_terms:
            break

    return terms
