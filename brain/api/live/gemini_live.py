"""Brain-owned Gemini Live session manager."""

from __future__ import annotations

import asyncio
import base64
import json
import logging
import random
import re
import time
from typing import Any, Awaitable, Callable, Protocol

import websockets

from config import BrainSettings, get_settings
from memory.embedder import encode_query_with_fallback
from memory.language_detect import (
    DEFAULT_LANGUAGE,
    TAIWANESE,
    detect_audio_language,
    detect_language,
    project_has_taiwanese_route,
)
from memory.retrieval import search_records
from .gemini_tools import build_gemini_tool_declarations


logger = logging.getLogger("brain.live.gemini_live")

_GEMINI_LIVE_WS_URL = (
    "wss://generativelanguage.googleapis.com/ws/"
    "google.ai.generativelanguage.v1beta.GenerativeService.BidiGenerateContent"
)
_PCM_RATE_RE = re.compile(r"rate=(\d+)")
_RECONNECT_DELAYS = (1, 2, 4, 8, 16)
_KEEPALIVE_INTERVAL_SECONDS = 600
_SETUP_COMPLETE_TIMEOUT_SECONDS = 10

EventSink = Callable[[dict[str, Any]], Awaitable[None]]


def _supports_thinking_level(model: str) -> bool:
    """Whether a Live model accepts generationConfig.thinkingConfig.

    3.8 起 thinkingLevel 只留在 extended-thinking 變體；一般的 gemini-3.8-live
    收到這個欄位會直接報錯。3.1 preview 兩者都吃。
    """
    name = model.strip().removeprefix("models/")
    if name.startswith("gemini-3.1-"):
        return True
    return "extended-thinking" in name


class JsonTransport(Protocol):
    async def connect(self) -> None: ...

    async def send_json(self, payload: dict[str, Any]) -> None: ...

    async def recv_json(self) -> dict[str, Any] | None: ...

    async def ping(self) -> None: ...

    async def close(self) -> None: ...


class GeminiLiveWebSocketTransport:
    """Minimal JSON transport for Gemini Live's raw websocket API."""

    def __init__(self, config: BrainSettings) -> None:
        self._config = config
        self._ws: Any | None = None

    async def connect(self) -> None:
        if not self._config.gemini_api_key:
            raise RuntimeError("GEMINI_API_KEY is not configured")
        self._ws = await websockets.connect(
            _GEMINI_LIVE_WS_URL,
            additional_headers={"x-goog-api-key": self._config.gemini_api_key},
            open_timeout=10,
            max_size=4 * 1024 * 1024,
        )

    async def send_json(self, payload: dict[str, Any]) -> None:
        if self._ws is None:
            raise RuntimeError("Gemini Live transport is not connected")
        await self._ws.send(json.dumps(payload))

    async def recv_json(self) -> dict[str, Any] | None:
        if self._ws is None:
            raise RuntimeError("Gemini Live transport is not connected")
        try:
            message = await self._ws.recv()
        except websockets.ConnectionClosedOK:
            return None
        except websockets.ConnectionClosedError as exc:
            raise RuntimeError(f"Gemini Live websocket closed: {exc}") from exc
        if isinstance(message, bytes):
            message = message.decode("utf-8")
        return json.loads(message)

    async def ping(self) -> None:
        if self._ws is None:
            raise RuntimeError("Gemini Live transport is not connected")
        pong = await self._ws.ping()
        await pong

    async def close(self) -> None:
        if self._ws is not None:
            await self._ws.close()
            self._ws = None


class GeminiLiveSession:
    """Persistent Gemini Live transport owned by the Brain service."""

    def __init__(
        self,
        *,
        relay_session_id: str,
        client_id: str,
        persona_id: str = "default",
        project_id: str = "default",
        session_id: str = "",
        user_id: str = "",
        role: str = "",
        principal_type: str = "",
        principal_id: str = "",
        system_instruction: str = "",
        config: BrainSettings | None = None,
        transport_factory: Any | None = None,
        event_sink: EventSink | None = None,
    ) -> None:
        self.relay_session_id = relay_session_id
        self.client_id = client_id
        self.persona_id = persona_id
        self.project_id = project_id
        self.session_id = session_id or relay_session_id
        self.user_id = user_id
        self.role = role
        self.principal_type = principal_type
        self.principal_id = principal_id
        self._system_instruction = system_instruction
        self.config = config or get_settings()
        self._transport_factory = transport_factory or (lambda cfg: GeminiLiveWebSocketTransport(cfg))
        self._event_sink = event_sink
        self._transport: JsonTransport | None = None
        self._listener_task: asyncio.Task | None = None
        self._keepalive_task: asyncio.Task | None = None
        self._closed = False
        self._last_user_message: str = ""
        # 一個 turn 的回覆會拆成多個 chunk 送來，累積到 turnComplete 才寫入歷史。
        self._assistant_text_buf: list[str] = []
        # Live 按音訊秒數計價，不是 token。逐 turn 累積、turnComplete 時記帳。
        self._input_audio_seconds = 0.0
        self._output_audio_seconds = 0.0
        self._usage_tasks: set[asyncio.Task] = set()
        self._chunk_counter = 0
        self._response_in_progress = False
        self._reconnecting = False
        self._unavailable = False
        self._connect_lock = asyncio.Lock()
        # 知識庫有台語文件才有台語分流；這時每句語音暫存起來，轉錄到了拿去聽是不是
        # 台語（見 _classify_utterance）。沒有台語分流就不多花這次呼叫。
        try:
            self._audio_language_id = project_has_taiwanese_route(project_id)
        except Exception:  # noqa: BLE001 - 讀不到文件設定就當沒有台語分流
            self._audio_language_id = False
        self._utterance_language: asyncio.Task | None = None
        self._utterance_pcm = bytearray()
        self._utterance_rate = 16000
        self._background_tasks: set[asyncio.Task] = set()

    async def ensure_connected(self) -> JsonTransport:
        # 回傳這次拿到的連線；呼叫端在 await 之後再讀 self._transport 可能已被
        # 重連流程清成 None。
        if self._transport is not None:
            return self._transport
        if self._unavailable:
            raise RuntimeError("Gemini Live transport is unavailable")

        async with self._connect_lock:
            if self._transport is not None:
                return self._transport
            if self._unavailable:
                raise RuntimeError("Gemini Live transport is unavailable")

            transport = self._transport_factory(self.config)
            await transport.connect()
            await transport.send_json({"setup": self._build_setup_message()})
            await self._wait_for_setup_complete(transport)
            self._transport = transport

            if self._event_sink is not None and self._listener_task is None:
                self._listener_task = asyncio.create_task(self._listen())
            if self._keepalive_task is None:
                self._keepalive_task = asyncio.create_task(self._keepalive_loop())
            return transport

    async def send_text_turn(self, user_text: str, speech_language: str | None = None) -> None:
        transport = await self.ensure_connected()
        self._response_in_progress = True
        if user_text:
            self._last_user_message = user_text
            # 語言判定綁定回合：先清掉前一句（可能是台語）的判定，再套這一句自己的。
            # 前台 ASR 聽出台語時帶 speech_language，這一輪 search_knowledge 照它查台語文件。
            self._utterance_language = None
            if speech_language == TAIWANESE:
                verdict = asyncio.get_running_loop().create_future()
                verdict.set_result(TAIWANESE)
                self._utterance_language = verdict
        await transport.send_json(self._build_user_turn_message(user_text))

    async def send_realtime_input(self, audio_b64: str, mime_type: str) -> None:
        if self._reconnecting or self._unavailable:
            logger.debug("dropping audio chunk while Gemini Live transport is unavailable")
            return
        transport = await self.ensure_connected()
        # 上行音訊同樣要計量；16-bit mono PCM，秒數 = bytes / (2 * rate)。
        try:
            pcm = base64.b64decode(audio_b64)
            rate = _parse_sample_rate(mime_type)
            self._input_audio_seconds += len(pcm) / (2 * rate)
            if self._audio_language_id:
                self._buffer_utterance(pcm, rate)
        except Exception:  # noqa: BLE001 - 計量失敗不該擋住音訊送出
            pass
        await transport.send_json(
            {
                "realtimeInput": {
                    "audio": {
                        "mimeType": mime_type,
                        "data": audio_b64,
                    }
                }
            }
        )

    async def send_turn_complete(self) -> None:
        transport = await self.ensure_connected()
        self._response_in_progress = True
        await transport.send_json({"realtimeInput": {"audioStreamEnd": True}})

    async def request_stop(self) -> None:
        if not self._response_in_progress:
            return
        self._response_in_progress = False
        await self._emit(
            {
                "event": "server_stop_audio",
                "session_id": self.relay_session_id,
                "timestamp": int(time.time() * 1000),
                "reason": "user_interruption",
            }
        )

    async def close(self) -> None:
        self._closed = True
        if self._listener_task is not None:
            self._listener_task.cancel()
            try:
                await self._listener_task
            except asyncio.CancelledError:
                pass
            self._listener_task = None
        if self._keepalive_task is not None:
            self._keepalive_task.cancel()
            try:
                await self._keepalive_task
            except asyncio.CancelledError:
                pass
            self._keepalive_task = None
        try:
            if self._transport is not None:
                await self._transport.close()
                self._transport = None
        finally:
            # Cancelling the listener must not cancel an in-progress ledger write.
            if self._usage_tasks:
                await asyncio.gather(*tuple(self._usage_tasks))
            await self._record_audio_usage()

    async def _listen(self) -> None:
        transport: JsonTransport | None = None
        try:
            while self._transport is not None:
                transport = self._transport
                try:
                    message = await transport.recv_json()
                except asyncio.CancelledError:
                    raise
                except Exception as exc:
                    logger.warning("Gemini Live listener interrupted: %s", exc)
                    if await self._reconnect(str(exc)):
                        continue
                    break

                if message is None:
                    if await self._reconnect("Gemini Live websocket closed cleanly"):
                        continue
                    break

                # Gemini 把收音轉錄放在 serverContent 裡；只看頂層的話使用者講的話
                # 從來沒存進歷史（2026-09-23 抓原始訊息確認）。
                server_content = message.get("serverContent")
                input_transcription = message.get("inputTranscription")
                if not isinstance(input_transcription, dict) and isinstance(server_content, dict):
                    input_transcription = server_content.get("inputTranscription")
                if isinstance(input_transcription, dict):
                    await self._handle_input_transcription(input_transcription)

                tool_call = message.get("toolCall")
                if isinstance(tool_call, dict):
                    await self._handle_tool_call(tool_call)
                    continue

                if not isinstance(server_content, dict):
                    continue

                if server_content.get("interrupted"):
                    # 被打斷的回覆已經播出去一部分，使用者記得它，歷史也要留著。
                    await self._flush_assistant_turn()
                    await self._emit(
                        {
                            "event": "server_stop_audio",
                            "session_id": self.relay_session_id,
                            "timestamp": int(time.time() * 1000),
                            "reason": "provider_interruption",
                        }
                    )

                events = self._events_from_server_content(server_content)
                for event in events:
                    await self._emit(event)

                if server_content.get("turnComplete"):
                    self._response_in_progress = False
                    await self._flush_assistant_turn()
                    await self._record_audio_usage()
                    if not events or not events[-1].get("is_final"):
                        self._chunk_counter += 1
                        await self._emit(
                            {
                                "event": "server_stream_chunk",
                                "chunk_id": f"gemini-live-{self.relay_session_id}-{self._chunk_counter}",
                                "session_id": self.relay_session_id,
                                "text": "",
                                "audio_base64": "",
                                "is_final": True,
                            }
                        )
        except asyncio.CancelledError:
            raise
        finally:
            if self._listener_task is asyncio.current_task():
                self._listener_task = None
            if transport is not None and self._transport is transport:
                self._transport = None
                await transport.close()

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
        utterance = bytes(self._utterance_pcm)
        self._utterance_pcm.clear()
        message_id = await self._save_input_transcription(text)
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

    async def _save_input_transcription(self, text: str) -> int | None:
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
            )
        except Exception as exc:
            logger.error("Failed to save user speech in Gemini Live: %s", exc)
        return None

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
                detect_audio_language, _pcm_to_wav(pcm, self._utterance_rate),
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

    async def _emit_user_transcription(self, text: str) -> None:
        await self._emit(
            {
                "event": "user_transcription",
                "text": text,
                "session_id": self.relay_session_id,
                "timestamp": int(time.time() * 1000),
            }
        )

    async def _handle_tool_call(self, tool_call: dict[str, Any]) -> None:
        function_calls = tool_call.get("functionCalls") or []
        function_responses: list[dict[str, Any]] = []

        for function_call in function_calls:
            if not isinstance(function_call, dict):
                continue
            function_responses.append(await self._execute_function_call(function_call))

        if function_responses and self._transport is not None:
            await self._transport.send_json(
                {"toolResponse": {"functionResponses": function_responses}}
            )

    async def _execute_function_call(self, function_call: dict[str, Any]) -> dict[str, Any]:
        name = str(function_call.get("name", "")).strip()
        call_id = str(function_call.get("id", "")).strip()
        args = function_call.get("args") or {}
        if isinstance(args, str):
            args = json.loads(args)

        # Mapping of tool names to handlers
        # Some are async, some are sync (wrapped in to_thread if needed)
        tool_map = {
            "search_knowledge": lambda: self._search("knowledge", args),
            "search_memory": lambda: self._search("memories", args),
            "get_chat_history": lambda: asyncio.to_thread(self._get_chat_history, args),
            "save_memory": lambda: asyncio.to_thread(self._save_memory, args),
            "search_web": lambda: asyncio.to_thread(self._search_web, args),
            "read_web_page": lambda: asyncio.to_thread(self._read_web_page, args),
            "publish_wiki": lambda: asyncio.to_thread(self._publish_wiki, args),
        }

        try:
            if name == "search_web" and not getattr(self.config, "url2md_search_enabled", True):
                raise ValueError("search_web 已停用")
            if name == "read_web_page" and not getattr(self.config, "url2md_read_enabled", True):
                raise ValueError("read_web_page 已停用")
            if name == "publish_wiki" and not getattr(self.config, "wiki_publish_enabled", True):
                raise ValueError("publish_wiki 已停用")
            handler = tool_map.get(name)
            if not handler:
                raise ValueError(f"Unsupported Gemini Live tool: {name}")

            response = await handler()
        except Exception as exc:
            logger.warning("Gemini Live tool %s failed: %s", name, exc)
            response = {"error": str(exc)}

        if isinstance(response, dict) and response.get("citations"):
            await self._emit(
                {
                    "event": "server_search_results",
                    "session_id": self.relay_session_id,
                    "tool_name": name,
                    "queries": response.get("queries", []),
                    "citations": response.get("citations", []),
                    "timestamp": int(time.time() * 1000),
                }
            )

        return {"id": call_id, "name": name, "response": response}


    def _save_memory(self, args: dict[str, Any]) -> dict[str, Any]:
        from memory.embedder import encode_text
        from memory.memory import add_memory
        from tools.builtin.memory_tools import is_explicit_memory_request

        content = str(args.get("content", "")).strip()
        if not content:
            raise ValueError("content 不可為空")
        # 文字模式早有這道檢查，Live 以前沒有，模型想存就存。
        if not is_explicit_memory_request(self._last_user_message):
            raise ValueError("只有使用者明確要求記憶時才能寫入長期記憶")
        vector = encode_text(content)
        add_memory(
            text=content,
            vector=vector,
            source="agent",
            persona_id=self.persona_id,
            project_id=self.project_id,
        )
        return {"saved": True, "content": content}

    def _get_chat_history(self, args: dict[str, Any]) -> dict[str, Any]:
        from memory.memory import list_session_messages

        session_id = str(args.get("session_id", "")).strip()
        if not session_id:
            session_id = self.relay_session_id
        try:
            max_messages = max(1, min(int(args.get("max_messages", 20)), 50))
        except (ValueError, TypeError):
            max_messages = 20
        messages = list_session_messages(session_id, project_id=self.project_id)
        recent = messages[-max_messages:]
        return {"session_id": session_id, "messages": recent}

    @staticmethod
    def _search_web(args: dict[str, Any]) -> dict[str, Any]:
        from tools.builtin.web_tools import _search_web

        return _search_web(args)

    @staticmethod
    def _read_web_page(args: dict[str, Any]) -> dict[str, Any]:
        from tools.builtin.web_tools import _read_web_page

        return _read_web_page(args)

    @staticmethod
    def _publish_wiki(args: dict[str, Any]) -> dict[str, Any]:
        from tools.builtin.wiki_tools import _publish_wiki

        return _publish_wiki(args)

    async def _search(self, table: str, args: dict[str, Any]) -> dict[str, Any]:
        heard = await self._utterance_language_for_search() if table == "knowledge" else None
        return await asyncio.to_thread(self._search_sync, table, args, heard)

    def _search_sync(
        self, table: str, args: dict[str, Any], heard_language: str | None = None,
    ) -> dict[str, Any]:
        from tools.search_helpers import (
            build_citations,
            fused_limit,
            merge_search_results,
            normalize_query_list,
        )

        queries = normalize_query_list(args)
        fallback = (self._last_user_message or "").strip()
        if fallback and fallback not in queries:
            queries.append(fallback)
        if not queries:
            raise ValueError("queries is required")

        top_k = max(1, min(int(args.get("top_k", 3) or 3), 8))
        # Gemini 常把問題改寫成中英西多條查詢；語言要看使用者原話，不看查詢。
        language = detect_language(fallback) if table == "knowledge" and fallback else None
        # 聽出是台語就查台語文件（沒有命中會在 search_records 退回中文）。
        if heard_language == TAIWANESE:
            language = TAIWANESE
        grouped: list[tuple[str, list[dict[str, Any]]]] = []
        embedding_versions: list[str] = []
        for query in queries:
            try:
                embedding_route = encode_query_with_fallback(
                    query,
                    project_id=self.project_id,
                    table_names=(table,),
                )
                results = search_records(
                    table,
                    embedding_route.vector,
                    top_k=top_k,
                    query_text=query,
                    query_type="vector",
                    persona_id=self.persona_id,
                    project_id=self.project_id,
                    embedding_version=embedding_route.version,
                    language=language,
                )
            except Exception as exc:
                logger.warning(
                    "Gemini Live search failed table=%s query=%r err=%s",
                    table,
                    query[:60],
                    exc,
                )
                continue
            grouped.append((query, results))
            if embedding_route.version not in embedding_versions:
                embedding_versions.append(embedding_route.version)

        merged = merge_search_results(
            grouped,
            limit=fused_limit(top_k, self.config),
        )
        return {
            "table": table,
            "queries": queries,
            "embedding_versions": embedding_versions,
            "results": merged,
            "citations": build_citations(merged),
        }

    async def _emit(self, event: dict[str, Any]) -> None:
        if self._event_sink is not None:
            await self._event_sink(event)

    async def _reconnect(self, reason: str) -> bool:
        if self._closed or self._reconnecting:
            return False

        self._reconnecting = True
        if self._response_in_progress:
            self._response_in_progress = False
            await self._emit(
                {
                    "event": "server_stop_audio",
                    "session_id": self.relay_session_id,
                    "timestamp": int(time.time() * 1000),
                    "reason": "provider_reconnect",
                }
            )

        if self._transport is not None:
            try:
                await self._transport.close()
            except Exception:
                pass
            self._transport = None

        for delay in _RECONNECT_DELAYS:
            try:
                await _sleep_before_retry(delay)
                await self.ensure_connected()
                self._reconnecting = False
                self._unavailable = False
                logger.info(
                    "Gemini Live reconnected for relay_session_id=%s after %ss (%s)",
                    self.relay_session_id,
                    delay,
                    reason,
                )
                return True
            except Exception as exc:
                logger.warning(
                    "Gemini Live reconnect failed for relay_session_id=%s delay=%ss error=%s",
                    self.relay_session_id,
                    delay,
                    exc,
                )

        self._reconnecting = False
        self._unavailable = True
        await self._emit(
            {
                "event": "server_error",
                "error_code": "INTERNAL_ERROR",
                "message": "Gemini Live transport unavailable after reconnect retries",
            }
        )
        return False

    async def _keepalive_loop(self) -> None:
        try:
            while not self._closed:
                await asyncio.sleep(_KEEPALIVE_INTERVAL_SECONDS)
                if self._transport is None or self._reconnecting or self._unavailable:
                    continue
                try:
                    await self._transport.ping()
                except Exception as exc:
                    logger.debug("Gemini Live keepalive failed: %s", exc)
        except asyncio.CancelledError:
            raise

    def _build_setup_message(self) -> dict[str, Any]:
        setup: dict[str, Any] = {
            "model": f"models/{self.config.live_gemini_model}",
            "generationConfig": {"responseModalities": ["AUDIO"]},
        }
        # gemini-3.8-live 不支援 thinkingLevel，帶了會被拒絕；extended-thinking
        # 變體才吃這個欄位，所以依模型決定要不要送，而不是無條件帶上。
        thinking_level = self.config.live_gemini_thinking_level.strip()
        if thinking_level and _supports_thinking_level(self.config.live_gemini_model):
            setup["generationConfig"]["thinkingConfig"] = {
                "thinkingLevel": thinking_level,
            }
        elif thinking_level:
            logger.warning(
                "ignoring live_gemini_thinking_level=%r: %s does not accept it",
                thinking_level,
                self.config.live_gemini_model,
            )
        instruction = self._system_instruction.strip() or self.config.live_gemini_system_instruction.strip()
        if instruction:
            setup["systemInstruction"] = {
                "parts": [{"text": instruction}]
            }
        # 不指定語言時中文轉錄回傳簡體；languageCodes 讓 Gemini 直接吐繁體
        # （2026-09-23 實測；單數 languageCode 會被拒）。
        transcription: dict[str, Any] = {}
        languages = [
            code.strip()
            for code in str(getattr(self.config, "live_gemini_transcription_languages", "")).split(",")
            if code.strip()
        ]
        if languages:
            transcription["languageCodes"] = languages
        if self.config.live_gemini_output_audio_transcription:
            setup["outputAudioTranscription"] = dict(transcription)
        setup["inputAudioTranscription"] = dict(transcription)
        if self.config.live_gemini_tools_enabled:
            setup["tools"] = [{"functionDeclarations": build_gemini_tool_declarations()}]

        # Without compression Gemini Live caps a session at 15 min (audio) or
        # 2 min (audio+video), then drops the socket with 1008. A sliding
        # window lifts that cap so video sessions survive past ~2 min.
        if self.config.live_gemini_context_compression:
            setup["contextWindowCompression"] = {"slidingWindow": {}}

        return setup

    def _build_user_turn_message(self, user_text: str) -> dict[str, Any]:
        return {
            "realtimeInput": {
                "text": user_text,
            }
        }

    async def _wait_for_setup_complete(self, transport: JsonTransport) -> None:
        try:
            async with asyncio.timeout(_SETUP_COMPLETE_TIMEOUT_SECONDS):
                while True:
                    message = await transport.recv_json()
                    if message is None:
                        raise RuntimeError("Gemini Live closed before setup completed")
                    if "setupComplete" in message:
                        return
        except TimeoutError as exc:
            raise RuntimeError("Gemini Live setup complete timed out") from exc

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
                    2 * _parse_sample_rate(mime_type)
                )
                audio_bytes = _pcm_to_wav(audio_bytes, _parse_sample_rate(mime_type))

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




def _parse_sample_rate(mime_type: str) -> int:
    match = _PCM_RATE_RE.search(mime_type)
    if not match:
        return 24000
    return int(match.group(1))


def _pcm_to_wav(pcm_bytes: bytes, sample_rate: int) -> bytes:
    data_size = len(pcm_bytes)
    chunk_size = 36 + data_size
    byte_rate = sample_rate * 2
    block_align = 2
    header = b"".join(
        [
            b"RIFF",
            chunk_size.to_bytes(4, "little"),
            b"WAVE",
            b"fmt ",
            (16).to_bytes(4, "little"),
            (1).to_bytes(2, "little"),
            (1).to_bytes(2, "little"),
            sample_rate.to_bytes(4, "little"),
            byte_rate.to_bytes(4, "little"),
            block_align.to_bytes(2, "little"),
            (16).to_bytes(2, "little"),
            b"data",
            data_size.to_bytes(4, "little"),
        ]
    )
    return header + pcm_bytes


async def _sleep_before_retry(base_delay: int) -> None:
    await asyncio.sleep(base_delay + random.uniform(0, 0.25))
