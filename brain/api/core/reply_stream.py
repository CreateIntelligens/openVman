"""Turn the final answer's streamed text into sentences while the model still writes.

``POST /brain/chat/stream`` hands a :class:`ReplyStream` to the generation. The LLM
client feeds it every text delta of each streamed attempt; tool-call rounds stop
feeding it as soon as a tool call appears. When generation ends the route calls
:meth:`ReplyStream.finish` with the final reply, which sends whatever has not been
sent yet, so the sentences of the final answer always add up to ``reply``.

句子是給整合方逐句送 TTS 用的：寧可晚一個 token 確認句尾，也不要把 3.5、網址
或型號切成兩半念。
"""

from __future__ import annotations

import logging
import re
from collections.abc import Callable

logger = logging.getLogger(__name__)

# 中日文句尾：看到就是句尾，不用等後面的空白。
_CJK_TERMINATORS = frozenset("。！？；…")
# 英文句尾：後面要接空白（或整段結束）才算，3.5、網址、檔名因此不會被切開。
_LATIN_TERMINATORS = frozenset(".!?")
# 句尾符號後面可以跟著的收尾字元，一起算進這一句。
_CLOSERS = frozenset("」』）)]】》〉\"'”’*`~")
_TAIL = _CJK_TERMINATORS | _LATIN_TERMINATORS | _CLOSERS
# 「Mr. Smith」「e.g. this」「No. 5」：句點後面雖然有空白，但不是句尾。
_ABBREVIATIONS = frozenset({
    "mr", "mrs", "ms", "dr", "prof", "st", "vs", "e.g", "i.e", "no", "fig", "approx",
})
# 「1. 第一項」「a. 選項」這種清單編號單獨成句沒有意義。
_LIST_MARKER = re.compile(r"(?:\d{1,3}|[A-Za-z])", re.ASCII)
_WORD_BEFORE_DOT = re.compile(r"([A-Za-z][A-Za-z.]*)$", re.ASCII)


def _is_cjk(char: str) -> bool:
    code = ord(char)
    return (
        0x3040 <= code <= 0x30FF      # 平假名、片假名
        or 0x3400 <= code <= 0x4DBF   # CJK 擴充 A
        or 0x4E00 <= code <= 0x9FFF   # CJK 統一漢字
        or 0xAC00 <= code <= 0xD7AF   # 韓文
        or 0xF900 <= code <= 0xFAFF   # 相容漢字
    )


class SentenceSplitter:
    """Cut a growing text into sentences; ``feed`` deltas, then ``flush`` the rest.

    Sentences keep the text's own whitespace (a sentence after a newline starts with
    that newline), so joining everything ``feed`` and ``flush`` return gives back the
    fed text with only its leading and trailing whitespace removed.
    *strip_leading* is False when continuing a text whose start was already sent.
    """

    def __init__(self, *, strip_leading: bool = True) -> None:
        self._buf = ""
        self._scan = 0
        self._started = not strip_leading

    def feed(self, delta: str) -> list[str]:
        if not self._started:
            delta = delta.lstrip()
            if not delta:
                return []
            self._started = True
        self._buf += delta
        return self._drain(final=False)

    def flush(self) -> list[str]:
        sentences = self._drain(final=True)
        rest = self._buf.rstrip()
        self._buf, self._scan = "", 0
        if rest.strip():
            sentences.append(rest)
        return sentences

    def _drain(self, *, final: bool) -> list[str]:
        sentences: list[str] = []
        while True:
            end = self._next_boundary(final=final)
            if end is None:
                return sentences
            sentences.append(self._buf[:end])
            self._buf = self._buf[end:]
            self._scan = 0

    def _next_boundary(self, *, final: bool) -> int | None:
        """End index of the first complete sentence in the buffer, or None to wait."""
        buf = self._buf
        i = self._scan
        while i < len(buf):
            char = buf[i]
            if char == "\n":
                if buf[:i].strip():
                    # 行尾空白留給下一句：這一行若是全文最後一行，空白本來就會被 strip 掉。
                    return len(buf[:i].rstrip())
            elif char in _CJK_TERMINATORS or char in _LATIN_TERMINATORS:
                end = i + 1
                while end < len(buf) and buf[end] in _TAIL:
                    end += 1
                if end == len(buf) and not final:
                    # 下一個 token 可能是收尾的引號或「3.5」的 5，先等。
                    self._scan = i
                    return None
                if self._ends_sentence(buf, i, end):
                    return end
                i = end
                continue
            i += 1
        self._scan = i
        return None

    def _ends_sentence(self, buf: str, start: int, end: int) -> bool:
        if not buf[:start].strip():
            return False
        if any(char in _CJK_TERMINATORS for char in buf[start:end]):
            return True
        following = buf[end] if end < len(buf) else ""
        if following and not following.isspace():
            # 半形 ?! 直接接中文（「真的嗎?我…」）也是句尾；句點不算，免得切開 3.5、網址。
            return buf[start] in "!?" and _is_cjk(following)
        if buf[start] != ".":
            return True
        sentence = buf[:start].strip()
        last_line = sentence.rsplit("\n", 1)[-1].strip()
        if _LIST_MARKER.fullmatch(last_line):
            return False
        word = _WORD_BEFORE_DOT.search(sentence)
        if word is not None:
            token = word.group(1).lower()
            if token in _ABBREVIATIONS or len(token) == 1:
                return False
        return True


def split_sentences(text: str) -> list[str]:
    """All sentences of a finished text; they join back to ``text.strip()``."""
    splitter = SentenceSplitter()
    return splitter.feed(text) + splitter.flush()


# 模型偶爾把工具呼叫寫成純文字（search_knowledge(...)），agent loop 會丟掉重來。
# 開頭像識別字就先不送，確定不是呼叫再放行；像呼叫就整個回合都不送，交給 finish。
_MAYBE_CALL = re.compile(r"[A-Za-z_]\w*\s*", re.ASCII)
_LOOKS_LIKE_CALL = re.compile(r"[A-Za-z_]\w*\s*\(", re.ASCII)


class ReplyStream:
    """Sentence sink for one chat turn; *emit* receives ``(index, text)``.

    Every streamed LLM attempt (each round and each fallback hop) calls
    :meth:`attempt_started`, so only the attempt that becomes the answer counts
    toward the reply. Methods are never called concurrently: the generation thread
    feeds it, then the route calls :meth:`finish` after that thread is done.
    """

    def __init__(self, emit: Callable[[int, str], None]) -> None:
        self._emit = emit
        self._next_index = 0
        self.attempt_started()

    def attempt_started(self) -> None:
        self._splitter = SentenceSplitter()
        self._attempt_text = ""
        self._attempt_sent: list[str] = []
        self._released = False
        self._held_for_call = False

    def text_delta(self, delta: str) -> None:
        if not delta:
            return
        self._attempt_text += delta
        if self._released:
            self._send(self._splitter.feed(delta))
            return
        if self._held_for_call:
            return
        head = self._attempt_text.lstrip()
        if not head or _MAYBE_CALL.fullmatch(head):
            return
        if _LOOKS_LIKE_CALL.match(head):
            self._held_for_call = True
            return
        self._released = True
        self._send(self._splitter.feed(self._attempt_text))

    def finish(self, reply: str) -> None:
        """Send the part of *reply* not yet sent, so the answer's sentences join to it."""
        sent = "".join(self._attempt_sent)
        if sent and not reply.startswith(sent):
            # 送出的句子不是最後答案的開頭（例如 provider 在同一回合先寫字再叫工具，
            # 或串流到一半換站）：那幾句收不回來，把答案整段補送。
            logger.warning(
                "streamed sentences are not a prefix of the final reply; resending it whole",
            )
            sent = ""
        splitter = SentenceSplitter(strip_leading=not sent)
        self._send(splitter.feed(reply[len(sent):]) + splitter.flush())
        self.attempt_started()

    def _send(self, sentences: list[str]) -> None:
        for text in sentences:
            self._attempt_sent.append(text)
            index = self._next_index
            self._next_index += 1
            self._emit(index, text)
