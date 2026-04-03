"""VibeVoice TTS serve — uses transformers native VibeVoice 1.5B."""

import asyncio
import io
import json
import logging
import os
import re
import tempfile
from pathlib import Path
from typing import Optional

import diffusers
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

MODEL_PATH = os.getenv("VIBEVOICE_MODEL_PATH", "bezzam/VibeVoice-1.5B-hf")
DEFAULT_SPEAKER = os.getenv("VIBEVOICE_DEFAULT_SPEAKER", "0")
MAX_NEW_TOKENS = int(os.getenv("VIBEVOICE_MAX_NEW_TOKENS", "300"))

# ---------------------------------------------------------------------------
# Model registry
# ---------------------------------------------------------------------------

_model = None
_processor = None
_noise_scheduler = None
_set_seed = None  # cached import


def _patch_tokenizer_config(model_path: str) -> None:
    """Fix extra_special_tokens from list to object if needed (community HF conversion issue)."""
    try:
        from huggingface_hub import hf_hub_download
        local_path = hf_hub_download(model_path, "tokenizer_config.json")
    except Exception:
        return
    path = Path(local_path)
    text = path.read_text()
    patched = re.sub(
        r'"extra_special_tokens"\s*:\s*\[[^\]]*\],',
        '"extra_special_tokens": {},',
        text,
        flags=re.S,
    )
    if patched != text:
        path.write_text(patched)
        logger.info("Patched tokenizer_config.json: extra_special_tokens list → object")


def _load_model() -> None:
    """Load the VibeVoice 1.5B model via pengzhiliang/transformers fork."""
    global _model, _processor, _noise_scheduler, _set_seed

    from transformers import AutoProcessor, VibeVoiceForConditionalGeneration, set_seed

    _set_seed = set_seed

    logger.info("Loading VibeVoice model: %s", MODEL_PATH)

    _patch_tokenizer_config(MODEL_PATH)

    _model = VibeVoiceForConditionalGeneration.from_pretrained(
        MODEL_PATH, device_map="cuda",
    )
    _processor = AutoProcessor.from_pretrained(MODEL_PATH)
    _noise_scheduler = diffusers.DPMSolverMultistepScheduler(
        beta_schedule="squaredcos_cap_v2",
        prediction_type="v_prediction",
    )

    logger.info("Model loaded on %s, dtype=%s", _model.device, _model.dtype)


# ---------------------------------------------------------------------------
# API
# ---------------------------------------------------------------------------


@asynccontextmanager
async def lifespan(app: FastAPI):
    loop = asyncio.get_running_loop()
    task = asyncio.ensure_future(loop.run_in_executor(None, _load_model))
    task.add_done_callback(
        lambda t: logger.error("Model loading failed: %s", t.exception()) if t.exception() else None
    )
    yield

app = FastAPI(title="VibeVoice Serve", lifespan=lifespan)


class SynthesizeRequest(BaseModel):
    text: str
    speaker: Optional[str] = None       # role ID: "0", "1", "2", "3"
    max_new_tokens: Optional[int] = None
    seed: Optional[int] = 42


@app.get("/health")
async def health():
    return {
        "status": "ok" if _model is not None else "loading",
        "model": MODEL_PATH,
        "default_speaker": DEFAULT_SPEAKER,
    }


@app.post("/tts")
async def synthesize(req: SynthesizeRequest):
    if _model is None:
        raise HTTPException(status_code=503, detail="Model still loading")

    try:
        loop = asyncio.get_running_loop()
        audio_bytes = await loop.run_in_executor(
            None, _synthesize_sync, req.text, req.speaker, req.max_new_tokens, req.seed,
        )

        return StreamingResponse(
            io.BytesIO(audio_bytes),
            media_type="audio/wav",
        )
    except Exception as e:
        logger.error("Synthesis failed: %s", e)
        raise HTTPException(status_code=500, detail=str(e))


def _synthesize_sync(text: str, speaker: str | None, max_tokens: int | None, seed: int | None) -> bytes:
    """Run TTS inference (blocking) and return WAV bytes."""
    role_id = speaker or DEFAULT_SPEAKER
    if seed is not None:
        _set_seed(seed)

    chat = [{"role": role_id, "content": [{"type": "text", "text": text}]}]

    inputs = _processor.apply_chat_template(
        chat,
        tokenize=True,
        return_dict=True,
    ).to(_model.device, _model.dtype)

    audio = _model.generate(
        **inputs,
        noise_scheduler=_noise_scheduler,
        max_new_tokens=max_tokens or MAX_NEW_TOKENS,
    )

    with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as tmp:
        tmp_path = tmp.name

    try:
        _processor.save_audio(audio, output_path=tmp_path)
        with open(tmp_path, "rb") as f:
            return f.read()
    finally:
        os.unlink(tmp_path)


if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=3000)
