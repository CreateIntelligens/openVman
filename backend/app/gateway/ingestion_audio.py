"""Audio ingestion — Whisper API or local binary transcription."""

from __future__ import annotations

import logging
import subprocess
from pathlib import Path

from openai import AsyncOpenAI

from app.config import get_tts_config
from app.gateway.ingestion import IngestionResult

logger = logging.getLogger("gateway.ingestion_audio")


async def _transcribe_openai(file_path: str, trace_id: str) -> str:
    """Transcribe audio using OpenAI Whisper API."""
    cfg = get_tts_config()
    client_kwargs: dict = {"api_key": cfg.whisper_api_key}
    if cfg.vision_llm_base_url:
        client_kwargs["base_url"] = cfg.vision_llm_base_url

    client = AsyncOpenAI(**client_kwargs)
    with open(file_path, "rb") as audio_file:
        response = await client.audio.transcriptions.create(
            model="whisper-1",
            file=audio_file,
            language="zh",
        )
    return response.text


def _transcribe_local(file_path: str, trace_id: str) -> str:
    """Transcribe audio using local whisper binary."""
    cfg = get_tts_config()
    result = subprocess.run(
        [cfg.whisper_local_bin, file_path, "--language", "zh", "--output_format", "txt"],
        capture_output=True,
        text=True,
        timeout=120,
    )
    if result.returncode != 0:
        raise RuntimeError(f"whisper local failed: {result.stderr}")

    # whisper outputs to <input>.txt
    txt_path = Path(file_path).with_suffix(".txt")
    if txt_path.exists():
        return txt_path.read_text(encoding="utf-8").strip()

    return result.stdout.strip()


async def transcribe(file_path: str, trace_id: str) -> IngestionResult:
    """Transcribe audio file using configured provider.

    Returns IngestionResult with content_type="audio_transcription".
    """
    cfg = get_tts_config()
    logger.info("transcribe trace_id=%s provider=%s", trace_id, cfg.whisper_provider)

    try:
        if cfg.whisper_provider == "openai":
            content = await _transcribe_openai(file_path, trace_id)
        else:
            content = _transcribe_local(file_path, trace_id)

        logger.info("transcription_ok trace_id=%s chars=%d", trace_id, len(content))
        return IngestionResult(content_type="audio_transcription", content=content)

    except Exception as exc:
        logger.error("transcription_failed trace_id=%s err=%s", trace_id, exc)
        return IngestionResult(
            content_type="audio_transcription",
            content="（音訊轉錄失敗）",
        )
