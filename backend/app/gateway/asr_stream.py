"""Streaming ASR over Gemini transcribe-live or Confucius4-R2T2.

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
帳號依偏好使用被授權的 ``gemini-live``、``r2t2-live`` 或 ``r2t2-dev-live``（.35 測試機）。R2T2 帶專案詞表，
增量累加、整句 final_text 轉繁體，不問 Jev；台語分流時前台不走這裡，
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
from collections.abc import AsyncIterator, Callable
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from uuid import uuid4

import anyio
import websockets
from fastapi import APIRouter, HTTPException, WebSocket, WebSocketDisconnect

from app import language_routes as language_routes_mod
from app.asr_glossary import project_asr_prompt
from app.auth.asr_selection import permitted_asr_preference
from app.auth.dependencies import CurrentAccount, authenticate_websocket
from app.auth.runtime import get_auth_runtime
from app.config import TTSRouterConfig, get_tts_config
from app.http_client import SharedAsyncClient
from app.usage_ledger_client import (
    UNIT_SECONDS,
    record_usage_event,
    usage_scope_for,
)
from app.utils.chinese import convert_to_traditional

logger = logging.getLogger("gateway.asr_stream")
router = APIRouter()

GEMINI_STREAM_ASR_ENGINE = "gemini-live"
R2T2_STREAM_ASR_ENGINE = "r2t2-live"
# .35 測試機（vLLM 版）：帳號自己選了才用，失敗不換台。
R2T2_DEV_STREAM_ASR_ENGINE = "r2t2-dev-live"
_R2T2_STREAM_ENGINES = {R2T2_STREAM_ASR_ENGINE, R2T2_DEV_STREAM_ASR_ENGINE}
_STREAM_ENGINES = {GEMINI_STREAM_ASR_ENGINE, *_R2T2_STREAM_ENGINES}
_R2T2_CHUNK_BYTES = 5120
# 指定正確語言時 .37、.35 五種語言各 3 句全對；.37 不會自己判斷（zhen 也當 Chinese，西日韓
# 會被當成中文解碼），.35 的 zhen 能自己分中英西、日文不行（2026-10-05 實測）。
_R2T2_LANGUAGES = {
    "zh": "Chinese", "en": "English", "es": "Spanish", "ja": "Japanese", "ko": "Korean",
}
_R2T2_CHINESE = "Chinese"
# 多種語言時交給 R2T2 自己判斷：.35 會分中英西，.37 當中文（中英夾雜照樣聽得懂）。
_R2T2_AUTO = "zhen"
_R2T2_EOS = "YOUDAO_ONETIME_ASR_STREAM_EOS"
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


def _allowed(current) -> str:
    """Resolve the account's selected streaming engine against current grants."""
    if current.embed_key is not None:
        return ""
    runtime = get_auth_runtime()
    stored = runtime.account_access.get_asr_provider(current.user.id)
    chosen = permitted_asr_preference(runtime, current.user, stored)
    return chosen if chosen in _STREAM_ENGINES else ""


def _r2t2_stream_endpoint(cfg: TTSRouterConfig, engine: str) -> tuple[str, str] | None:
    """URL and key for this R2T2 streaming engine, or None when it is not configured."""
    url, key = (
        (cfg.asr_r2t2_dev_stream_url, cfg.asr_r2t2_dev_secret_key)
        if engine == R2T2_DEV_STREAM_ASR_ENGINE
        else (cfg.asr_r2t2_stream_url, cfg.asr_r2t2_secret_key)
    )
    return (url, key) if url and key else None


def _r2t2_language(routes: list[str]) -> str:
    """The language R2T2 should decode this connection in, from its effective routes."""
    spoken = [route for route in routes if route != language_routes_mod.TAIWANESE]
    if len(spoken) == 1:
        return _R2T2_LANGUAGES.get(spoken[0], _R2T2_CHINESE)
    return _R2T2_AUTO


@asynccontextmanager
async def _r2t2_upstream(
    url: str, key: str, prompt: str, language: str = _R2T2_CHINESE,
) -> AsyncIterator[Any]:
    """Connect and hand-shake with one R2T2 host; .37 與 .35 用同一套握手。"""
    async with websockets.connect(url, max_size=4 * 1024 * 1024, open_timeout=10) as upstream:
        await upstream.send(json.dumps({
            "requestId": str(uuid4()),
            "language": language,
            "use_vad": True,
            "secret_key": key,
            "system_prompt": prompt,
        }))
        first = json.loads(await asyncio.wait_for(upstream.recv(), 10))
        if first.get("status") != "connected":
            raise RuntimeError("R2T2 handshake rejected")
        yield upstream


async def _relay_r2t2(
    websocket: WebSocket,
    current: CurrentAccount,
    project_id: str,
    endpoint: tuple[str, str],
    count_audio: Callable[[int], None],
    routes: list[str],
) -> None:
    prompt = await project_asr_prompt(current, project_id)
    language = _r2t2_language(routes)
    # R2T2 中文輸出簡體才要轉繁；指定日文時轉了會把「学校」改成「學校」。
    display = (
        convert_to_traditional if language in (_R2T2_CHINESE, _R2T2_AUTO) else str
    )
    async with _r2t2_upstream(*endpoint, prompt, language) as upstream:
        await websocket.send_json({"type": "ready"})
        ended = asyncio.Event()

        async def client_to_r2t2() -> None:
            buffer = bytearray()
            while True:
                message = await websocket.receive()
                if message.get("type") == "websocket.disconnect":
                    return
                if chunk := message.get("bytes"):
                    count_audio(len(chunk))
                    buffer.extend(chunk)
                    while len(buffer) >= _R2T2_CHUNK_BYTES:
                        await upstream.send(bytes(buffer[:_R2T2_CHUNK_BYTES]))
                        del buffer[:_R2T2_CHUNK_BYTES]
                elif (text := message.get("text")) and json.loads(text).get("type") == "end":
                    if buffer:
                        await upstream.send(
                            bytes(buffer).ljust(_R2T2_CHUNK_BYTES, b"\0"),
                        )
                        buffer.clear()
                    ended.set()
                    await upstream.send(_R2T2_EOS)
                    # Keep receiving until the client disconnects so EOS finals survive.
                    # The frontend owns the five-second final drain timeout.

        async def r2t2_to_client() -> None:
            accumulated = ""
            async for raw in upstream:
                response = json.loads(raw)
                if response.get("status") != "success":
                    raise RuntimeError("R2T2 transcription failed")
                body = response.get("msg") or {}
                accumulated += body.get("text") or ""
                if body.get("reset"):
                    text = display(body.get("final_text") or accumulated).strip()
                    if text:
                        await websocket.send_json({"type": "final", "text": text})
                    accumulated = ""
                elif body.get("text"):
                    await websocket.send_json({
                        "type": "interim",
                        "text": display(accumulated),
                    })
            if not ended.is_set():
                raise RuntimeError("R2T2 upstream closed")

        tasks = [
            asyncio.create_task(client_to_r2t2()),
            asyncio.create_task(r2t2_to_client()),
        ]
        try:
            done, _ = await asyncio.wait(tasks, return_when=asyncio.FIRST_COMPLETED)
            for task in done:
                task.result()
        finally:
            for task in tasks:
                if not task.done():
                    task.cancel()
            with anyio.CancelScope(shield=True):
                await asyncio.gather(*tasks, return_exceptions=True)


@router.websocket("/api/v1/asr/stream")
async def asr_stream(websocket: WebSocket) -> None:
    try:
        current = authenticate_websocket(websocket, get_auth_runtime())
    except HTTPException:
        await websocket.close(code=1008, reason="authentication required")
        return
    await websocket.accept()

    engine = _allowed(current)
    api_key = os.environ.get("GEMINI_API_KEY", "")
    cfg = get_tts_config()
    endpoint = _r2t2_stream_endpoint(cfg, engine) if engine in _R2T2_STREAM_ENGINES else None
    configured = bool(endpoint) if engine in _R2T2_STREAM_ENGINES else bool(api_key)
    if not engine or not configured:
        await websocket.send_json({
            "type": "error",
            "code": "not_allowed" if not engine else "not_configured",
        })
        await websocket.close()
        return

    project_id = websocket.query_params.get("project_id", "")
    routes = await _project_routes(
        current, project_id, websocket.query_params.get("language_routes"),
    )
    languages = _gemini_languages(routes)
    audio_bytes = 0
    started = time.monotonic()

    def count_audio(size: int) -> None:
        nonlocal audio_bytes
        audio_bytes += size

    try:
        if endpoint:
            await _relay_r2t2(
                websocket, current, project_id, endpoint, count_audio, routes,
            )
            await websocket.close()
            return
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
                provider=(
                    engine if engine in _R2T2_STREAM_ENGINES
                    else "gemini-transcribe-live"
                ),
                model=(
                    "Confucius4-R2T2" if engine in _R2T2_STREAM_ENGINES
                    else _model()
                ),
                kind="asr",
                unit_type=UNIT_SECONDS,
                units=round(seconds, 2),
                scope=usage_scope_for(current, channel="ws"),
                raw={"streaming": True, "wall_seconds": round(time.monotonic() - started, 1)},
            )
