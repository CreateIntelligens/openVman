"""Gemini transcription protocol pieces shared by streaming and batch ASR.

串流（asr_stream 的 ``gemini-live``）與批次（gemini_live_batch 的 ``gemini-live-batch``）
共用同一份 Live 協定訊息與語言對應，免得兩邊各寫一套、改了一邊忘了另一邊。這裡只放純函式與
常數：不碰 FastAPI、帳號或連線，連線與錯誤處理留在呼叫端。
"""

from __future__ import annotations

import base64
import json
import os
from dataclasses import dataclass

GEMINI_LIVE_URL = (
    "wss://generativelanguage.googleapis.com/ws/"
    "google.ai.generativelanguage.v1beta.GenerativeService.BidiGenerateContent"
)
SAMPLE_RATE = 16000
# 分流代碼 → Gemini languageCodes。台語分流時前台不走串流（Gemini 聽不懂），不必對應。
GEMINI_LANGUAGE_CODES = {
    "zh": "zh-TW",
    "en": "en-US",
    "es": "es-ES",
    "ja": "ja-JP",
    "ko": "ko-KR",
}


def live_model() -> str:
    return os.environ.get("ASR_GEMINI_STREAM_MODEL", "gemini-3.5-transcribe-live")


def default_languages() -> list[str]:
    # 不指定時中文會出簡體；帶 zh-TW 出繁體，英西不受影響（2026-09-23 實測）。
    raw = os.environ.get("ASR_GEMINI_STREAM_LANGUAGES", "zh-TW,en-US,es-ES")
    return [code.strip() for code in raw.split(",") if code.strip()]


def languages_for(routes: list[str]) -> list[str]:
    codes = [GEMINI_LANGUAGE_CODES[route] for route in routes if route in GEMINI_LANGUAGE_CODES]
    return codes or default_languages()


def transcription_config(languages: list[str], vocabulary: list[str] | None = None) -> dict:
    config: dict = {"languageCodes": languages}
    if vocabulary:
        config["customVocabulary"] = vocabulary
    return config


def setup_message(transcription: dict, *, manual_activity: bool = False) -> str:
    setup: dict = {
        "model": f"models/{live_model()}",
        "inputAudioTranscription": transcription,
    }
    if manual_activity:
        # 關掉伺服器端 VAD，改由呼叫端用 activityStart/activityEnd 框出一段話。
        setup["realtimeInputConfig"] = {"automaticActivityDetection": {"disabled": True}}
    return json.dumps({"setup": setup})


def audio_message(chunk: bytes) -> str:
    return json.dumps({"realtimeInput": {"audio": {
        "mimeType": f"audio/pcm;rate={SAMPLE_RATE}",
        "data": base64.b64encode(chunk).decode("ascii"),
    }}})


AUDIO_STREAM_END = json.dumps({"realtimeInput": {"audioStreamEnd": True}})
ACTIVITY_START = json.dumps({"realtimeInput": {"activityStart": {}}})
ACTIVITY_END = json.dumps({"realtimeInput": {"activityEnd": {}}})


@dataclass(frozen=True, slots=True)
class LiveEvent:
    """What one Live server message means for transcription."""

    interim: str = ""
    final: str = ""
    # serverContent.generationComplete / turnComplete：這一段的定稿已經送完。
    generation_complete: bool = False
    # voiceActivity.type：ACTIVITY_START／ACTIVITY_END，其他訊息為空字串。
    voice_activity: str = ""


def parse_setup_reply(raw: str | bytes) -> bool:
    return "setupComplete" in json.loads(raw)


def parse_live_message(raw: str | bytes) -> LiveEvent:
    message = json.loads(raw)
    content = message.get("serverContent") or {}
    return LiveEvent(
        interim=(content.get("interimInputTranscription") or {}).get("text") or "",
        final=(content.get("inputTranscription") or {}).get("text") or "",
        generation_complete=bool(
            content.get("generationComplete") or content.get("turnComplete"),
        ),
        voice_activity=str((message.get("voiceActivity") or {}).get("type") or ""),
    )
