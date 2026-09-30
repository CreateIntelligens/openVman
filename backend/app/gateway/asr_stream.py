"""Streaming ASR over Gemini transcribe-live.

前台邊錄邊送 16 kHz 單聲道 PCM16（binary frame），這裡轉給 Gemini 的
gemini-3.5-transcribe-live，把轉錄推回前台：

- ``{"type": "ready"}``：Gemini 連好了，可以開始送音訊。
- ``{"type": "interim", "text": ...}``：講話中的暫定結果（約每 0.5 秒）。
- ``{"type": "final", "text": ...}``：一句定稿。Gemini 自己判斷講完（停頓約 0.5 秒），
  不用前台送結束訊號，同一條連線可以連續講好幾句。
- ``{"type": "error", "code": ...}``：無法使用，前台退回批次 ASR。

語言提示依專案的語言分流產生（前台帶 ``project_id``、``language_routes``），以後開日韓
專案不用改這裡。定稿偶爾比講話中的暫定字幕還差（「who am i」定稿成「OMI」、定稿成
韓文）：兩者不同時問 Brain（Jev）送哪個，逾時或失敗照定稿；每次都在
``backend/logs/asr_final_judge.jsonl`` 記一行，之後拿真實資料驗證準度（正式環境
docker logs 看不到 logger.info，所以寫檔，跟 turn_timing 一樣）。

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
import threading
import time
from datetime import datetime, timezone
from pathlib import Path

import anyio
import websockets
from fastapi import APIRouter, HTTPException, WebSocket, WebSocketDisconnect

from app import language_routes as language_routes_mod
from app.auth.asr_selection import permitted_asr_preference
from app.auth.dependencies import authenticate_websocket
from app.auth.runtime import get_auth_runtime
from app.config import get_tts_config
from app.http_client import SharedAsyncClient
from app.usage_ledger_client import UNIT_SECONDS, record_usage_event, usage_scope_for

logger = logging.getLogger("gateway.asr_stream")
router = APIRouter()

GEMINI_STREAM_ASR_ENGINE = "gemini-live"
_GEMINI_LIVE_URL = (
    "wss://generativelanguage.googleapis.com/ws/"
    "google.ai.generativelanguage.v1beta.GenerativeService.BidiGenerateContent"
)
_SAMPLE_RATE = 16000
# 分流代碼 → Gemini languageCodes。台語分流時前台不走串流（Gemini 聽不懂），不必對應。
_GEMINI_LANGUAGE_CODES = {
    "zh": "zh-TW",
    "en": "en-US",
    "es": "es-ES",
    "ja": "ja-JP",
    "ko": "ko-KR",
}
# Brain 那邊 Jev 最多等 1 秒；這裡多留一點往返時間。使用者在等這句送出。
_JUDGE_TIMEOUT_SECONDS = 1.5
_INTERNAL_TOKEN_HEADER = "X-Internal-Token"
_http = SharedAsyncClient(connect=2, read=_JUDGE_TIMEOUT_SECONDS)
_JUDGE_LOG_DEFAULT = Path(__file__).resolve().parents[2] / "logs" / "asr_final_judge.jsonl"
_judge_log_lock = threading.Lock()


def _append_judge_log(record: dict) -> None:
    configured = os.environ.get("ASR_FINAL_JUDGE_LOG", "").strip()
    path = Path(configured) if configured else _JUDGE_LOG_DEFAULT
    try:
        with _judge_log_lock:
            path.parent.mkdir(parents=True, exist_ok=True)
            with path.open("a", encoding="utf-8") as handle:
                handle.write(json.dumps(record, ensure_ascii=False) + "\n")
    except OSError as exc:
        logger.warning("asr_final_judge_log_failed err=%s", exc)


def _model() -> str:
    return os.environ.get("ASR_GEMINI_STREAM_MODEL", "gemini-3.5-transcribe-live")


def _languages() -> list[str]:
    # 不指定時中文會出簡體；帶 zh-TW 出繁體，英西不受影響（2026-09-23 實測）。
    raw = os.environ.get("ASR_GEMINI_STREAM_LANGUAGES", "zh-TW,en-US,es-ES")
    return [code.strip() for code in raw.split(",") if code.strip()]


def _gemini_languages(routes: list[str]) -> list[str]:
    codes = [_GEMINI_LANGUAGE_CODES[route] for route in routes if route in _GEMINI_LANGUAGE_CODES]
    return codes or _languages()


async def _project_routes(current, project_id: str, requested: str | None) -> list[str]:
    """This connection's routes: the admin's, narrowed by the client's toggles; [] if unknown."""
    if not project_id:
        return []
    try:
        return await language_routes_mod.effective_routes(
            current, project_id, language_routes_mod.parse_requested(requested),
        )
    except Exception as exc:  # noqa: BLE001 - 查不到分流就用部署預設，不擋收音
        logger.warning("asr stream language routes failed: %s", exc)
        return []


async def _judge_final(project_id: str, routes: list[str], interim: str, final: str) -> str:
    """Ask Brain whether the last interim beats the final; the final on any doubt."""
    cfg = get_tts_config()
    started = time.monotonic()
    try:
        response = await _http.get().post(
            f"{cfg.brain_url.rstrip('/')}/brain/internal/asr-judge",
            # 語言跟著這條連線實際生效的分流走（前台可以臨時關掉某個語言），不是只看後台設定。
            json={
                "project_id": project_id or "default",
                "languages": routes or None,
                "interim": interim,
                "final": final,
            },
            headers={_INTERNAL_TOKEN_HEADER: cfg.gateway_internal_token},
            timeout=_JUDGE_TIMEOUT_SECONDS,
        )
        response.raise_for_status()
        verdict = response.json()
    except Exception as exc:  # noqa: BLE001 - 判斷不了就照定稿
        verdict = {"text": final, "chosen": "final", "reason": f"error:{type(exc).__name__}"}
    text = str(verdict.get("text") or final).strip()
    _append_judge_log({
        "at": datetime.now(timezone.utc).isoformat(timespec="milliseconds"),
        "project_id": project_id,
        "languages": routes,
        "interim": interim,
        "final": final,
        "chosen": verdict.get("chosen"),
        "scores": verdict.get("scores"),
        "reason": verdict.get("reason"),
        "ms": round((time.monotonic() - started) * 1000),
    })
    return text


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

    project_id = websocket.query_params.get("project_id", "")
    routes = await _project_routes(
        current, project_id, websocket.query_params.get("language_routes"),
    )
    languages = _gemini_languages(routes)
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
                "inputAudioTranscription": {"languageCodes": languages},
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
                last_interim = ""
                async for raw in upstream:
                    content = json.loads(raw).get("serverContent") or {}
                    if text := (content.get("interimInputTranscription") or {}).get("text"):
                        last_interim = text
                        await websocket.send_json({"type": "interim", "text": text})
                    if text := (content.get("inputTranscription") or {}).get("text"):
                        final = text.strip()
                        if last_interim.strip() and last_interim.strip() != final:
                            final = await _judge_final(project_id, routes, last_interim.strip(), final)
                        last_interim = ""
                        await websocket.send_json({"type": "final", "text": final})

            tasks = [
                asyncio.create_task(client_to_gemini()),
                asyncio.create_task(gemini_to_client()),
            ]
            try:
                done, _pending = await asyncio.wait(
                    tasks, return_when=asyncio.FIRST_COMPLETED,
                )
                for task in done:
                    task.result()
                if tasks[1] in done and tasks[0] not in done:
                    raise RuntimeError("ASR upstream closed")
            finally:
                # Leave no receiver using a socket after its context closes.
                for task in tasks:
                    if not task.done():
                        task.cancel()
                with anyio.CancelScope(shield=True):
                    await asyncio.gather(*tasks, return_exceptions=True)
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
