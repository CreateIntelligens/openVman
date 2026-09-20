"""Deterministic guard for transcript-triggered interruptions."""

import re
import unicodedata
from typing import Literal


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
        # Preserve the existing conservative fallback for unknown long speech.
        return "STOP" if len(meaningful) > 5 else "IGNORE"
