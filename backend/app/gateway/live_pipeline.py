"""Live voice pipeline: orchestrates Brain token stream to TTS audio chunks.

Uses a producer/consumer pattern so Brain SSE reading and TTS synthesis
run concurrently — the next chunk starts synthesizing while the previous
one is being sent to the client.
"""

import asyncio
import json
import logging
import base64
import time
from typing import AsyncIterator, Optional

import httpx
from app.config import get_tts_config
from app.utils.chunker import PunctuationChunker
from app.providers.vibevoice_adapter import VibeVoiceAdapter
from app.providers.base import SynthesizeRequest
from app.session_manager import Session
from app.observability import record_voice_latency

logger = logging.getLogger("backend.live_pipeline")

_SENTINEL = object()  # marks end of text/audio queues


class LiveVoicePipeline:
    """Consumes Brain SSE stream, chunks text, synthesizes audio, and yields WebSocket events."""

    def __init__(self, session: Session):
        self.session = session
        self.config = get_tts_config()
        self.chunker = PunctuationChunker()
        self.vibevoice = VibeVoiceAdapter(self.config)

    async def run(self, user_text: str) -> AsyncIterator[dict]:
        """Run the end-to-end pipeline with concurrent Brain reading and TTS synthesis."""
        logger.info("Starting live pipeline for session %s", self.session.session_id)
        t_start = time.monotonic()

        text_queue: asyncio.Queue[Optional[str]] = asyncio.Queue()
        audio_queue: asyncio.Queue[Optional[dict]] = asyncio.Queue()

        # Producer: read Brain SSE → chunk text → put into text_queue
        producer_task = asyncio.create_task(
            self._read_brain_stream(user_text, text_queue)
        )

        # Consumer: take text chunks → synthesize → put audio events into audio_queue
        consumer_task = asyncio.create_task(
            self._synthesize_worker(text_queue, audio_queue)
        )

        # Yield audio events as they become ready
        first_chunk_sent = False
        try:
            while True:
                event = await audio_queue.get()
                if event is _SENTINEL:
                    break
                if not first_chunk_sent:
                    latency_ms = (time.monotonic() - t_start) * 1000
                    record_voice_latency(latency_ms)
                    first_chunk_sent = True
                yield event
        except Exception as e:
            logger.error("Live pipeline error: %s", e)
            producer_task.cancel()
            consumer_task.cancel()
            yield {"event": "server_error", "error_code": "internal_error", "message": str(e)}
            return

        # Ensure tasks are done
        await asyncio.gather(producer_task, consumer_task, return_exceptions=True)

    async def _read_brain_stream(
        self, user_text: str, text_queue: asyncio.Queue[Optional[str]]
    ) -> None:
        """Read Brain SSE, chunk by punctuation, and enqueue text chunks."""
        brain_url = f"{self.config.brain_url}/brain/chat/stream"
        payload = {
            "message": user_text,
            "session_id": self.session.session_id,
            "stream": True,
        }

        try:
            async with httpx.AsyncClient(timeout=30.0) as http_client:
                async with http_client.stream("POST", brain_url, json=payload) as response:
                    if response.status_code >= 400:
                        error_text = await response.aread()
                        logger.error("Brain stream failed: %s - %s", response.status_code, error_text)
                        await text_queue.put(_SENTINEL)
                        return

                    text_buffer = ""

                    async for line in response.aiter_lines():
                        line = line.strip()
                        if not line.startswith("data: "):
                            continue

                        data_str = line.removeprefix("data: ").strip()
                        if data_str == "[DONE]":
                            break

                        try:
                            data = json.loads(data_str)
                            token = data.get("token", "")
                            text_buffer += token

                            if any(p in token for p in "，。？！；"):
                                for chunk in self.chunker.split(text_buffer):
                                    await text_queue.put(chunk)
                                text_buffer = ""

                        except json.JSONDecodeError:
                            continue

                    # Final flush
                    if text_buffer.strip():
                        for chunk in self.chunker.split(text_buffer):
                            await text_queue.put(chunk)

        except Exception as e:
            logger.error("Brain stream error: %s", e)
        finally:
            await text_queue.put(_SENTINEL)

    async def _synthesize_worker(
        self, text_queue: asyncio.Queue[Optional[str]], audio_queue: asyncio.Queue[Optional[dict]]
    ) -> None:
        """Take text chunks from the queue and synthesize them into audio events."""
        loop = asyncio.get_running_loop()

        last_event = None
        try:
            while True:
                text = await text_queue.get()
                if text is _SENTINEL:
                    break
                if not text.strip():
                    continue

                event = await self._synthesize_chunk(text, loop)
                if event:
                    if last_event is not None:
                        await audio_queue.put(last_event)
                    last_event = event
        except Exception as e:
            logger.error("Synthesize worker error: %s", e)
        finally:
            if last_event is not None:
                last_event["is_final"] = True
                await audio_queue.put(last_event)
            await audio_queue.put(_SENTINEL)

    async def _synthesize_chunk(self, text: str, loop: asyncio.AbstractEventLoop) -> Optional[dict]:
        """Synthesize a single text chunk into audio and wrap in WebSocket event."""
        logger.debug("Synthesizing chunk: %s...", text[:20])

        try:
            request = SynthesizeRequest(
                text=text,
                voice_hint=self.config.tts_vibevoice_ref_voice,
                sample_rate=24000,
            )

            result = await loop.run_in_executor(None, self.vibevoice.synthesize, request)
            audio_b64 = base64.b64encode(result.audio_bytes).decode("utf-8")

            return {
                "event": "server_stream_chunk",
                "chunk_id": f"chunk-{id(text)}",
                "text": text,
                "audio_base64": audio_b64,
                "is_final": False,
            }
        except Exception as e:
            logger.error("Synthesis failed for chunk: %s", e)
            return None
