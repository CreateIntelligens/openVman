"""Gemini Live audio handling: utterance buffering, language and metering."""

from __future__ import annotations

import asyncio
import base64
import json
import logging
from typing import Any

from memory.language_detect import (
    DEFAULT_LANGUAGE,
    TAIWANESE,
    detect_audio_language,
    detect_language,
)

from .gemini_context import LiveSessionContext
from .gemini_payloads import parse_sample_rate, pcm_to_wav


# 沿用 session 的 logger 名稱，拆檔前後的日誌路由與篩選不變。
logger = logging.getLogger("brain.live.gemini_live")


class GeminiLiveAudio:
    """Owns audio state: the current utterance, its language verdict and metered seconds."""

    # 太長的句子只留最後這麼多秒；判斷語言不需要整段，也避免暫存無限長。
    _UTTERANCE_MAX_SECONDS = 20
    # Live 常在轉錄一到就呼叫 search_knowledge，聽台語那次還沒回來；最多等這麼久。
    _LANGUAGE_WAIT_SECONDS = 3.0

    def __init__(self, context: LiveSessionContext, *, audio_language_id: bool) -> None:
        self._context = context
        # 知識庫有台語文件才有台語分流；這時每句語音暫存起來，轉錄到了拿去聽是不是
        # 台語（見 _classify_utterance）。沒有台語分流就不多花這次呼叫。
        self._audio_language_id = audio_language_id
        self._utterance_language: asyncio.Future[str | None] | None = None
        self._utterance_pcm = bytearray()
        self._utterance_rate = 16000
        # Live 按音訊秒數計價，不是 token。逐 turn 累積、turnComplete 時記帳。
        self._input_audio_seconds = 0.0
        self._output_audio_seconds = 0.0
        self._usage_tasks: set[asyncio.Task] = set()
        self._chunk_counter = 0
        self._background_tasks: set[asyncio.Task] = set()

    def track_input(self, audio_b64: str, mime_type: str) -> None:
        # 上行音訊同樣要計量；16-bit mono PCM，秒數 = bytes / (2 * rate)。
        try:
            pcm = base64.b64decode(audio_b64)
            rate = parse_sample_rate(mime_type)
            self._input_audio_seconds += len(pcm) / (2 * rate)
            if self._audio_language_id:
                self._buffer_utterance(pcm, rate)
        except Exception:  # noqa: BLE001 - 計量失敗不該擋住音訊送出
            pass

    def bind_turn_language(self, speech_language: str | None) -> None:
        # 語言判定綁定回合：先清掉前一句（可能是台語）的判定，再套這一句自己的。
        # 前台 ASR 聽出台語時帶 speech_language，這一輪 search_knowledge 照它查台語文件。
        self._utterance_language = None
        if speech_language == TAIWANESE:
            verdict = asyncio.get_running_loop().create_future()
            verdict.set_result(TAIWANESE)
            self._utterance_language = verdict

    def take_utterance(self) -> bytes:
        utterance = bytes(self._utterance_pcm)
        self._utterance_pcm.clear()
        return utterance

    def classify_in_background(self, text: str, utterance: bytes, message_id: int | None) -> None:
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
            from core.usage import usage_scope

            credential = (
                self._context.gemini_credential()
                if self._context.gemini_credential else None
            )
            kwargs: dict[str, Any] = (
                {"credential": credential} if credential is not None else {}
            )
            context = self._context
            with usage_scope(
                kind="audio_language", project_id=context.project_id,
                user_id=context.user_id, role=context.role,
                principal_type=context.principal_type, principal_id=context.principal_id,
                session_id=context.session_id, persona_id=context.persona_id,
                channel="live",
            ):
                language = await asyncio.to_thread(
                    detect_audio_language, pcm_to_wav(pcm, self._utterance_rate), **kwargs,
                )
            if language == TAIWANESE:
                from memory.memory import update_session_message_language

                await asyncio.to_thread(
                    update_session_message_language, message_id, language,
                    self._context.project_id,
                )
            logger.info(json.dumps({
                "event": "live_audio_language",
                "session_id": self._context.session_id,
                "project_id": self._context.project_id,
                "language": language,
                "seconds": round(len(pcm) / (2 * self._utterance_rate), 1),
            }))
            return language
        except Exception as exc:  # noqa: BLE001
            logger.warning(json.dumps({
                "event": "live_audio_language_failed", "error_type": type(exc).__name__,
            }))
            return None

    async def language_for_search(self) -> str | None:
        task = self._utterance_language
        if task is None:
            return None
        try:
            return await asyncio.wait_for(asyncio.shield(task), self._LANGUAGE_WAIT_SECONDS)
        except (asyncio.TimeoutError, Exception):  # noqa: BLE001 - 等不到就當中文查
            return None

    async def record_usage(self) -> None:
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
        task = asyncio.create_task(self._persist_usage(pending))
        self._usage_tasks.add(task)
        task.add_done_callback(self._usage_tasks.discard)
        await asyncio.shield(task)

    async def close(self) -> None:
        # Cancelling the listener must not cancel an in-progress ledger write.
        if self._usage_tasks:
            await asyncio.gather(*tuple(self._usage_tasks))
        await self.record_usage()

    async def _persist_usage(
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
                    model=self._context.config.live_gemini_model,
                    usage=None,
                    kind="live",
                    scope=self._usage_scope(),
                    unit_type=UNIT_SECONDS,
                    units=seconds,
                    raw={"direction": direction, **self._credential_metadata()},
                )
            except Exception as exc:
                logger.warning("Gemini Live usage ledger write failed: %s", exc)

    def _credential_metadata(self) -> dict[str, str]:
        getter = self._context.gemini_credential
        credential = getter() if getter is not None else None
        return credential.metadata() if credential is not None else {}

    def _usage_scope(self):
        from core.usage import UsageScope

        context = self._context
        return UsageScope(
            kind="live",
            user_id=context.user_id,
            role=context.role,
            principal_type=context.principal_type,
            principal_id=context.principal_id,
            project_id=context.project_id,
            session_id=context.session_id,
            persona_id=context.persona_id,
            channel="live",
        )

    def next_chunk_id(self) -> str:
        self._chunk_counter += 1
        return f"gemini-live-{self._context.relay_session_id}-{self._chunk_counter}"

    def output_events(
        self, server_content: dict[str, Any], text: str,
    ) -> list[dict[str, Any]]:
        """Turn one serverContent's audio parts into stream chunks carrying its text."""
        model_turn = server_content.get("modelTurn") or {}
        parts = model_turn.get("parts") or []
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

            events.append(
                {
                    "event": "server_stream_chunk",
                    "chunk_id": self.next_chunk_id(),
                    "session_id": self._context.relay_session_id,
                    "text": text,
                    "audio_base64": base64.b64encode(audio_bytes).decode("ascii"),
                    "is_final": False,
                }
            )

        if events and server_content.get("turnComplete"):
            events[-1]["is_final"] = True

        return events
