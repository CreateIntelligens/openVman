"""Gemini Live audio handling: utterance buffering, language and metering."""

from __future__ import annotations

import asyncio
import base64
import json
import logging
from typing import Any

from memory.language_detect import TAIWANESE, detect_audio_language

from .gemini_payloads import parse_sample_rate, pcm_to_wav


# 沿用 session 的 logger 名稱，拆檔前後的日誌路由與篩選不變。
logger = logging.getLogger("brain.live.gemini_live")


class GeminiLiveAudioMixin:
    """Audio-side behavior of ``GeminiLiveSession``; uses the session's state."""

    # 太長的句子只留最後這麼多秒；判斷語言不需要整段，也避免暫存無限長。
    _UTTERANCE_MAX_SECONDS = 20

    def _buffer_utterance(self, pcm: bytes, rate: int) -> None:
        if rate != self._utterance_rate:
            self._utterance_pcm.clear()
            self._utterance_rate = rate
        self._utterance_pcm.extend(pcm)
        overflow = len(self._utterance_pcm) - self._UTTERANCE_MAX_SECONDS * 2 * rate
        if overflow > 0:
            del self._utterance_pcm[:overflow]

    async def _classify_utterance(self, pcm: bytes, message_id: int) -> str | None:
        """Mark a Chinese-looking utterance as Taiwanese if the audio says so.

        只寫訊息語言、不影響回答；判斷不是台語或失敗就保留文字判斷的結果。
        """
        try:
            language = await asyncio.to_thread(
                detect_audio_language, pcm_to_wav(pcm, self._utterance_rate),
            )
            if language == TAIWANESE:
                from memory.memory import update_session_message_language

                await asyncio.to_thread(
                    update_session_message_language, message_id, language, self.project_id,
                )
            logger.info(json.dumps({
                "event": "live_audio_language",
                "session_id": self.session_id,
                "project_id": self.project_id,
                "language": language,
                "seconds": round(len(pcm) / (2 * self._utterance_rate), 1),
            }))
            return language
        except Exception as exc:  # noqa: BLE001
            logger.warning(json.dumps({
                "event": "live_audio_language_failed", "error_type": type(exc).__name__,
            }))
            return None

    # Live 常在轉錄一到就呼叫 search_knowledge，聽台語那次還沒回來；最多等這麼久。
    _LANGUAGE_WAIT_SECONDS = 3.0

    async def _utterance_language_for_search(self) -> str | None:
        task = self._utterance_language
        if task is None:
            return None
        try:
            return await asyncio.wait_for(asyncio.shield(task), self._LANGUAGE_WAIT_SECONDS)
        except (asyncio.TimeoutError, Exception):  # noqa: BLE001 - 等不到就當中文查
            return None

    async def _record_audio_usage(self) -> None:
        """Meter the audio exchanged this turn, in seconds.

        Live 不是 token 計價，所以走 (unit_type, units)。輸入與輸出分兩筆，
        因為兩者費率不同，合併記就沒辦法還原成本。
        """
        pending = (
            ("input", self._input_audio_seconds),
            ("output", self._output_audio_seconds),
        )
        self._input_audio_seconds = 0.0
        self._output_audio_seconds = 0.0
        if not any(seconds > 0 for _, seconds in pending):
            return
        task = asyncio.create_task(self._persist_audio_usage(pending))
        self._usage_tasks.add(task)
        task.add_done_callback(self._usage_tasks.discard)
        await asyncio.shield(task)

    async def _persist_audio_usage(
        self, pending: tuple[tuple[str, float], ...],
    ) -> None:
        for direction, seconds in pending:
            if seconds <= 0:
                continue
            try:
                from infra.usage_ledger import UNIT_SECONDS, record_usage_event

                await asyncio.to_thread(
                    record_usage_event,
                    provider="gemini",
                    model=self.config.live_gemini_model,
                    usage=None,
                    kind="live",
                    scope=self._usage_scope(),
                    unit_type=UNIT_SECONDS,
                    units=seconds,
                    raw={"direction": direction},
                )
            except Exception as exc:
                logger.warning("Gemini Live usage ledger write failed: %s", exc)

    def _usage_scope(self):
        from core.usage import UsageScope

        return UsageScope(
            kind="live",
            user_id=self.user_id,
            role=self.role,
            principal_type=self.principal_type,
            principal_id=self.principal_id,
            project_id=self.project_id,
            session_id=self.session_id,
            persona_id=self.persona_id,
            channel="live",
        )

    def _events_from_server_content(self, server_content: dict[str, Any]) -> list[dict[str, Any]]:
        model_turn = server_content.get("modelTurn") or {}
        parts = model_turn.get("parts") or []
        text = self._extract_text(parts, server_content)
        # 每則 serverContent 只累積一次；同一則裡的多個音訊 part 共用同一段文字。
        if text:
            self._assistant_text_buf.append(text)
        events: list[dict[str, Any]] = []

        for part in parts:
            inline = part.get("inlineData")
            if not isinstance(inline, dict):
                continue
            encoded_audio = inline.get("data")
            if not encoded_audio:
                continue

            audio_bytes = base64.b64decode(encoded_audio)
            mime_type = str(inline.get("mimeType", ""))
            if mime_type.startswith("audio/pcm"):
                # 16-bit mono，所以秒數 = bytes / (2 * rate)。要在轉成 WAV
                # 之前算，否則 44 bytes 的檔頭會被算進音訊長度。
                self._output_audio_seconds += len(audio_bytes) / (
                    2 * parse_sample_rate(mime_type)
                )
                audio_bytes = pcm_to_wav(audio_bytes, parse_sample_rate(mime_type))

            self._chunk_counter += 1
            events.append(
                {
                    "event": "server_stream_chunk",
                    "chunk_id": f"gemini-live-{self.relay_session_id}-{self._chunk_counter}",
                    "session_id": self.relay_session_id,
                    "text": text,
                    "audio_base64": base64.b64encode(audio_bytes).decode("ascii"),
                    "is_final": False,
                }
            )

        if events and server_content.get("turnComplete"):
            events[-1]["is_final"] = True

        return events

    def _extract_text(self, parts: list[dict[str, Any]], server_content: dict[str, Any]) -> str:
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
