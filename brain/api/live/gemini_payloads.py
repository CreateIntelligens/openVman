"""Gemini setup payload and PCM encoding, independent of session state."""

from __future__ import annotations

import logging
import json
import re
from typing import Any

from core.turn_decisions import TurnDecision

from config import BrainSettings

from .gemini_tools import build_gemini_tool_declarations


logger = logging.getLogger("brain.live.gemini_payloads")
_PCM_RATE_RE = re.compile(r"rate=(\d+)")


def _supports_thinking_level(model: str) -> bool:
    """Whether a Live model accepts generationConfig.thinkingConfig.

    3.8 起 thinkingLevel 只留在 extended-thinking 變體；一般的 gemini-3.8-live
    收到這個欄位會直接報錯。3.1 preview 兩者都吃。
    """
    name = model.strip().removeprefix("models/")
    if name.startswith("gemini-3.1-"):
        return True
    return "extended-thinking" in name


def build_setup_message(
    config: BrainSettings, system_instruction: str
) -> dict[str, Any]:
    setup: dict[str, Any] = {
        "model": f"models/{config.live_gemini_model}",
        "generationConfig": {"responseModalities": ["AUDIO"]},
    }
    # gemini-3.8-live 不支援 thinkingLevel，帶了會被拒絕；extended-thinking
    # 變體才吃這個欄位，所以依模型決定要不要送，而不是無條件帶上。
    thinking_level = config.live_gemini_thinking_level.strip()
    if thinking_level and _supports_thinking_level(config.live_gemini_model):
        setup["generationConfig"]["thinkingConfig"] = {
            "thinkingLevel": thinking_level,
        }
    elif thinking_level:
        logger.warning(
            "ignoring live_gemini_thinking_level=%r: %s does not accept it",
            thinking_level,
            config.live_gemini_model,
        )
    instruction = (
        system_instruction.strip()
        or config.live_gemini_system_instruction.strip()
    )
    if instruction:
        setup["systemInstruction"] = {"parts": [{"text": instruction}]}
    # 不指定語言時中文轉錄回傳簡體；languageCodes 讓 Gemini 直接吐繁體
    # （2026-09-23 實測；單數 languageCode 會被拒）。
    transcription: dict[str, Any] = {}
    languages = [
        code.strip()
        for code in str(
            getattr(config, "live_gemini_transcription_languages", "")
        ).split(",")
        if code.strip()
    ]
    if languages:
        transcription["languageCodes"] = languages
    if config.live_gemini_output_audio_transcription:
        setup["outputAudioTranscription"] = dict(transcription)
    setup["inputAudioTranscription"] = dict(transcription)
    if config.live_gemini_tools_enabled:
        setup["tools"] = [
            {"functionDeclarations": build_gemini_tool_declarations()}
        ]

    # Without compression Gemini Live caps a session at 15 min (audio) or
    # 2 min (audio+video), then drops the socket with 1008. A sliding
    # window lifts that cap so video sessions survive past ~2 min.
    if config.live_gemini_context_compression:
        setup["contextWindowCompression"] = {"slidingWindow": {}}

    return setup


def parse_sample_rate(mime_type: str) -> int:
    match = _PCM_RATE_RE.search(mime_type)
    if not match:
        return 24000
    return int(match.group(1))


def pcm_to_wav(pcm_bytes: bytes, sample_rate: int) -> bytes:
    data_size = len(pcm_bytes)
    chunk_size = 36 + data_size
    byte_rate = sample_rate * 2
    block_align = 2
    header = b"".join(
        [
            b"RIFF",
            chunk_size.to_bytes(4, "little"),
            b"WAVE",
            b"fmt ",
            (16).to_bytes(4, "little"),
            (1).to_bytes(2, "little"),
            (1).to_bytes(2, "little"),
            sample_rate.to_bytes(4, "little"),
            byte_rate.to_bytes(4, "little"),
            block_align.to_bytes(2, "little"),
            (16).to_bytes(2, "little"),
            b"data",
            data_size.to_bytes(4, "little"),
        ]
    )
    return header + pcm_bytes


def build_user_turn_message(
    user_text: str, decision: TurnDecision | None, prefetched_reads: dict[str, dict[str, Any]],
) -> dict[str, Any]:
    """Build the bounded trusted decision envelope for a finalized text turn."""
    text = user_text
    if decision is not None and decision.source != "baseline":
        policy = decision.policy
        required_reads = [
            name for name, required in (
                ("search_knowledge", policy.needs_knowledge is True),
                ("search_web", policy.needs_web is True),
                ("search_memory", policy.needs_memory is True),
            ) if required and name not in prefetched_reads
        ]
        prefetched = [
            {
                "name": name,
                "result": json.dumps(result, ensure_ascii=False)[:4_000],
                "trust_boundary": "untrusted_reference_data",
            }
            for name, result in prefetched_reads.items()
        ]
        text = json.dumps({
            "openvman_turn_envelope": 1,
            "policy": policy.to_prompt_fields(),
            "required_reads": required_reads,
            "satisfied_reads": sorted(prefetched_reads),
            "prefetched_reads": prefetched,
            "user_text": user_text,
        }, ensure_ascii=False)
    return {"realtimeInput": {"text": text}}
