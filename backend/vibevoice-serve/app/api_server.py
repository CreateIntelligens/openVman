"""VibeVoice TTS serve — supports 0.5B (fast) and 1.5B (quality) models."""

import asyncio
import io
import logging
import os
import tempfile

import uvicorn
from contextlib import asynccontextmanager
from fastapi import FastAPI, HTTPException
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
from typing import Optional

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("vibevoice-serve")

# ---------------------------------------------------------------------------
# Config from env
# ---------------------------------------------------------------------------

MODEL_IDS = {
    "0.5b": os.getenv("VIBEVOICE_MODEL_0_5B", "bezzam/VibeVoice-0.5B-hf"),
    "1.5b": os.getenv("VIBEVOICE_MODEL_1_5B", "bezzam/VibeVoice-1.5B-hf"),
}

# Which models to load at startup (comma-separated, e.g. "0.5b" or "0.5b,1.5b")
ENABLED_MODELS = [
    m.strip() for m in os.getenv("VIBEVOICE_ENABLED_MODELS", "0.5b").split(",") if m.strip()
]

DEFAULT_MODEL = os.getenv("VIBEVOICE_DEFAULT_MODEL", ENABLED_MODELS[0])

# ---------------------------------------------------------------------------
# Model registry
# ---------------------------------------------------------------------------

_models: dict[str, dict] = {}  # {"0.5b": {"processor": ..., "model": ..., "gen_config": ...}}
_noise_scheduler = None


def _patch_tokenizer_config(model_id: str) -> None:
    """Fix extra_special_tokens list→dict in cached tokenizer_config.json."""
    import json
    from pathlib import Path
    from huggingface_hub import try_to_load_from_cache

    cached = try_to_load_from_cache(model_id, "tokenizer_config.json")
    if cached is None or not isinstance(cached, str):
        return

    path = Path(cached)
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        if isinstance(data.get("extra_special_tokens"), list):
            data["extra_special_tokens"] = {}
            path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
            logger.info("Patched tokenizer_config.json for %s", model_id)
    except Exception as exc:
        logger.warning("tokenizer_config.json patch failed for %s: %s", model_id, exc)


def _load_models() -> None:
    """Load all enabled models."""
    global _noise_scheduler

    import diffusers
    from transformers import AutoProcessor, VibeVoiceForConditionalGeneration, set_seed

    set_seed(42)

    _noise_scheduler = diffusers.DPMSolverMultistepScheduler(
        beta_schedule="squaredcos_cap_v2",
        prediction_type="v_prediction",
    )

    for name in ENABLED_MODELS:
        if name in _models:
            continue
        model_id = MODEL_IDS.get(name)
        if not model_id:
            logger.warning("Unknown model name: %s, skipping", name)
            continue

        logger.info("Loading VibeVoice %s: %s", name, model_id)
        _patch_tokenizer_config(model_id)

        processor = AutoProcessor.from_pretrained(model_id)
        model = VibeVoiceForConditionalGeneration.from_pretrained(
            model_id, device_map="cuda",
        )

        gen_config = model.generation_config
        gen_config.max_new_tokens = 120
        gen_config.max_length = None
        gen_config.noise_scheduler = _noise_scheduler

        _models[name] = {
            "processor": processor,
            "model": model,
            "gen_config": gen_config,
        }
        logger.info("VibeVoice %s loaded on %s", name, next(model.parameters()).device)


# ---------------------------------------------------------------------------
# API
# ---------------------------------------------------------------------------

_load_task: Optional[asyncio.Task] = None


@asynccontextmanager
async def lifespan(app: FastAPI):
    global _load_task
    loop = asyncio.get_running_loop()
    _load_task = asyncio.ensure_future(loop.run_in_executor(None, _load_models))
    _load_task.add_done_callback(
        lambda t: logger.error("Model loading failed: %s", t.exception()) if t.exception() else None
    )
    yield

app = FastAPI(title="VibeVoice Serve", lifespan=lifespan)


class SynthesizeRequest(BaseModel):
    text: str
    model: Optional[str] = None
    reference_id: Optional[str] = None
    streaming: Optional[bool] = False


@app.get("/health")
async def health():
    return {
        "status": "ok" if _models else "loading",
        "default_model": DEFAULT_MODEL,
        "loaded_models": list(_models.keys()),
        "enabled_models": ENABLED_MODELS,
    }


@app.post("/tts")
async def synthesize(req: SynthesizeRequest):
    model_name = req.model or DEFAULT_MODEL

    if model_name not in _models:
        if model_name not in ENABLED_MODELS:
            raise HTTPException(status_code=400, detail=f"Model '{model_name}' not enabled. Available: {ENABLED_MODELS}")
        raise HTTPException(status_code=503, detail=f"Model '{model_name}' still loading")

    try:
        loop = asyncio.get_running_loop()
        audio_bytes = await loop.run_in_executor(None, _synthesize_sync, req.text, model_name)

        return StreamingResponse(
            io.BytesIO(audio_bytes),
            media_type="audio/wav",
        )
    except Exception as e:
        logger.error("Synthesis failed: %s", e)
        raise HTTPException(status_code=500, detail=str(e))


def _synthesize_sync(text: str, model_name: str) -> bytes:
    """Run TTS inference (blocking) and return WAV bytes."""
    entry = _models[model_name]
    processor = entry["processor"]
    model = entry["model"]
    gen_config = entry["gen_config"]

    chat = [{"role": "0", "content": [{"type": "text", "text": text}]}]
    inputs = processor.apply_chat_template(
        chat, tokenize=True, return_dict=True,
    ).to(model.device, model.dtype)

    audio = model.generate(**inputs, generation_config=gen_config)

    with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as tmp:
        tmp_path = tmp.name

    try:
        processor.save_audio(audio, tmp_path)
        with open(tmp_path, "rb") as f:
            return f.read()
    finally:
        os.unlink(tmp_path)


if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=3000)
