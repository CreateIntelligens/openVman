"""視覺事件定義與判讀解析 — 純邏輯，無 I/O、無模型呼叫。

攝影機是 AI 的眼睛。本模組把「畫面裡有哪些事件」這件事定義成一張
可擴充的表，並負責把 VLM 的 JSON 輸出解析成 {event_key: bool}。
觸發時機（狀態機）見 detect_edges。
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass


@dataclass(frozen=True)
class EventDefinition:
    key: str
    name: str
    question: str
    context_text: str


EventSlot = dict[str, int | bool]
EventState = dict[str, EventSlot]


def _greeting_event(key: str, gender: str, pronoun: str, term: str) -> EventDefinition:
    """以性別差異參數化打招呼事件，避免 female/male 兩份近乎相同的文案複製。"""
    return EventDefinition(
        key=key,
        name=f"{key}_appeared",
        question=(
            f"畫面中是否有{gender}，且看得到臉部（正面才算，五官不清楚沒關係）？"
            "（只拍到背影、或僅手腳、身體局部而完全看不到臉，算否）"
        ),
        context_text=(
            f"[視覺打招呼] 畫面中出現一位{gender}訪客。"
            "這是 kiosk 主動打招呼觸發，不是使用者提問。"
            f"請只用一句自然親切的開場招呼，稱呼{pronoun}為「{term}」。"
            f"不要詢問{pronoun}在哪裡，不要提海釣或釣場安全。"
        ),
    )


EVENT_DEFINITIONS: list[EventDefinition] = [
    _greeting_event("female", "女性", "她", "美女"),
    _greeting_event("male", "男性", "他", "帥哥"),
    EventDefinition(
        key="fire",
        name="fire_detected",
        question="畫面中是否有火焰或濃煙？",
        context_text="[視覺事件] 畫面中偵測到火焰與煙霧。",
    ),
]
EVENT_DEFINITION_BY_KEY = {event.key: event for event in EVENT_DEFINITIONS}


def build_detection_prompt() -> str:
    lines = [
        "你是數位虛擬人的「眼睛」。請只用 JSON 物件回答以下判讀，",
        "每個欄位皆為布林值，不要加任何說明文字：",
    ]
    for e in EVENT_DEFINITIONS:
        lines.append(f'- "{e.key}": {e.question}')
    lines.append('範例：{"' + '": false, "'.join(e.key for e in EVENT_DEFINITIONS) + '": false}')
    return "\n".join(lines)


_JSON_RE = re.compile(r"\{.*\}", re.DOTALL)


def parse_detection(raw: str) -> dict[str, bool]:
    if not raw:
        return {}
    match = _JSON_RE.search(raw)
    if not match:
        return {}
    try:
        data = json.loads(match.group(0))
    except (json.JSONDecodeError, ValueError):
        return {}
    if not isinstance(data, dict):
        return {}
    result: dict[str, bool] = {}
    for e in EVENT_DEFINITIONS:
        value = data.get(e.key)
        if isinstance(value, bool):
            result[e.key] = value
    return result


_CONFIRM_DEFAULT = 3
_RELEASE_DEFAULT = 10


def new_event_state() -> EventState:
    """Per-session event state. Tracks active status and streak counts."""
    return {
        e.key: {"active": False, "true_streak": 0, "false_streak": 0}
        for e in EVENT_DEFINITIONS
    }


def detect_edges(
    state: EventState,
    detection: dict[str, bool],
    *,
    confirm_frames: int = _CONFIRM_DEFAULT,
    release_frames: int = _RELEASE_DEFAULT,
) -> tuple[EventState, list[str]]:
    """Pure edge detector. Returns (new_state, fired_event_keys).

    An event fires on the frame where it reaches `confirm_frames` consecutive
    true readings while currently inactive. It only resets (becoming eligible
    to fire again) after `release_frames` consecutive false readings.

    去重門檻刻意非對稱：`release_frames` 遠大於 `confirm_frames`。VLM 對
    「畫面中是否有臉」這類判讀會抖動（轉頭、低頭、眨眼），若用對稱門檻，
    短暫的 false 誤判就會重置 active，使人一抬頭就重複觸發、AI 重複打招呼。
    放寬釋放門檻可吸收這種抖動，只有人真的離開夠久才允許再次觸發。
    """
    new_state = {k: dict(v) for k, v in state.items()}
    fired: list[str] = []

    for key, slot in new_state.items():
        present = detection.get(key, False)
        if present:
            slot["true_streak"] = int(slot["true_streak"]) + 1
            slot["false_streak"] = 0
            if not slot["active"] and slot["true_streak"] >= confirm_frames:
                slot["active"] = True
                fired.append(key)
        else:
            slot["false_streak"] = int(slot["false_streak"]) + 1
            slot["true_streak"] = 0
            if slot["active"] and slot["false_streak"] >= release_frames:
                slot["active"] = False

    return new_state, fired


def format_fired_events(fired_keys: list[str]) -> list[dict[str, str]]:
    events: list[dict[str, str]] = []
    for key in fired_keys:
        definition = EVENT_DEFINITION_BY_KEY.get(key)
        if definition is None:
            continue
        events.append(
            {
                "key": key,
                "name": definition.name,
                "context_text": definition.context_text,
            }
        )
    return events
