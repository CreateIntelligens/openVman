"""Gemini Live transcript persistence for user speech and model replies."""

from __future__ import annotations

import asyncio
import logging
import time
from typing import Any

from memory.language_detect import DEFAULT_LANGUAGE, detect_language


# 沿用 session 的 logger 名稱，拆檔前後的日誌路由與篩選不變。
logger = logging.getLogger("brain.live.gemini_live")


class GeminiLiveTranscriptMixin:
    """Transcript and history behavior of ``GeminiLiveSession``."""

    async def _handle_input_transcription(self, input_transcription: dict[str, Any]) -> None:
        text = str(input_transcription.get("text", "")).strip()
        if not text:
            return
        # 視覺脈絡由 routes_vision ephemeral 路徑注入，不是真實語音，不存歷史
        if text.startswith("[視覺事件]"):
            return

        logger.info("Gemini Live user transcription (session %s): %s", self.session_id, text)
        # 語音輸入也要記成本回合的使用者發言，否則 turn 歸檔會少掉問句。
        self._last_user_message = text
        self._cancel_turn_decision()
        self._turn_revision += 1
        revision = self._turn_revision
        self._turn_decision = None
        self._prefetched_reads = {}
        self._prefetched_queries = {}
        utterance = bytes(self._utterance_pcm)
        self._utterance_pcm.clear()
        from knowledge.kb_settings import primary_language

        input_language = detect_language(text, primary_language(self.project_id))
        message_id = await self._save_input_transcription(text, input_language)
        await self._emit_user_transcription(text)
        # 中英西看 Live 的轉錄文字就分得出來；只有轉成中文字的句子才可能是台語，
        # 這種才送去聽。英西不送，也避開判斷模型把西語聽成華語的誤判。
        if (
            self._audio_language_id
            and utterance
            and message_id
            and detect_language(text) == DEFAULT_LANGUAGE
        ):
            task = asyncio.create_task(self._classify_utterance(utterance, message_id))
            self._background_tasks.add(task)
            task.add_done_callback(self._background_tasks.discard)
            self._utterance_language = task
        else:
            self._utterance_language = None
        task = asyncio.create_task(self._update_live_turn_decision(text, revision))
        self._turn_decision_task = task
        self._background_tasks.add(task)
        task.add_done_callback(self._background_tasks.discard)

    async def _save_input_transcription(
        self, text: str, input_language: str | None = None,
    ) -> int | None:
        try:
            if self._audio_language_id:
                from memory.memory import append_session_message_with_id

                _, message_id = await asyncio.to_thread(
                    append_session_message_with_id,
                    self.session_id,
                    self.persona_id,
                    "user",
                    text,
                    project_id=self.project_id,
                    language=input_language,
                )
                return message_id
            from memory.memory import append_session_message

            await asyncio.to_thread(
                append_session_message,
                self.session_id,
                self.persona_id,
                "user",
                text,
                project_id=self.project_id,
                language=input_language,
            )
        except Exception as exc:
            logger.error("Failed to save user speech in Gemini Live: %s", exc)
        return None

    async def _flush_assistant_turn(self) -> None:
        """Persist the accumulated reply, mirroring the text-mode turn archive.

        Live 模式只存過使用者發言，模型回覆串完就丟，切回文字模式時整段歷史
        看起來全是 user，模型會判定沒有脈絡。這裡補上 assistant 那一半。
        """
        full_text = "".join(self._assistant_text_buf).strip()
        self._assistant_text_buf = []
        if not full_text:
            return

        try:
            from memory.memory import append_session_message

            await asyncio.to_thread(
                append_session_message,
                self.session_id,
                self.persona_id,
                "assistant",
                full_text,
                project_id=self.project_id,
            )
        except Exception as exc:
            logger.error("Failed to save assistant reply in Gemini Live: %s", exc)
            return

        user_text = self._last_user_message.strip()
        self._last_user_message = ""
        if not user_text:
            return
        try:
            from memory.memory import archive_session_turn

            await asyncio.to_thread(
                archive_session_turn,
                session_id=self.session_id,
                user_message=user_text,
                assistant_message=full_text,
                persona_id=self.persona_id,
                project_id=self.project_id,
            )
        except Exception as exc:
            logger.error("Failed to archive session turn in Gemini Live: %s", exc)

    async def _emit_user_transcription(self, text: str) -> None:
        await self._emit(
            {
                "event": "user_transcription",
                **({"decision_turn_id": f"live:{self.relay_session_id}:{self._turn_revision}"} if self.decision_debug_enabled else {}),
                "text": text,
                "session_id": self.relay_session_id,
                "timestamp": int(time.time() * 1000),
            }
        )
