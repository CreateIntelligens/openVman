"""Gemini Live transcript persistence for user speech and model replies."""

from __future__ import annotations

import asyncio
import logging
import time
from typing import Any

from memory.language_detect import detect_language

from .gemini_context import LiveSessionContext


# 沿用 session 的 logger 名稱，拆檔前後的日誌路由與篩選不變。
logger = logging.getLogger("brain.live.gemini_live")


class GeminiLiveTranscripts:
    """Owns the reply being streamed and writes both halves of a turn to history."""

    def __init__(self, context: LiveSessionContext, *, audio_language_id: bool) -> None:
        self._context = context
        # 有台語分流時要拿到訊息 id，聽完音訊才能回頭改這則訊息的語言。
        self._audio_language_id = audio_language_id
        # 一個 turn 的回覆會拆成多個 chunk 送來，累積到 turnComplete 才寫入歷史。
        self._assistant_text_buf: list[str] = []

    def add_reply_text(self, text: str) -> None:
        # 每則 serverContent 只累積一次；同一則裡的多個音訊 part 共用同一段文字。
        if text:
            self._assistant_text_buf.append(text)

    async def save_user_speech(self, text: str) -> int | None:
        from knowledge.kb_settings import primary_language

        input_language = detect_language(text, primary_language(self._context.project_id))
        return await self._save_input_transcription(text, input_language)

    async def _save_input_transcription(
        self, text: str, input_language: str | None = None,
    ) -> int | None:
        context = self._context
        try:
            if self._audio_language_id:
                from memory.memory import append_session_message_with_id

                _, message_id = await asyncio.to_thread(
                    append_session_message_with_id,
                    context.session_id,
                    context.persona_id,
                    "user",
                    text,
                    project_id=context.project_id,
                    language=input_language,
                )
                return message_id
            from memory.memory import append_session_message

            await asyncio.to_thread(
                append_session_message,
                context.session_id,
                context.persona_id,
                "user",
                text,
                project_id=context.project_id,
                language=input_language,
            )
        except Exception as exc:
            logger.error("Failed to save user speech in Gemini Live: %s", exc)
        return None

    async def save_assistant_reply(self) -> str | None:
        """Persist the accumulated reply; return it when saved so the turn can be archived.

        Live 模式只存過使用者發言，模型回覆串完就丟，切回文字模式時整段歷史
        看起來全是 user，模型會判定沒有脈絡。這裡補上 assistant 那一半。
        """
        full_text = "".join(self._assistant_text_buf).strip()
        self._assistant_text_buf = []
        if not full_text:
            return None

        try:
            from memory.memory import append_session_message

            await asyncio.to_thread(
                append_session_message,
                self._context.session_id,
                self._context.persona_id,
                "assistant",
                full_text,
                project_id=self._context.project_id,
            )
        except Exception as exc:
            logger.error("Failed to save assistant reply in Gemini Live: %s", exc)
            return None
        return full_text

    async def archive_turn(self, user_text: str, assistant_text: str) -> None:
        try:
            from memory.memory import archive_session_turn

            await asyncio.to_thread(
                archive_session_turn,
                session_id=self._context.session_id,
                user_message=user_text,
                assistant_message=assistant_text,
                persona_id=self._context.persona_id,
                project_id=self._context.project_id,
            )
        except Exception as exc:
            logger.error("Failed to archive session turn in Gemini Live: %s", exc)

    async def emit_user_transcription(self, text: str, decision_turn_id: str | None) -> None:
        await self._context.emit(
            {
                "event": "user_transcription",
                **({"decision_turn_id": decision_turn_id} if decision_turn_id is not None else {}),
                "text": text,
                "session_id": self._context.relay_session_id,
                "timestamp": int(time.time() * 1000),
            }
        )


def reply_text(server_content: dict[str, Any]) -> str:
    """The model's reply text in one serverContent, from its parts or output transcription."""
    model_turn = server_content.get("modelTurn") or {}
    parts = model_turn.get("parts") or []
    text_parts = [
        part.get("text", "")
        for part in parts
        if isinstance(part, dict) and isinstance(part.get("text"), str)
    ]
    # 轉錄是逐段送的，英西的字間空格落在段落頭尾；strip 會把字黏在一起。
    joined = "".join(text_parts)
    if joined.strip():
        return joined
    transcription = server_content.get("outputTranscription") or {}
    text = transcription.get("text", "")
    return text if isinstance(text, str) and text.strip() else ""
