"""TTS router configuration."""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class TTSRouterConfig(BaseSettings):
    """Immutable TTS router settings loaded from environment."""

    model_config = SettingsConfigDict(
        env_file=Path(__file__).resolve().parents[2] / ".env",
        env_file_encoding="utf-8",
        extra="ignore",
        frozen=True,
        populate_by_name=True,
    )

    # --- Index TTS ---
    tts_index_url: str = ""
    tts_index_character: str = "hayley"

    # --- AWS Polly ---
    tts_aws_enabled: bool = False
    tts_aws_region: str = "ap-northeast-1"
    tts_aws_access_key_id: str = ""
    tts_aws_secret_access_key: str = ""
    tts_aws_polly_voice_id: str = "Zhiyu"
    tts_aws_polly_engine: str = "neural"
    tts_aws_output_format: str = "pcm"
    tts_aws_sample_rate: int = 24000

    # --- GCP Cloud TTS ---
    tts_gcp_enabled: bool = False
    tts_gcp_project_id: str = ""
    tts_gcp_credentials_json: str = ""
    tts_gcp_voice_name: str = "cmn-TW-Standard-A"
    tts_gcp_audio_encoding: str = "LINEAR16"
    tts_gcp_sample_rate: int = 24000

    # --- Edge-TTS (in-process) ---
    edge_tts_enabled: bool = Field(default=True, validation_alias="TTS_EDGE_ENABLED")
    edge_tts_voice: str = Field(
        default="zh-TW-HsiaoChenNeural",
        validation_alias="TTS_EDGE_VOICE",
    )
    edge_tts_sample_rate: int = Field(default=24000, validation_alias="TTS_EDGE_SAMPLE_RATE")
    edge_tts_max_text_length: int = Field(
        default=2000,
        validation_alias="TTS_EDGE_MAX_TEXT_LENGTH",
    )


@lru_cache(maxsize=1)
def get_tts_config() -> TTSRouterConfig:
    """Build config from environment variables (cached)."""
    return TTSRouterConfig()
