"""Live voice pipeline: orchestrates Brain token stream to TTS audio chunks."""

import asyncio
import json
import logging
import base64
import time
from typing import AsyncIterator, Optional
from dataclasses import dataclass

import httpx
from app.config import get_tts_config
from app.utils.chunker import PunctuationChunker
from app.providers.vibevoice_adapter import VibeVoiceAdapter
from app.providers.base import SynthesizeRequest
from app.session_manager import Session
from app.observability import record_voice_latency

logger = logging.getLogger("backend.live_pipeline")

@dataclass
class LivePipelineConfig:
    brain_url: str
    vibevoice_url: str
    default_ref_voice: str

class LiveVoicePipeline:
    """Consumes Brain SSE stream, chunks text, synthesizes audio, and yields WebSocket events."""

    def __init__(self, session: Session):
        self.session = session
        self.config = get_tts_config()
        self.chunker = PunctuationChunker()
        self.vibevoice = VibeVoiceAdapter(self.config)
        self._http_client = httpx.AsyncClient(timeout=30.0)

    async def run(self, user_text: str) -> AsyncIterator[dict]:
        """Run the end-to-end pipeline."""
        logger.info(f"Starting live pipeline for session {self.session.session_id}")
        t_start = time.monotonic()
        first_chunk_sent = False
        
        # 1. Start Brain chat stream
        # Note: We use the internal brain /chat/stream endpoint
        brain_url = f"{self.config.brain_url}/brain/chat/stream"
        payload = {
            "message": user_text,
            "session_id": self.session.session_id,
            "stream": True
        }

        try:
            async with self._http_client.stream("POST", brain_url, json=payload) as response:
                if response.status_code >= 400:
                    error_text = await response.aread()
                    logger.error(f"Brain stream failed: {response.status_code} - {error_text}")
                    yield {"event": "server_error", "error_code": "brain_error", "message": "Brain service error"}
                    return

                # Accumulator for tokens
                text_buffer = ""
                
                async for line in response.aiter_lines():
                    if not line.strip() or not line.startswith("data: "):
                        continue
                    
                    data_str = line.removeprefix("data: ").strip()
                    if data_str == "[DONE]":
                        break
                    
                    try:
                        data = json.loads(data_str)
                        token = data.get("token", "")
                        text_buffer += token
                        
                        # 2. Check for punctuation to chunk
                        # We use a simple check here, or we can use the Chunker more formally
                        # To keep it streaming-friendly, we look for sentence ends
                        if any(p in token for p in "，。？！；"):
                            # Flush chunks from buffer
                            for chunk in self.chunker.split(text_buffer):
                                # Synthesize and yield
                                event = await self._synthesize_chunk(chunk, is_final=False)
                                if event:
                                    if not first_chunk_sent:
                                        latency_ms = (time.monotonic() - t_start) * 1000
                                        record_voice_latency(latency_ms)
                                        first_chunk_sent = True
                                    yield event
                            text_buffer = ""
                            
                    except json.JSONDecodeError:
                        continue

                # 3. Final flush
                if text_buffer.strip():
                    for chunk in self.chunker.split(text_buffer):
                        event = await self._synthesize_chunk(chunk, is_final=True)
                        if event:
                            yield event
                else:
                    # Send an empty final chunk if needed
                    pass

        except Exception as e:
            logger.error(f"Live pipeline error: {e}")
            yield {"event": "server_error", "error_code": "internal_error", "message": str(e)}

    async def _synthesize_chunk(self, text: str, is_final: bool) -> Optional[dict]:
        """Synthesize a single text chunk into audio and wrap in WebSocket event."""
        if not text.strip():
            return None
            
        logger.debug(f"Synthesizing chunk: {text[:20]}...")
        
        try:
            # Note: SynthesizeRequest is synchronous in the current adapter implementation
            # We might need to run it in a threadpool if it blocks the loop too much
            # Or update the adapter to be async.
            request = SynthesizeRequest(
                text=text,
                voice_hint=self.config.tts_vibevoice_ref_voice,
                sample_rate=24000
            )
            
            # Using the adapter's synthesize method (currently sync)
            # In a real async environment, we should make the adapter async.
            # For now, let's wrap it in run_in_executor
            loop = asyncio.get_running_loop()
            result = await loop.run_in_executor(None, self.vibevoice.synthesize, request)
            
            audio_b64 = base64.b64encode(result.audio_bytes).decode("utf-8")
            
            return {
                "event": "server_stream_chunk",
                "chunk_id": f"chunk-{id(text)}",
                "text": text,
                "audio_base64": audio_b64,
                "is_final": is_final
            }
        except Exception as e:
            logger.error(f"Synthesis failed for chunk: {e}")
            return None
