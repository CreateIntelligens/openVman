"""LLM normalizer: clean raw extracted text into tidy Obsidian Markdown.

Knowledge documents are frequently OCR'd from PDFs and carry typos, missing
characters, layout noise, and — most damaging for heading-based chunking — body
text mis-detected as ``## headings``. This module asks the LLM to repair those
issues without fabricating content. Long input is split into segments (reusing
:func:`knowledge.graph_extractor._split_text`), each normalized via its own LLM
call, then rejoined. A failed segment falls back to its original text so content
is never lost.
"""

from __future__ import annotations

import logging

from core.llm_client import generate_chat_reply
from knowledge.graph_extractor import _split_text

logger = logging.getLogger("brain.knowledge.normalizer")

SEGMENT_SIZE = 6000

NORMALIZE_PROMPT = """你是知識庫文件整理助手。下面是一段從 PDF/掃描 OCR 轉出的中文文字，含有 OCR 錯字、缺字、排版雜訊，且標題層級被誤判（許多內文被當成 ## 標題）。

請整理成乾淨的 Markdown：
- 修正明顯的 OCR 錯字與缺字，但不可增刪或杜撰任何事實內容。
- 重建正確的標題階層：真正的章節才用標題，被誤判成標題的內文要還原成段落。
- 移除頁碼、亂碼表格殘渣等排版雜訊。
- 只輸出整理後的純 Markdown，不要解釋。

待整理文字：
---
{text}
---
"""


def _normalize_segment(segment: str) -> str:
    """Normalize one segment via the LLM, falling back to the original on error."""
    prompt = NORMALIZE_PROMPT.format(text=segment)
    try:
        return generate_chat_reply(
            [{"role": "user", "content": prompt}],
            privacy_source="graph_extractor",
        )
    except Exception:  # noqa: BLE001 - never drop content on LLM failure
        logger.warning(
            "normalizer: LLM call failed for a segment; using original text",
            exc_info=True,
        )
        return segment


def normalize_to_markdown(text: str) -> str:
    """Clean raw extracted text into tidy Obsidian-style Markdown via the LLM.

    Splits long input into segments, normalizes each, and rejoins. Returns the
    cleaned markdown. On LLM failure for a segment, falls back to that segment's
    original text (never loses content).
    """
    if not text.strip():
        return ""
    segments = _split_text(text, size=SEGMENT_SIZE)
    cleaned = [_normalize_segment(seg) for seg in segments]
    return "\n\n".join(cleaned).strip()
