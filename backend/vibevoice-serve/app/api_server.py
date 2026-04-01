"""VibeVoice TTS serve — uses official microsoft/VibeVoice 1.5B package."""

import asyncio
import copy
import io
import logging
import os
import tempfile
from pathlib import Path
from typing import Optional

import torch
import uvicorn
from contextlib import asynccontextmanager
from fastapi import FastAPI, HTTPException
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("vibevoice-serve")

# ---------------------------------------------------------------------------
# Config from env
# ---------------------------------------------------------------------------

MODEL_PATH = os.getenv("VIBEVOICE_MODEL_PATH", "microsoft/VibeVoice-1.5B")
DEFAULT_SPEAKER = os.getenv("VIBEVOICE_DEFAULT_SPEAKER", "")
VOICES_DIR = os.getenv("VIBEVOICE_VOICES_DIR", "/app/assets/tts_references")

# ---------------------------------------------------------------------------
# Model registry
# ---------------------------------------------------------------------------

_model = None
_processor = None
_available_speakers: list[str] = []


def _scan_voices() -> dict[str, str]:
    """Scan VOICES_DIR for WAV files, return {name: path} mapping."""
    voices: dict[str, str] = {}
    if not os.path.isdir(VOICES_DIR):
        logger.warning("Voices directory not found: %s", VOICES_DIR)
        return voices
    for f in sorted(os.listdir(VOICES_DIR)):
        if f.lower().endswith((".wav", ".mp3")):
            name = Path(f).stem
            voices[f] = os.path.join(VOICES_DIR, f)
            # Also register without extension for convenience
            voices[name] = os.path.join(VOICES_DIR, f)
    return voices


_voice_paths: dict[str, str] = {}  # name_or_filename -> absolute path


def _load_model() -> None:
    """Load the VibeVoice 1.5B model."""
    global _model, _processor, _voice_paths, _available_speakers

    from vibevoice import VibeVoiceForConditionalGenerationInference, VibeVoiceProcessor

    logger.info("Loading VibeVoice model: %s", MODEL_PATH)

    device = "cuda" if torch.cuda.is_available() else "cpu"
    dtype = torch.bfloat16 if device == "cuda" else torch.float32

    try:
        _model = VibeVoiceForConditionalGenerationInference.from_pretrained(
            MODEL_PATH,
            torch_dtype=dtype,
            device_map=device,
            attn_implementation="flash_attention_2" if device == "cuda" else "sdpa",
        )
    except Exception:
        logger.warning("flash_attention_2 failed, falling back to sdpa")
        _model = VibeVoiceForConditionalGenerationInference.from_pretrained(
            MODEL_PATH,
            torch_dtype=dtype,
            device_map=device,
            attn_implementation="sdpa",
        )

    _processor = VibeVoiceProcessor.from_pretrained(MODEL_PATH)

    # Scan voice references
    _voice_paths = _scan_voices()
    # Available speakers = unique filenames (with extension) for the API
    _available_speakers = sorted(
        f for f in _voice_paths if "." in f  # only filenames, not bare stems
    )

    logger.info("Model loaded. Available voices: %s", _available_speakers)


# ---------------------------------------------------------------------------
# API
# ---------------------------------------------------------------------------

_load_task: Optional[asyncio.Task] = None


@asynccontextmanager
async def lifespan(app: FastAPI):
    global _load_task
    loop = asyncio.get_running_loop()
    _load_task = asyncio.ensure_future(loop.run_in_executor(None, _load_model))
    _load_task.add_done_callback(
        lambda t: logger.error("Model loading failed: %s", t.exception()) if t.exception() else None
    )
    yield

app = FastAPI(title="VibeVoice Serve", lifespan=lifespan)


class SynthesizeRequest(BaseModel):
    text: str
    model: Optional[str] = None
    reference_id: Optional[str] = None  # voice filename or stem
    streaming: Optional[bool] = False


@app.get("/health")
async def health():
    return {
        "status": "ok" if _model is not None else "loading",
        "model": MODEL_PATH,
        "default_speaker": DEFAULT_SPEAKER,
        "available_speakers": _available_speakers,
    }


@app.get("/voices")
async def list_voices():
    """List available voice reference files."""
    return {"voices": _available_speakers}


@app.post("/tts")
async def synthesize(req: SynthesizeRequest):
    if _model is None:
        raise HTTPException(status_code=503, detail="Model still loading")

    speaker = req.reference_id or DEFAULT_SPEAKER
    if speaker and speaker not in _voice_paths:
        raise HTTPException(
            status_code=400,
            detail=f"Voice '{speaker}' not found. Available: {_available_speakers}",
        )

    try:
        loop = asyncio.get_running_loop()
        audio_bytes = await loop.run_in_executor(
            None, _synthesize_sync, req.text, speaker
        )

        return StreamingResponse(
            io.BytesIO(audio_bytes),
            media_type="audio/wav",
        )
    except Exception as e:
        logger.error("Synthesis failed: %s", e)
        raise HTTPException(status_code=500, detail=str(e))


def _synthesize_sync(text: str, speaker: str) -> bytes:
    """Run TTS inference (blocking) and return WAV bytes."""
    # Build voice sample list for the processor
    voice_sample = _voice_paths.get(speaker)
    voice_samples = [[voice_sample]] if voice_sample else None

    # Format as single-speaker script
    script = f"Speaker 1: {text}"

    inputs = _processor(
        text=script,
        voice_samples=voice_samples,
        return_tensors="pt",
        padding=True,
    ).to(_model.device)

    outputs = _model.generate(
        **inputs,
        cfg_scale=1.3,
        is_prefill=bool(voice_sample),
        generation_config={"do_sample": False},
    )

    with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as tmp:
        tmp_path = tmp.name

    try:
        _processor.save_audio(outputs.speech_outputs[0], output_path=tmp_path)
        with open(tmp_path, "rb") as f:
            return f.read()
    finally:
        os.unlink(tmp_path)


if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=3000)
