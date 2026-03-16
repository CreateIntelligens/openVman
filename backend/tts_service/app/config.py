"""Edge-TTS worker configuration."""

from __future__ import annotations

import os
from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class TTSWorkerConfig:
    """Immutable TTS worker settings loaded from environment."""

    voice: str = "zh-TW-HsiaoChenNeural"
    sample_rate: int = 24000
    max_text_length: int = 2000
    port: int = 9000


def get_worker_config() -> TTSWorkerConfig:
    """Build config from environment variables."""
    return TTSWorkerConfig(
        voice=os.environ.get("TTS_VOICE", "zh-TW-HsiaoChenNeural"),
        sample_rate=int(os.environ.get("TTS_SAMPLE_RATE", "24000")),
        max_text_length=int(os.environ.get("TTS_MAX_TEXT_LENGTH", "2000")),
        port=int(os.environ.get("TTS_PORT", "9000")),
    )
