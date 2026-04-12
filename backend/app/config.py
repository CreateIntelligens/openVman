"""openVman backend configuration."""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict

_BACKEND_ENV_FILE = Path(__file__).resolve().parents[1] / ".env"
_DEFAULT_SUPPORTED_TYPES = (
    "image/jpeg,image/png,image/webp,"
    "video/mp4,video/quicktime,"
    "audio/mpeg,audio/wav,"
    "application/pdf,"
    "application/vnd.openxmlformats-officedocument.wordprocessingml.document,"
    "application/vnd.openxmlformats-officedocument.presentationml.presentation,"
    "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
)


def _split_csv_values(raw: str) -> tuple[str, ...]:
    return tuple(item.strip() for item in raw.split(",") if item.strip())


class TTSRouterConfig(BaseSettings):
    """Immutable backend settings loaded from environment."""

    model_config = SettingsConfigDict(
        env_file=_BACKEND_ENV_FILE,
        env_file_encoding="utf-8",
        extra="ignore",
        frozen=True,
        populate_by_name=True,
    )

    # --- Environment ---
    env: str = "prod"
    backend_port: int = Field(default=8200, validation_alias="BACKEND_PORT")

    # --- IndexTTS (primary, voice-cloning) ---
    tts_indextts_url: str = Field(default="", validation_alias="TTS_INDEXTTS_URL")
    tts_indextts_default_character: str = Field(default="", validation_alias="TTS_INDEXTTS_DEFAULT_CHARACTER")

    # --- VibeVoice TTS ---
    tts_vibevoice_url: str = Field(default="", validation_alias="TTS_VIBEVOICE_URL")

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
    markitdown_max_upload_bytes: int = Field(
        default=10 * 1024 * 1024,
        validation_alias="MARKITDOWN_MAX_UPLOAD_BYTES",
    )
    docling_serve_url: str = Field(default="", validation_alias="DOCLING_SERVE_URL")
    docling_timeout_ms: int = Field(default=5000, validation_alias="DOCLING_TIMEOUT_MS")
    docling_api_key: str = Field(default="", validation_alias="DOCLING_API_KEY")
    docling_fallback_to_markitdown: bool = Field(
        default=True,
        validation_alias="DOCLING_FALLBACK_TO_MARKITDOWN",
    )

    # --- TTS Cache ---
    tts_cache_enabled: bool = Field(default=True, validation_alias="TTS_CACHE_ENABLED")
    tts_cache_ttl_seconds: int = Field(default=86400, validation_alias="TTS_CACHE_TTL_SECONDS")

    # --- Gateway: Temp Storage ---
    gateway_temp_dir: str = "/tmp/vman-gateway"
    gateway_temp_ttl_min: int = 30
    gateway_temp_dir_max_mb: int = 2048
    gateway_max_file_size_mb: int = 100

    # --- Gateway: Media Processing ---
    media_processing_timeout_ms: int = 5000
    media_supported_types: str = _DEFAULT_SUPPORTED_TYPES

    # --- Gateway: Redis & Queue ---
    redis_url: str = "redis://redis:6379"
    queue_job_timeout_ms: int = 30000

    # --- Vision LLM ---
    vision_llm_api_key: str = ""
    vision_llm_model: str = "gpt-4o"
    vision_llm_base_url: str = ""

    # --- Whisper ---
    whisper_provider: str = "openai"  # "openai" | "local"
    whisper_api_key: str = ""
    whisper_local_bin: str = "/usr/local/bin/whisper"

    # --- Camera ---
    camera_snapshot_interval_sec: int = 5

    # --- API Tool ---
    api_tool_timeout_ms: int = 10000
    api_tool_max_queue: int = 10
    api_registry_path: str = "./config/api-registry.yaml"

    # --- Web Crawler ---
    crawler_timeout_ms: int = 15000
    crawler_cache_ttl_min: int = 60
    crawler_ignore_robots: bool = False
    crawler_blocked_domains: str = ""
    crawler_provider_url: str = ""

    # --- Internal ---
    brain_url: str = "http://api:8100"
    gateway_internal_token: str = "change-me-in-production"

    @property
    def supported_mime_types(self) -> frozenset[str]:
        return frozenset(_split_csv_values(self.media_supported_types))

    @property
    def is_dev(self) -> bool:
        return self.env == "dev"

    @property
    def blocked_domain_set(self) -> frozenset[str]:
        return frozenset(
            domain.lower()
            for domain in _split_csv_values(self.crawler_blocked_domains)
        )


@lru_cache(maxsize=1)
def get_tts_config() -> TTSRouterConfig:
    """Build config from environment variables (cached)."""
    return TTSRouterConfig()
