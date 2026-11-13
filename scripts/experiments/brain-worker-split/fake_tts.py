"""Local IndexTTS-compatible responder with pre-generated audio and GB10-like timing.

延遲照 2026-09 GB10 實測：串流第一段約 0.3 秒，整句合成約 0.3 秒＋每字 0.12 秒
（2 字 0.54、16 字 2.15、49 字 5.97 秒）。念出來的長度以每字 0.22 秒計。音檔在啟動時
先做好（16 kHz 單聲道 PCM16 的 440 Hz 正弦波），請求進來只是切片送出，不吃 CPU。

FAKE_TTS_MAX_CONCURRENCY 大於 0 時，同時只合成這麼多句、其餘排隊，模擬單一 GPU 節點。
"""

from __future__ import annotations

import asyncio
import math
import os
import struct

from fastapi import FastAPI, Request
from fastapi.responses import Response, StreamingResponse

SAMPLE_RATE = 16000
FIRST_CHUNK_SECONDS = float(os.environ.get("FAKE_TTS_FIRST_CHUNK_SECONDS", "0.3"))
SECONDS_PER_CHAR = float(os.environ.get("FAKE_TTS_SECONDS_PER_CHAR", "0.12"))
AUDIO_SECONDS_PER_CHAR = 0.22
MAX_CONCURRENCY = int(os.environ.get("FAKE_TTS_MAX_CONCURRENCY", "0"))
CHUNK_SECONDS = 0.2

_TONE = b"".join(
    struct.pack("<h", int(8000 * math.sin(2 * math.pi * 440 * i / SAMPLE_RATE)))
    for i in range(SAMPLE_RATE * 30)
)
_slots = asyncio.Semaphore(MAX_CONCURRENCY) if MAX_CONCURRENCY > 0 else None
app = FastAPI()
counts = {"tts": 0, "streams": 0, "peak_active": 0}
_active = 0


def _wav_header(data_bytes: int) -> bytes:
    return b"RIFF" + struct.pack(
        "<I4s4sIHHIIHH4sI", 36 + data_bytes, b"WAVE", b"fmt ", 16, 1, 1,
        SAMPLE_RATE, SAMPLE_RATE * 2, 2, 16, b"data", data_bytes,
    )


def _pcm(text: str) -> bytes:
    seconds = min(30.0, max(0.5, len(text) * AUDIO_SECONDS_PER_CHAR))
    return _TONE[: int(seconds * SAMPLE_RATE) * 2]


class _Slot:
    async def __aenter__(self):
        global _active
        if _slots is not None:
            await _slots.acquire()
        _active += 1
        counts["peak_active"] = max(counts["peak_active"], _active)

    async def __aexit__(self, *exc):
        global _active
        _active -= 1
        if _slots is not None:
            _slots.release()


@app.get("/health")
async def health():
    return {"status": "healthy"}


@app.get("/audio/voices")
async def voices():
    return {"voices": ["fake-voice"]}


@app.get("/stats")
async def stats():
    return counts


@app.post("/tts")
async def tts(request: Request):
    text = str((await request.json()).get("text", ""))
    counts["tts"] += 1
    async with _Slot():
        await asyncio.sleep(FIRST_CHUNK_SECONDS + SECONDS_PER_CHAR * len(text))
    pcm = _pcm(text)
    return Response(_wav_header(len(pcm)) + pcm, media_type="audio/wav")


@app.post("/tts_stream")
async def tts_stream(request: Request):
    text = str((await request.json()).get("text", ""))
    counts["streams"] += 1
    pcm = _pcm(text)
    chunk = int(CHUNK_SECONDS * SAMPLE_RATE) * 2
    pieces = [pcm[i:i + chunk] for i in range(0, len(pcm), chunk)]
    # 第一段之後，剩下的在整句合成時間內平均送完。
    gap = max(0.0, SECONDS_PER_CHAR * len(text)) / max(1, len(pieces))

    async def body():
        async with _Slot():
            await asyncio.sleep(FIRST_CHUNK_SECONDS)
            yield _wav_header(len(pcm)) + pieces[0]
            for piece in pieces[1:]:
                await asyncio.sleep(gap)
                yield piece

    return StreamingResponse(body(), media_type="audio/wav")


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host="0.0.0.0", port=8090, access_log=False)
