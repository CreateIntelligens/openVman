import os
import asyncio
import io
import traceback
import tempfile
import uuid
import subprocess
from fastapi import FastAPI, Request, Response, UploadFile, File
from fastapi.responses import JSONResponse, StreamingResponse
from contextlib import asynccontextmanager
from fastapi.middleware.cors import CORSMiddleware
import uvicorn
import argparse
import json
import time
import numpy as np
import soundfile as sf

from indextts.infer_vllm import IndexTTS

# Pre-compile BigVGAN CUDA kernels at import time (main thread).
# cpp_extension.load() uses ninja and hangs in background threads.
# Remove stale lock files left behind when the container is killed.
_cuda_build_dir = os.path.join(
    os.path.dirname(__file__),
    "indextts", "BigVGAN", "alias_free_activation", "cuda", "build",
)
_stale_lock = os.path.join(_cuda_build_dir, "lock")
if os.path.isfile(_stale_lock):
    os.remove(_stale_lock)
    print("[IndexTTS] removed stale CUDA build lock", flush=True)

try:
    from indextts.BigVGAN.alias_free_activation.cuda.activation1d import Activation1d as _  # noqa: F401
    print("[IndexTTS] CUDA kernels preloaded", flush=True)
except Exception as _exc:
    print(f"[IndexTTS] CUDA kernel preload skipped: {_exc}", flush=True)

audio_processing_semaphore = asyncio.Semaphore(20)

async def convert_audio_with_ffmpeg(input_data, target_sample_rate=16000):
    cmd = [
        'ffmpeg', '-y',
        '-i', 'pipe:0',
        '-ar', str(target_sample_rate),
        '-ac', '1',
        '-c:a', 'pcm_s16le',
        '-f', 'wav',
        'pipe:1'
    ]
    try:
        process = await asyncio.create_subprocess_exec(
            *cmd,
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE
        )
        stdout, stderr = await process.communicate(input=input_data)
        if process.returncode != 0: return input_data
        return stdout
    except: return input_data

tts = None

_tts_ready = False
_init_task = None


async def _background_init():
    """Initialize TTS engine in a background thread.

    CUDA kernels are pre-compiled on the main thread before this runs.
    Port binding happens immediately (lifespan yields right away).
    Health endpoint returns 503 until _tts_ready is True.
    """
    import concurrent.futures
    import threading

    global tts, _tts_ready

    engine_future: concurrent.futures.Future = concurrent.futures.Future()

    def _worker():
        try:
            cfg_path = os.path.join(args.model_dir, "config.yaml")
            print("[IndexTTS] calling IndexTTS()...", flush=True)
            engine = IndexTTS(
                model_dir=args.model_dir,
                cfg_path=cfg_path,
                gpu_memory_utilization=args.gpu_memory_utilization,
            )
            print("[IndexTTS] engine loaded", flush=True)

            cur_dir = os.path.dirname(os.path.abspath(__file__))
            speaker_path = os.path.join(cur_dir, "assets/speaker.json")
            if os.path.exists(speaker_path):
                with open(speaker_path, "r") as f:
                    speaker_dict = json.load(f)
                for speaker, audio_paths in speaker_dict.items():
                    audio_paths_ = [os.path.join(cur_dir, p) for p in audio_paths]
                    engine.registry_speaker(speaker, audio_paths_)
                print("[IndexTTS] speakers registered", flush=True)

            engine_future.set_result(engine)
        except Exception as exc:
            traceback.print_exc()
            engine_future.set_exception(exc)

    thread = threading.Thread(target=_worker, daemon=True)
    thread.start()

    while not engine_future.done():
        await asyncio.sleep(1)

    tts = engine_future.result()
    _tts_ready = True
    print("[IndexTTS] ready, accepting requests", flush=True)


@asynccontextmanager
async def lifespan(app: FastAPI):
    global _init_task
    _init_task = asyncio.create_task(_background_init())
    yield
    if _init_task and not _init_task.done():
        _init_task.cancel()

app = FastAPI(lifespan=lifespan)
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_credentials=True, allow_methods=["*"], allow_headers=["*"])

def wav_to_bytes(wav_data, sampling_rate):
    with io.BytesIO() as wav_buffer:
        sf.write(wav_buffer, wav_data, sampling_rate, format='WAV')
        return wav_buffer.getvalue()

@app.get("/health")
async def health_check():
    if not _tts_ready:
        return JSONResponse(status_code=503, content={"status": "initializing", "timestamp": time.time()})
    return JSONResponse(status_code=200, content={"status": "healthy", "timestamp": time.time()})

async def _tts_response(sr: int, wav) -> Response:
    async with audio_processing_semaphore:
        wav_bytes = await asyncio.to_thread(wav_to_bytes, wav, sr)
        wav_bytes_16k = await convert_audio_with_ffmpeg(wav_bytes)
    return Response(content=wav_bytes_16k, media_type="audio/wav")

@app.post("/tts_url")
async def tts_api_url(request: Request):
    if not _tts_ready:
        return JSONResponse(status_code=503, content={"status": "initializing"})
    try:
        data = await request.json()
        sr, wav = await tts.infer(data["audio_paths"], data["text"], seed=data.get("seed", 8))
        return await _tts_response(sr, wav)
    except Exception as ex: return JSONResponse(status_code=500, content={"status": "error", "error": str(ex)})

@app.post("/tts")
async def tts_api(request: Request):
    if not _tts_ready:
        return JSONResponse(status_code=503, content={"status": "initializing"})
    try:
        data = await request.json()
        sr, wav = await tts.infer_with_ref_audio_embed(data["character"], data["text"])
        return await _tts_response(sr, wav)
    except Exception as ex: return JSONResponse(status_code=500, content={"status": "error", "error": str(ex)})

_voices_cache: list | dict | None = None

@app.get("/audio/voices")
async def tts_voices():
    global _voices_cache
    if _voices_cache is not None:
        return _voices_cache
    speaker_path = os.path.join(os.path.dirname(__file__), "assets/speaker.json")
    if os.path.exists(speaker_path):
        with open(speaker_path, 'r') as f:
            _voices_cache = json.load(f)
        return _voices_cache
    return []

if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--host", type=str, default="0.0.0.0")
    parser.add_argument("--port", type=int, default=11996)
    parser.add_argument("--model_dir", type=str, default="/path/to/IndexTeam/Index-TTS")
    parser.add_argument("--gpu_memory_utilization", type=float, default=0.1)
    args = parser.parse_args()
    uvicorn.run(app=app, host=args.host, port=args.port)
