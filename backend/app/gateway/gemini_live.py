"""Gemini Live adapter for the websocket live voice pipeline."""

from __future__ import annotations

import base64
import json
import logging
import re
import time
from typing import Any, Protocol

import httpx
import websockets

from app.config import TTSRouterConfig, get_tts_config
from app.session_manager import Session

logger = logging.getLogger("backend.gemini_live")

_GEMINI_LIVE_WS_URL = (
    "wss://generativelanguage.googleapis.com/ws/"
    "google.ai.generativelanguage.v1beta.GenerativeService.BidiGenerateContent"
)
_PCM_RATE_RE = re.compile(r"rate=(\d+)")


class JsonTransport(Protocol):
    async def connect(self) -> None: ...

    async def send_json(self, payload: dict[str, Any]) -> None: ...

    async def recv_json(self) -> dict[str, Any] | None: ...

    async def close(self) -> None: ...


class GeminiLiveWebSocketTransport:
    """Minimal JSON transport for Gemini Live's raw websocket API."""

    def __init__(self, config: TTSRouterConfig) -> None:
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

    async def close(self) -> None:
        if self._ws is not None:
            await self._ws.close()
            self._ws = None


class GeminiLivePipeline:
    """Turn-based adapter over Gemini Live using the existing websocket event contract."""

    def __init__(
        self,
        session: Session,
        *,
        config: TTSRouterConfig | None = None,
        transport_factory: Any | None = None,
        brain_http_factory: Any | None = None,
    ) -> None:
        self.session = session
        self.config = config or get_tts_config()
        self._transport_factory = transport_factory or (lambda cfg: GeminiLiveWebSocketTransport(cfg))
        self._brain_http_factory = brain_http_factory or (
            lambda: httpx.AsyncClient(timeout=httpx.Timeout(connect=5, read=25, write=10, pool=5))
        )
        self._chunk_counter = 0

    async def run(self, user_text: str):
        transport = self._transport_factory(self.config)
        brain_client = self._brain_http_factory()

        try:
            await transport.connect()
            await transport.send_json({"setup": self._build_setup_message()})
            await self._wait_for_setup_complete(transport)
            await transport.send_json(self._build_user_turn_message(user_text))

            while True:
                message = await transport.recv_json()
                if message is None:
                    break

                tool_call = message.get("toolCall")
                if isinstance(tool_call, dict):
                    await self._handle_tool_call(tool_call, transport, brain_client)
                    continue

                server_content = message.get("serverContent")
                if isinstance(server_content, dict):
                    if server_content.get("interrupted"):
                        yield {
                            "event": "server_stop_audio",
                            "session_id": self.session.session_id,
                            "timestamp": int(time.time() * 1000),
                            "reason": "provider_interruption",
                        }
                    for event in self._events_from_server_content(server_content):
                        yield event
                    if server_content.get("turnComplete"):
                        break
        finally:
            await transport.close()
            aclose = getattr(brain_client, "aclose", None)
            if callable(aclose):
                await aclose()

    def _build_setup_message(self) -> dict[str, Any]:
        setup: dict[str, Any] = {
            "model": f"models/{self.config.live_gemini_model}",
            "generationConfig": {
                "responseModalities": ["AUDIO"],
            },
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
                "turns": [
                    {
                        "role": "user",
                        "parts": [{"text": user_text}],
                    }
                ],
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
                    "chunk_id": f"gemini-live-{self.session.session_id}-{self._chunk_counter}",
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

    async def _handle_tool_call(
        self,
        tool_call: dict[str, Any],
        transport: JsonTransport,
        brain_client: Any,
    ) -> None:
        function_calls = tool_call.get("functionCalls") or []
        function_responses: list[dict[str, Any]] = []

        for function_call in function_calls:
            if not isinstance(function_call, dict):
                continue
            function_responses.append(
                await self._execute_function_call(function_call, brain_client)
            )

        if function_responses:
            await transport.send_json(
                {
                    "toolResponse": {
                        "functionResponses": function_responses,
                    }
                }
            )

    async def _execute_function_call(self, function_call: dict[str, Any], brain_client: Any) -> dict[str, Any]:
        name = str(function_call.get("name", "")).strip()
        call_id = str(function_call.get("id", "")).strip()
        args = function_call.get("args") or {}
        if isinstance(args, str):
            args = json.loads(args)

        try:
            if name == "search_knowledge":
                response = await self._search_brain("knowledge", args, brain_client)
            elif name == "search_memory":
                response = await self._search_brain("memories", args, brain_client)
            else:
                raise ValueError(f"Unsupported Gemini Live tool: {name}")
        except Exception as exc:
            logger.warning("Gemini Live tool %s failed: %s", name, exc)
            response = {"error": str(exc)}

        return {
            "id": call_id,
            "name": name,
            "response": response,
        }

    async def _search_brain(self, table: str, args: dict[str, Any], brain_client: Any) -> dict[str, Any]:
        query = str(args.get("query", "")).strip()
        if not query:
            raise ValueError("query is required")

        payload = {
            "query": query,
            "table": table,
            "top_k": max(1, min(int(args.get("top_k", 3)), 8)),
            "query_type": "vector",
            "persona_id": str(self.session.metadata.get("persona_id", "default")),
            "project_id": str(self.session.metadata.get("project_id", "default")),
        }
        response = await brain_client.post(
            f"{self.config.brain_url.rstrip('/')}/brain/search",
            json=payload,
        )
        response.raise_for_status()
        data = response.json()
        return {"results": data.get("results", [])}

    def _build_tool_declarations(self) -> list[dict[str, Any]]:
        return [
            {
                "name": "search_knowledge",
                "description": "Search the workspace knowledge base for factual context.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "query": {
                            "type": "string",
                            "description": "Semantic search query.",
                        },
                        "top_k": {
                            "type": "integer",
                            "description": "Maximum results to return.",
                        },
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
                        "query": {
                            "type": "string",
                            "description": "Semantic search query.",
                        },
                        "top_k": {
                            "type": "integer",
                            "description": "Maximum results to return.",
                        },
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
