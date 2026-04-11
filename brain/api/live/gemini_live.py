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
from memory.retrieval import search_records

logger = logging.getLogger("brain.live.gemini_live")

_GEMINI_LIVE_WS_URL = (
    "wss://generativelanguage.googleapis.com/ws/"
    "google.ai.generativelanguage.v1beta.GenerativeService.BidiGenerateContent"
)
_PCM_RATE_RE = re.compile(r"rate=(\d+)")
_RECONNECT_DELAYS = (1, 2, 4, 8, 16)
_KEEPALIVE_INTERVAL_SECONDS = 600

EventSink = Callable[[dict[str, Any]], Awaitable[None]]


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
        config: BrainSettings | None = None,
        transport_factory: Any | None = None,
        event_sink: EventSink | None = None,
    ) -> None:
        self.relay_session_id = relay_session_id
        self.client_id = client_id
        self.persona_id = persona_id
        self.project_id = project_id
        self.config = config or get_settings()
        self._transport_factory = transport_factory or (lambda cfg: GeminiLiveWebSocketTransport(cfg))
        self._event_sink = event_sink
        self._transport: JsonTransport | None = None
        self._listener_task: asyncio.Task | None = None
        self._keepalive_task: asyncio.Task | None = None
        self._closed = False
        self._chunk_counter = 0
        self._response_in_progress = False
        self._reconnecting = False
        self._unavailable = False
        self._connect_lock = asyncio.Lock()

    async def ensure_connected(self) -> None:
        if self._transport is not None:
            return
        if self._unavailable:
            raise RuntimeError("Gemini Live transport is unavailable")

        async with self._connect_lock:
            if self._transport is not None:
                return
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

    async def send_text_turn(self, user_text: str) -> None:
        await self.ensure_connected()
        self._response_in_progress = True
        await self._transport.send_json(self._build_user_turn_message(user_text))

    async def send_realtime_input(self, audio_b64: str, mime_type: str) -> None:
        if self._reconnecting or self._unavailable:
            logger.debug("dropping audio chunk while Gemini Live transport is unavailable")
            return
        await self.ensure_connected()
        await self._transport.send_json(
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
        await self.ensure_connected()
        self._response_in_progress = True
        await self._transport.send_json({"realtimeInput": {"audioStreamEnd": True}})

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
        if self._transport is not None:
            await self._transport.close()
            self._transport = None

    async def _listen(self) -> None:
        try:
            while self._transport is not None:
                transport = self._transport
                try:
                    message = await transport.recv_json()
                except asyncio.CancelledError:
                    raise
                except Exception as exc:
                    logger.error("Gemini Live listener failed: %s", exc, exc_info=True)
                    if await self._reconnect(str(exc)):
                        continue
                    break

                if message is None:
                    if await self._reconnect("Gemini Live websocket closed cleanly"):
                        continue
                    break

                tool_call = message.get("toolCall")
                if isinstance(tool_call, dict):
                    await self._handle_tool_call(tool_call)
                    continue

                server_content = message.get("serverContent")
                if not isinstance(server_content, dict):
                    continue

                if server_content.get("interrupted"):
                    await self._emit(
                        {
                            "event": "server_stop_audio",
                            "session_id": self.relay_session_id,
                            "timestamp": int(time.time() * 1000),
                            "reason": "provider_interruption",
                        }
                    )

                for event in self._events_from_server_content(server_content):
                    await self._emit(event)

                if server_content.get("turnComplete"):
                    self._response_in_progress = False
        except asyncio.CancelledError:
            raise
        finally:
            transport = self._transport
            self._transport = None
            if transport is not None:
                await transport.close()

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

        try:
            if name == "search_knowledge":
                response = self._search("knowledge", args)
            elif name == "search_memory":
                response = self._search("memories", args)
            else:
                raise ValueError(f"Unsupported Gemini Live tool: {name}")
        except Exception as exc:
            logger.warning("Gemini Live tool %s failed: %s", name, exc)
            response = {"error": str(exc)}

        return {"id": call_id, "name": name, "response": response}

    def _search(self, table: str, args: dict[str, Any]) -> dict[str, Any]:
        query = str(args.get("query", "")).strip()
        if not query:
            raise ValueError("query is required")

        top_k = max(1, min(int(args.get("top_k", 3)), 8))
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
        )
        return {"results": results}

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
                "error_code": "internal_error",
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
        thinking_level = self.config.live_gemini_thinking_level.strip()
        if thinking_level:
            setup["generationConfig"]["thinkingConfig"] = {
                "thinkingLevel": thinking_level,
            }
        if self.config.live_gemini_system_instruction.strip():
            setup["systemInstruction"] = {
                "parts": [{"text": self.config.live_gemini_system_instruction.strip()}]
            }
        if self.config.live_gemini_output_audio_transcription:
            setup["outputAudioTranscription"] = {}
        if self.config.live_gemini_tools_enabled:
            setup["tools"] = [{"functionDeclarations": self._build_tool_declarations()}]
        return setup

    def _build_user_turn_message(self, user_text: str) -> dict[str, Any]:
        return {
            "clientContent": {
                "turns": [{"role": "user", "parts": [{"text": user_text}]}],
                "turnComplete": True,
            }
        }

    async def _wait_for_setup_complete(self, transport: JsonTransport) -> None:
        while True:
            message = await transport.recv_json()
            if message is None:
                raise RuntimeError("Gemini Live closed before setup completed")
            if "setupComplete" in message:
                return

    def _events_from_server_content(self, server_content: dict[str, Any]) -> list[dict[str, Any]]:
        model_turn = server_content.get("modelTurn") or {}
        parts = model_turn.get("parts") or []
        text = self._extract_text(parts, server_content)
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
                audio_bytes = _pcm_to_wav(audio_bytes, _parse_sample_rate(mime_type))

            self._chunk_counter += 1
            events.append(
                {
                    "event": "server_stream_chunk",
                    "chunk_id": f"gemini-live-{self.relay_session_id}-{self._chunk_counter}",
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
        joined = "".join(text_parts).strip()
        if joined:
            return joined
        transcription = server_content.get("outputTranscription") or {}
        text = transcription.get("text", "")
        return text.strip() if isinstance(text, str) else ""

    def _build_tool_declarations(self) -> list[dict[str, Any]]:
        return [
            {
                "name": "search_knowledge",
                "description": "Search the workspace knowledge base for factual context.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "query": {"type": "string", "description": "Semantic search query."},
                        "top_k": {"type": "integer", "description": "Maximum results to return."},
                    },
                    "required": ["query"],
                },
            },
            {
                "name": "search_memory",
                "description": "Search prior user-specific memories for relevant context.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "query": {"type": "string", "description": "Semantic search query."},
                        "top_k": {"type": "integer", "description": "Maximum results to return."},
                    },
                    "required": ["query"],
                },
            },
        ]


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
