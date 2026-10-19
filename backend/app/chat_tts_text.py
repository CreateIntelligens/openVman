"""Add ``tts_text`` — the spoken form of a reply — to chat responses.

整合方拿 ``reply`` 自己接 TTS 時，會把 markdown、emoji、「0800-123-456」
照字面念出來。Backend 的 ``/tts/stream`` 內部本來就會先把文字整理成念的
版本，這裡把同一份結果放進 ``/chat`` 的回應與 ``/chat/stream`` 的事件，
呼叫端不必自己再做一次。只做本地正規化（不打 normalize API），逐句串流
才不會每句多一次往返；保留繁體，數字與電話轉成讀法。
"""

from __future__ import annotations

import json
import re
from collections.abc import AsyncIterator
from typing import Any

from app.tts_text import prepare_tts_text

#: Paths (relative to the Brain prefix) whose JSON replies get ``tts_text``.
TTS_TEXT_PATHS = frozenset({"chat", "chat/accept"})
TTS_TEXT_STREAM_PATHS = frozenset({"chat/stream"})
#: SSE events that carry text to speak: ``sentence`` has ``text``, ``done`` has ``reply``.
_EVENT_TEXT_FIELD = {"sentence": "text", "done": "reply"}
_CJK = re.compile(r"[㐀-鿿]")


def spoken_form(text: str) -> str:
    """Markdown and emoji stripped; digits verbalized when the text is Chinese."""
    language = "zh" if _CJK.search(text) else "en"
    return prepare_tts_text(text, language=language, simplified=False, normalize_url="") or ""


def annotate_payload(payload: Any, field: str = "reply") -> Any:
    """Return ``payload`` with ``tts_text`` added when it carries ``field``."""
    if not isinstance(payload, dict):
        return payload
    value = payload.get(field)
    if isinstance(value, str):
        payload["tts_text"] = spoken_form(value)
    return payload


def annotate_json_body(content: bytes) -> bytes:
    """Non-streaming reply: add ``tts_text`` or return the bytes untouched."""
    try:
        payload = json.loads(content)
    except ValueError:
        return content
    if not isinstance(payload, dict) or "reply" not in payload:
        return content
    return json.dumps(annotate_payload(payload), ensure_ascii=False).encode("utf-8")


def _annotate_event(block: bytes) -> bytes:
    """One SSE event block (without the trailing blank line)."""
    event = ""
    data_lines: list[bytes] = []
    other: list[bytes] = []
    for line in block.split(b"\n"):
        if line.startswith(b"event:"):
            event = line[6:].strip().decode("utf-8", errors="ignore")
        elif line.startswith(b"data:"):
            data_lines.append(line[5:].lstrip(b" "))
        else:
            other.append(line)
    field = _EVENT_TEXT_FIELD.get(event)
    if field is None or not data_lines:
        return block
    try:
        payload = json.loads(b"\n".join(data_lines))
    except ValueError:
        return block
    if not isinstance(payload, dict) or not isinstance(payload.get(field), str):
        return block
    annotate_payload(payload, field)
    data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    lines = [line for line in other if line] + [f"event: {event}".encode(), b"data: " + data]
    return b"\n".join(lines)


async def annotate_sse(stream: AsyncIterator[bytes]) -> AsyncIterator[bytes]:
    """Forward SSE chunks as they come, adding ``tts_text`` to sentence/done events.

    每個事件以空行結尾；只在收齊一個事件時改寫它，不會為了整段回應而延後轉發。
    """
    buffer = b""
    async for chunk in stream:
        buffer += chunk
        while True:
            end = buffer.find(b"\n\n")
            if end < 0:
                break
            block, buffer = buffer[:end], buffer[end + 2:]
            yield _annotate_event(block) + b"\n\n"
    if buffer:
        yield buffer
