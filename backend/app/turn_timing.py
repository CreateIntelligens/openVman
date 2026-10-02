"""Per-turn latency log: from the user speaking to the avatar starting to talk.

前台每一輪記下各個時間點（開始講話、講完、ASR 回來、送出、Brain 回完、TTS 第一段
聲音、開始播放），播放開始後送來這裡，每輪寫一行 JSON 到 logs/turn_timing.jsonl。

寫檔而不是只寫 logger：容器的 stdout 在每次部署重建時就沒了，logs/ 則掛在主機上
（backend/logs），要量整個流程多久時直接 jq 撈。
"""

from __future__ import annotations

import json
import logging
import os
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Literal

from fastapi import APIRouter, Depends, Response, status
from pydantic import BaseModel, ConfigDict, Field

from app.auth.dependencies import CurrentAccount, get_current_account

logger = logging.getLogger("backend.turn_timing")

router = APIRouter(prefix="/api/v1/metrics", tags=["Metrics"])

_DEFAULT_PATH = Path(__file__).resolve().parents[1] / "logs" / "turn_timing.jsonl"
_write_lock = threading.Lock()

TurnMark = Literal[
    "speech_start",
    "speech_end",
    "asr_done",
    "sent",
    "reply_done",
    "tts_start",
    "first_audio",
    "playback_start",
]


class TurnTiming(BaseModel):
    model_config = ConfigDict(extra="forbid")

    turn_id: str = Field(min_length=1, max_length=64)
    input: Literal["voice", "text"]
    # merged：還在等回答時使用者補了一句，前台把兩句合併重送，這一輪由合併後那輪接手。
    outcome: Literal["played", "interrupted", "error", "superseded", "merged"]
    # 前台的牆上時間（第一個時間點），拿來跟其他 log 對時間。
    started_at: str = Field(max_length=40)
    # 各時間點相對第一個時間點的毫秒數。
    marks_ms: dict[TurnMark, float] = Field(max_length=16)
    # 前台算好的分段（例如 asr、brain、tts_first_audio、total），省得撈的人再算。
    durations_ms: dict[str, float] = Field(max_length=16)
    project_id: str = Field(default="", max_length=128)
    session_id: str = Field(default="", max_length=128)
    voice_mode: str = Field(default="", max_length=16)
    asr_engine: str = Field(default="", max_length=32)
    tts_provider: str = Field(default="", max_length=32)
    tts_voice: str = Field(default="", max_length=128)
    reply_chars: int = Field(default=0, ge=0, le=100_000)


def _log_path() -> Path:
    configured = os.environ.get("TURN_TIMING_LOG", "").strip()
    return Path(configured) if configured else _DEFAULT_PATH


def append_turn(record: dict) -> None:
    path = _log_path()
    line = json.dumps(record, ensure_ascii=False)
    with _write_lock:
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("a", encoding="utf-8") as handle:
            handle.write(line + "\n")


@router.post("/turn", status_code=status.HTTP_204_NO_CONTENT)
def record_turn(
    body: TurnTiming,
    current: CurrentAccount = Depends(get_current_account),
) -> Response:
    record = {
        "received_at": datetime.now(timezone.utc).isoformat(timespec="milliseconds"),
        "user_id": current.user.id,
        "username": current.user.username,
        **body.model_dump(),
    }
    try:
        append_turn(record)
    except OSError as exc:
        # 量測失敗不該影響對話；前台也不等這個回應。
        logger.warning("turn_timing_write_failed err=%s", exc)
    return Response(status_code=status.HTTP_204_NO_CONTENT)
