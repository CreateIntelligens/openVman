"""Deterministic guard for transcript-triggered interruptions."""

import json
import logging
import re
import unicodedata
from typing import Literal

logger = logging.getLogger(__name__)

# 與 scripts/experiments/jev/eval_replacements.py 同一題。規則判不出的長句原本一律
# STOP，附和、對旁人說話也會誤停（自寫 30 題規則 23/30、Jev 29/30）。
_JEV_INTERRUPT_QUESTION = {
    "type": "choice",
    "instructions": (
        "助理正在說話。這句 ASR 辨識文字是否表示使用者要中斷助理？"
        "單字停止命令、修正、新問題都算；附和、對旁人說話、要求繼續不算。"
    ),
    "criteria": {
        "STOP": "使用者對正在說話的助手提出停止、修正或新的問題，需要中斷當前回答。",
        "IGNORE": "只是附和、背景對話、對別人說話，或明確要求助手繼續說，不應中斷。",
    },
}


_QUOTED_TEXT = re.compile(
    r'「[^」]*」|『[^』]*』|“[^”]*”|"[^"\n]*"'
    r"|‘[^’]*’|(?<!\w)'[^'\n]*'(?!\w)"
)
# Remove only recognized non-interrupting phrases, not the whole utterance:
# a later correction or new question must still be able to interrupt.
_NON_INTERRUPTING = re.compile(
    r"(?:請|你|您|麻煩你|麻煩您)?(?:不用|不要|不必|別)(?:再)?(?:停止|暫停|停下來|停下|停|等)"
    r"|(?:不是|沒有)(?:在)?(?:叫|要|請)(?:你|您)(?:停止|暫停|停)"
    r"|(?:我)?(?:只|正|剛才)?(?:是)?在(?:跟|和)(?:旁邊的人|別人|他|她)說話"
    r"|(?:旁邊的人|別人|他|她)(?:剛才)?(?:說|講)(?:了)?"
    r"(?:停止|暫停|等一下|停|stop\b|wait\b)?"
    r"|(?:請|你|您|麻煩你|麻煩您)?(?:繼續(?:說下去|講下去|說|講|回答|下一段)?"
    r"|接著(?:說|講)(?:下去)?)(?:就好)?"
    r"|(?:這段)?我懂了|我有在聽|(?:我)?(?:了解|知道|明白)(?:了)?"
    r"(?=$|[\s，,。.!！?？；;]|(?:請|你|您)?繼續)"
    r"|收到|沒錯|謝謝(?:你)?|聽到了|嗯+|喔+|哦+|好+|(?<!不)對+"
    r"|\b(?:please\s+)?(?:do\s+not|don['’]t|no\s+need\s+to)"
    r"\s+stop\b(?:\s+(?:talking|speaking)\b)?"
    r"|\b(?:please\s+)?(?:keep\s+(?:going|talking)|continue|go\s+on)\b"
    r"|\b(?:ok(?:ay)?|yes|yeah|uh[- ]?huh|thanks)\b",
    re.IGNORECASE,
)
_STOP_CONTINUING = re.compile(r"(?:不要|不用|別)(?:再)?(?:繼續|說|講)")
_INTENT = re.compile(
    r"停|等一下|等等|請|麻煩|為什麼|如何|不對|先(?:別|不要)(?:說|講)"
    r"|\b(?:stop|wait)\b",
    re.IGNORECASE,
)


class GuardAgent:
    """Keep acknowledgements out of the interruption path without an LLM."""

    def __init__(self, model: str = "lightweight"):
        self.model = model

    async def classify(self, text: str) -> Literal["STOP", "IGNORE"]:
        normalized = unicodedata.normalize("NFKC", text).strip()
        if not normalized:
            return "IGNORE"

        # Quoted commands are evidence of speech, not commands to this agent.
        remaining = _QUOTED_TEXT.sub("", normalized)
        if _STOP_CONTINUING.search(remaining):
            return "STOP"
        remaining = _NON_INTERRUPTING.sub("", remaining)
        if _INTENT.search(remaining):
            return "STOP"

        meaningful = "".join(char for char in remaining if char.isalnum())
        if len(meaningful) <= 5:
            return "IGNORE"
        # Unknown long speech: ask Jev when enabled, else keep the
        # conservative STOP. Any Jev failure also falls back to STOP.
        return await _classify_ambiguous(normalized)


async def _classify_ambiguous(text: str) -> Literal["STOP", "IGNORE"]:
    from app.config import get_tts_config
    from app.jev_client import jev_answer, jev_available

    cfg = get_tts_config()
    if not (cfg.jev_interrupt_enabled and jev_available()):
        return "STOP"
    try:
        answer = await jev_answer(
            text, _JEV_INTERRUPT_QUESTION,
            timeout=cfg.jev_interrupt_timeout_seconds,
        )
    except Exception as exc:
        logger.warning(json.dumps(
            {"event": "interrupt_jev_fallback", "error_type": type(exc).__name__},
        ))
        return "STOP"
    choice = answer.get("choice")
    logger.info(json.dumps(
        {"event": "interrupt_jev", "choice": choice, "confidence": answer.get("confidence")},
    ))
    return "IGNORE" if choice == "IGNORE" else "STOP"
