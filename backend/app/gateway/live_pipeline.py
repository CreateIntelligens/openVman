"""Live voice pipeline: orchestrates Brain reply to TTS audio chunks.

Uses a producer/consumer pattern so text chunking and TTS synthesis
run concurrently — the next chunk starts synthesizing while the previous
one is being sent to the client.
"""

import asyncio
import base64
import logging
import time
from typing import AsyncIterator, Optional

import httpx
from app.config import get_tts_config
from app.utils.chunker import PunctuationChunker
from app.providers.base import SynthesizeRequest
from app.service import TTSRouterService
from app.session_manager import Session
from app.observability import record_voice_latency

logger = logging.getLogger("backend.live_pipeline")

_SENTINEL: str = "\x00"  # marks end of text queue
_AUDIO_SENTINEL: dict = {}  # marks end of audio queue


class LiveVoicePipeline:
    """Calls Brain /chat, chunks the reply by punctuation, synthesizes audio, and yields WebSocket events."""

    def __init__(self, session: Session):
        self.session = session
        self.config = get_tts_config()
        self.chunker = PunctuationChunker()
        self.tts_router = TTSRouterService(self.config)

    async def run(self, user_text: str) -> AsyncIterator[dict]:
        """Run the end-to-end pipeline with concurrent text chunking and TTS synthesis."""
        logger.info("Starting live pipeline for session %s", self.session.session_id)
        t_start = time.monotonic()

        reply = await self._fetch_brain_reply(user_text)
        if reply is None:
            yield {"event": "server_error", "error_code": "internal_error", "message": "Brain 回覆失敗"}
            return

        text_queue: asyncio.Queue[Optional[str]] = asyncio.Queue()
        audio_queue: asyncio.Queue[Optional[dict]] = asyncio.Queue()

        for chunk in self.chunker.split(reply):
            if chunk:
                await text_queue.put(chunk)
        await text_queue.put(_SENTINEL)  # end marker

        consumer_task = asyncio.create_task(
            self._synthesize_worker(text_queue, audio_queue)
        )

        first_chunk_sent = False
        try:
            while True:
                event = await audio_queue.get()
                if event is _AUDIO_SENTINEL:
                    break
                if not first_chunk_sent:
                    latency_ms = (time.monotonic() - t_start) * 1000
                    record_voice_latency(latency_ms)
                    first_chunk_sent = True
                yield event
        except Exception as e:
            logger.error("Live pipeline error: %s", e)
            consumer_task.cancel()
            yield {"event": "server_error", "error_code": "internal_error", "message": str(e)}
            return

        await consumer_task

    async def _fetch_brain_reply(self, user_text: str) -> Optional[str]:
        """Call Brain /chat and return the full reply text."""
        brain_url = f"{self.config.brain_url}/brain/chat"
        payload = {
            "message": user_text,
            "session_id": self.session.session_id,
        }
        try:
            async with httpx.AsyncClient(timeout=60.0) as http_client:
                response = await http_client.post(brain_url, json=payload)
                if response.status_code >= 400:
                    logger.error("Brain chat failed: %s - %s", response.status_code, response.text)
                    return None
                data = response.json()
                return data.get("reply") or ""
        except Exception as e:
            logger.error("Brain chat error: %s", e)
            return None

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
            await audio_queue.put(_AUDIO_SENTINEL)

    async def _synthesize_chunk(self, text: str, loop: asyncio.AbstractEventLoop) -> Optional[dict]:
        """Synthesize a single text chunk into audio and wrap in WebSocket event."""
        logger.debug("Synthesizing chunk: %s...", text[:20])

        try:
            request = SynthesizeRequest(
                text=text,
                sample_rate=24000,
            )

            output = await loop.run_in_executor(None, self.tts_router.synthesize, request)
            audio_b64 = base64.b64encode(output.result.audio_bytes).decode("utf-8")

            return {
                "event": "server_stream_chunk",
                "chunk_id": f"chunk-{id(text)}",
                "session_id": self.session.session_id,
                "text": text,
                "audio_base64": audio_b64,
                "is_final": False,
            }
        except Exception as e:
            logger.error("Synthesis failed for chunk: %s", e)
            return None
