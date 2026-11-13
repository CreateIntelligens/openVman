"""Answer "is this utterance Taiwanese?" quickly with Gemini Decisions.

Gemini Decisions 對「是不是台語」這種問法很模糊（華語也常給 0.4～0.6），
但對「是不是華語／英語／西語」很有把握，所以反過來問：華語、英語、西語、
日語、韓語各一題是非題，一次送出。華語或英西分數高就不是台語；五題都低
才算台語；其他情況（多半是日韓分數偏高，真人台語常被聽成韓語）交給原本
的模型。原本的模型同時送出，Decisions 沒把握或失敗時就等它，所以最壞情況
跟沒開一樣慢。

門檻來自 2026-11-13 的 50 句測試（真人台語連續劇 20 句、合成華語 10 句、
合成英西日韓各 5 句）：Decisions 自己下判斷的句子零誤判，台語 12/20、華語
10/10、英西 10/10 不必等原本的模型；合在一起台語 20/20。華語都是合成語音，
帶台灣腔的真人華語還沒驗證，所以預設關閉。
"""

from __future__ import annotations

import asyncio
import base64
import json
import logging
from time import monotonic
from typing import TYPE_CHECKING, Any

import httpx

from memory import language_detect
from memory.language_detect import TAIWANESE

if TYPE_CHECKING:
    from core.gemini_credentials import GeminiCredential

logger = logging.getLogger(__name__)

_ENDPOINT = "https://generativelanguage.googleapis.com/v1beta/decisions"
_LANGUAGE_NAMES = {
    "zh": "Mandarin Chinese (華語)",
    "en": "English",
    "es": "Spanish",
    "ja": "Japanese",
    "ko": "Korean",
}
_QUESTIONS = {
    code: {"type": "noul", "instructions": f"Is the speaker speaking {name}?"}
    for code, name in _LANGUAGE_NAMES.items()
}
# 真華語 0.82～0.93，真人台語最高 0.76。
_MANDARIN_SURE = 0.8
# 合成英西最低 0.79，真人台語聽成英西最高 0.40。
_LATIN_SURE = 0.75
# 判成台語：華語不超過這個，五題也都低於 _OTHER_LOW。
_MANDARIN_LOW = 0.65
_OTHER_LOW = 0.5

_client: httpx.Client | None = None


def _http() -> httpx.Client:
    global _client
    if _client is None:
        _client = httpx.Client()
    return _client


def verdict(scores: dict[str, float]) -> str | None:
    """The language Decisions is sure about, or None to wait for the slow model."""
    mandarin = scores.get("zh", 0.0)
    latin = max(("en", "es"), key=lambda code: scores.get(code, 0.0))
    if mandarin >= _MANDARIN_SURE:
        return "zh"
    if scores.get(latin, 0.0) >= _LATIN_SURE:
        return latin
    others = (scores.get(code, 0.0) for code in ("en", "es", "ja", "ko"))
    if mandarin <= _MANDARIN_LOW and all(score < _OTHER_LOW for score in others):
        return TAIWANESE
    return None


def ask_decisions(wav_bytes: bytes, credential: GeminiCredential) -> dict[str, float]:
    """One Decisions call; returns each language's yes-probability."""
    from config import get_settings
    from core.usage import LLMUsage, UsageScope, current_usage_scope
    from infra.usage_ledger import record_usage_event

    cfg = get_settings()
    started = monotonic()
    response = _http().post(
        _ENDPOINT,
        json={
            "model": cfg.audio_language_decision_model,
            "input": [{
                "type": "audio",
                "data": base64.b64encode(wav_bytes).decode(),
                "mime_type": "audio/wav",
            }],
            "questions": _QUESTIONS,
        },
        headers={"x-goog-api-key": credential.api_key},
        timeout=cfg.audio_language_decision_timeout_seconds,
    )
    response.raise_for_status()
    body = response.json()
    tokens = int((body.get("usage") or {}).get("total_input_tokens", 0) or 0)
    scope = current_usage_scope() or UsageScope(kind="audio_language")
    record_usage_event(
        provider="gemini", model=cfg.audio_language_decision_model,
        kind="audio_language", scope=scope,
        latency_ms=(monotonic() - started) * 1000,
        usage=LLMUsage(input_tokens=tokens, output_tokens=0, total_tokens=tokens),
        raw=credential.metadata(),
    )
    return {
        code: float(answer["noul"])
        for code, answer in body["answers"].items()
        if code in _QUESTIONS
    }


def _credential(credential: GeminiCredential | None) -> dict[str, Any]:
    return {"credential": credential} if credential is not None else {}


async def detect_audio_language_async(
    wav_bytes: bytes, *, credential: GeminiCredential | None = None,
) -> str:
    """Same answer as detect_audio_language, sooner when Decisions is sure."""
    from config import get_settings

    if not get_settings().audio_language_decision_enabled:
        return await asyncio.to_thread(
            language_detect.detect_audio_language, wav_bytes, **_credential(credential),
        )
    if credential is None:
        from core.gemini_credentials import resolve_gemini_credential

        credential = await asyncio.to_thread(resolve_gemini_credential, None)
    slow = asyncio.ensure_future(
        asyncio.to_thread(language_detect.detect_audio_language, wav_bytes, credential=credential),
    )
    started = monotonic()
    scores: dict[str, Any] = {}
    fast: str | None = None
    try:
        scores = await asyncio.to_thread(ask_decisions, wav_bytes, credential)
        fast = verdict(scores)
    except Exception as exc:  # noqa: BLE001 - Decisions 失敗就等原本的模型
        scores = {"error": type(exc).__name__}
    logger.info(json.dumps({
        "event": "audio_language_decision",
        "scores": {k: round(v, 3) if isinstance(v, float) else v for k, v in scores.items()},
        "verdict": fast,
        "ms": round((monotonic() - started) * 1000),
    }))
    if fast is not None:
        # 原本的模型已經在跑，執行緒取消不了；讓它跑完，只是不等它。
        slow.add_done_callback(lambda task: task.exception())
        return fast
    return await slow
