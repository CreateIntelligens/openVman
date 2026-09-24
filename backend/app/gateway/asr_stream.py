"""Streaming ASR over Gemini transcribe-live.

前台邊錄邊送 16 kHz 單聲道 PCM16（binary frame），這裡轉給 Gemini 的
gemini-3.5-transcribe-live，把轉錄推回前台：

- ``{"type": "ready"}``：Gemini 連好了，可以開始送音訊。
- ``{"type": "interim", "text": ...}``：講話中的暫定結果（約每 0.5 秒）。
- ``{"type": "final", "text": ...}``：一句定稿。Gemini 自己判斷講完（停頓約 0.5 秒），
  不用前台送結束訊號，同一條連線可以連續講好幾句。
- ``{"type": "error", "code": ...}``：無法使用，前台退回批次 ASR。

跟瀏覽器內建辨識一樣是前台直接驅動的引擎，不進 transcribe() 的 fallback chain；
帳號要被授權 ``gemini-live`` 才能用。台語分流時前台不走這裡（Gemini 聽不懂台語），
改用 Breeze 批次。
"""

from __future__ import annotations

import asyncio
import base64
import json
import logging
import os
import time

import websockets
from fastapi import APIRouter, HTTPException, WebSocket, WebSocketDisconnect

from app.auth.asr_selection import permitted_asr_preference
from app.auth.dependencies import authenticate_websocket
from app.auth.runtime import get_auth_runtime
from app.usage_ledger_client import UNIT_SECONDS, record_usage_event, usage_scope_for

logger = logging.getLogger("gateway.asr_stream")
router = APIRouter()

GEMINI_STREAM_ASR_ENGINE = "gemini-live"
_GEMINI_LIVE_URL = (
    "wss://generativelanguage.googleapis.com/ws/"
    "google.ai.generativelanguage.v1beta.GenerativeService.BidiGenerateContent"
)
_SAMPLE_RATE = 16000


def _model() -> str:
    return os.environ.get("ASR_GEMINI_STREAM_MODEL", "gemini-3.5-transcribe-live")


def _languages() -> list[str]:
    # 不指定時中文會出簡體；帶 zh-TW 出繁體，英西不受影響（2026-09-23 實測）。
    raw = os.environ.get("ASR_GEMINI_STREAM_LANGUAGES", "zh-TW,en-US,es-ES")
    return [code.strip() for code in raw.split(",") if code.strip()]


def _allowed(current) -> bool:
    """嵌入金鑰沒有帳號授權，一律不給；帳號要被授權 gemini-live（ROOT 全開）。"""
    if current.embed_key is not None:
        return False
    runtime = get_auth_runtime()
    chosen = permitted_asr_preference(runtime, current.user, GEMINI_STREAM_ASR_ENGINE)
    return chosen == GEMINI_STREAM_ASR_ENGINE


@router.websocket("/api/v1/asr/stream")
async def asr_stream(websocket: WebSocket) -> None:
    try:
        current = authenticate_websocket(websocket, get_auth_runtime())
    except HTTPException:
        await websocket.close(code=1008, reason="authentication required")
        return
    await websocket.accept()

    api_key = os.environ.get("GEMINI_API_KEY", "")
    if not api_key or not _allowed(current):
        await websocket.send_json({"type": "error", "code": "not_allowed" if api_key else "not_configured"})
        await websocket.close()
        return

    audio_bytes = 0
    started = time.monotonic()
    try:
        async with websockets.connect(
            _GEMINI_LIVE_URL,
            additional_headers={"x-goog-api-key": api_key},
            max_size=4 * 1024 * 1024,
            open_timeout=10,
        ) as upstream:
            await upstream.send(json.dumps({"setup": {
                "model": f"models/{_model()}",
                "inputAudioTranscription": {"languageCodes": _languages()},
            }}))
            first = json.loads(await asyncio.wait_for(upstream.recv(), 10))
            if "setupComplete" not in first:
                raise RuntimeError(f"setup rejected: {str(first)[:120]}")
            await websocket.send_json({"type": "ready"})

            async def client_to_gemini() -> None:
                nonlocal audio_bytes
                while True:
                    message = await websocket.receive()
                    if message.get("type") == "websocket.disconnect":
                        return
                    if chunk := message.get("bytes"):
                        audio_bytes += len(chunk)
                        await upstream.send(json.dumps({"realtimeInput": {"audio": {
                            "mimeType": f"audio/pcm;rate={_SAMPLE_RATE}",
                            "data": base64.b64encode(chunk).decode("ascii"),
                        }}}))
                    elif (text := message.get("text")) and json.loads(text).get("type") == "end":
                        # 前台停止收音：讓 Gemini 把手上的句子定稿。
                        await upstream.send(json.dumps({"realtimeInput": {"audioStreamEnd": True}}))

            async def gemini_to_client() -> None:
                async for raw in upstream:
                    content = json.loads(raw).get("serverContent") or {}
                    if text := (content.get("interimInputTranscription") or {}).get("text"):
                        await websocket.send_json({"type": "interim", "text": text})
                    if text := (content.get("inputTranscription") or {}).get("text"):
                        await websocket.send_json({"type": "final", "text": text.strip()})

            tasks = [
                asyncio.create_task(client_to_gemini()),
                asyncio.create_task(gemini_to_client()),
            ]
            _done, pending = await asyncio.wait(tasks, return_when=asyncio.FIRST_COMPLETED)
            for task in pending:
                task.cancel()
    except WebSocketDisconnect:
        pass
    except Exception as exc:  # noqa: BLE001 - 上游失敗時讓前台退回批次 ASR
        logger.warning("asr stream failed: %s", exc)
        try:
            await websocket.send_json({"type": "error", "code": "upstream_failed"})
            await websocket.close()
        except Exception:  # noqa: BLE001
            pass
    finally:
        seconds = audio_bytes / (2 * _SAMPLE_RATE)
        if seconds > 0:
            record_usage_event(
                provider="gemini-transcribe-live",
                model=_model(),
                kind="asr",
                unit_type=UNIT_SECONDS,
                units=round(seconds, 2),
                scope=usage_scope_for(current, channel="ws"),
                raw={"streaming": True, "wall_seconds": round(time.monotonic() - started, 1)},
            )
