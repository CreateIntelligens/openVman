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

    # --- Gemini TTS Console ---
    tts_gemini_url: str = Field(default="", validation_alias="TTS_GEMINI_URL")

    # --- VoxCPM360 (CastAgent-compatible /api/v1/tts/*) ---
    tts_voxcpm_url: str = Field(default="", validation_alias="TTS_VOXCPM_URL")
    tts_voxcpm_api_key: str = Field(
        default="",
        validation_alias="TTS_VOXCPM_API_KEY",
    )
    tts_voxcpm_default_voice: str = Field(
        default="",
        validation_alias="TTS_VOXCPM_DEFAULT_VOICE",
    )
    # VoxCPM diffusion 去噪步數。延遲與步數幾乎線性（實測 31 字：10 步 3.2 秒、
    # 30 步 8.0 秒），而串流的首音延遲幾乎不受影響——多出來的時間全在後續段落。
    # 部署預設是 10；adapter 先前寫死 30，等於把整段合成的時間變成兩倍多。
    tts_voxcpm_inference_timesteps: int = Field(
        default=10,
        validation_alias="TTS_VOXCPM_INFERENCE_TIMESTEPS",
    )
    # 逗號分隔的 voice_id 黑名單。上游的聲音清單不是我們維護的，這裡把不想
    # 出現在選單裡的濾掉；預設排除 barbet-hung-yi-lee（另一套固定語者模型，
    # 不是 VoxCPM2 的 zero-shot 克隆，行為與其餘聲音不一致）。
    tts_voxcpm_excluded_voices: str = Field(
        default="barbet-hung-yi-lee",
        validation_alias="TTS_VOXCPM_EXCLUDED_VOICES",
    )

    # --- CosyVoice3 (CastAgent-compatible /v1/*，臺灣台語) ---
    tts_cosyvoice_url: str = Field(default="", validation_alias="TTS_COSYVOICE_URL")
    tts_cosyvoice_api_key: str = Field(
        default="",
        validation_alias="TTS_COSYVOICE_API_KEY",
    )
    tts_cosyvoice_default_voice: str = Field(
        default="",
        validation_alias="TTS_COSYVOICE_DEFAULT_VOICE",
    )
    # 逗號分隔的 voice_id 黑名單，語意同 TTS_VOXCPM_EXCLUDED_VOICES。
    tts_cosyvoice_excluded_voices: str = Field(
        default="",
        validation_alias="TTS_COSYVOICE_EXCLUDED_VOICES",
    )

    # --- TTS Text Normalization / 轉譯 API ---
    normalize_api_url: str = Field(default="", validation_alias="NORMALIZE_API_URL")

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
    document_max_upload_bytes: int = Field(
        default=100 * 1024 * 1024,
        validation_alias="DOCUMENT_MAX_UPLOAD_BYTES",
    )
    avatar_assets_dir: str = Field(
        default="/data/avatar",
        validation_alias="AVATAR_ASSETS_DIR",
    )
    avatar_backgrounds_dir: str = Field(
        default="/data/backgrounds",
        validation_alias="AVATAR_BACKGROUNDS_DIR",
    )
    avatar_mascots_dir: str = Field(
        default="/data/mascots",
        validation_alias="AVATAR_MASCOTS_DIR",
    )
    avatar_max_upload_bytes: int = Field(
        default=100 * 1024 * 1024,
        validation_alias="AVATAR_MAX_UPLOAD_BYTES",
    )
    avatar_background_max_upload_bytes: int = Field(
        default=25 * 1024 * 1024,
        validation_alias="AVATAR_BACKGROUND_MAX_UPLOAD_BYTES",
    )
    avatar_mascot_max_upload_bytes: int = Field(
        default=100 * 1024 * 1024,
        validation_alias="AVATAR_MASCOT_MAX_UPLOAD_BYTES",
    )
    docling_serve_url: str = Field(default="", validation_alias="DOCLING_SERVE_URL")
    docling_timeout_ms: int = Field(default=5000, validation_alias="DOCLING_TIMEOUT_MS")
    docling_api_key: str = Field(default="", validation_alias="DOCLING_API_KEY")
    docling_fallback_to_anydoc: bool = Field(
        default=True,
        validation_alias="DOCLING_FALLBACK_TO_ANYDOC",
    )
    pdf_inspector_enabled: bool = Field(
        default=True,
        validation_alias="PDF_INSPECTOR_ENABLED",
    )
    pdf_inspector_min_confidence: float = Field(
        default=0.85,
        validation_alias="PDF_INSPECTOR_MIN_CONFIDENCE",
    )
    pdf_inspector_min_markdown_chars: int = Field(
        default=10,
        validation_alias="PDF_INSPECTOR_MIN_MARKDOWN_CHARS",
    )
    pdf_repair_enabled: bool = Field(
        default=True,
        validation_alias="PDF_REPAIR_ENABLED",
    )
    pdf_repair_timeout_ms: int = Field(
        default=120000,
        validation_alias="PDF_REPAIR_TIMEOUT_MS",
    )

    # --- TTS Cache ---
    tts_cache_enabled: bool = Field(default=True, validation_alias="TTS_CACHE_ENABLED")
    tts_cache_ttl_seconds: int = Field(default=86400, validation_alias="TTS_CACHE_TTL_SECONDS")

    # --- Gateway: Temp Storage ---
    gateway_temp_dir: str = "/tmp/vman-gateway"
    gateway_temp_ttl_min: int = 30
    gateway_temp_dir_max_mb: int = 2048
    gateway_max_file_size_mb: int = 100
    gateway_convert_to_traditional: bool = Field(
        default=True,
        validation_alias="GATEWAY_CONVERT_TO_TRADITIONAL",
    )

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
    # "sensevoice" | "breeze" | "openai"
    # 都是整檔上傳、無串流端點：使用者講完才開始辨識。sensevoice 會以臺語
    # 漢字輸出臺語語音，breeze 則轉寫成華語。
    whisper_provider: str = "sensevoice"
    whisper_api_key: str = ""
    # Breeze-ASR-26（MediaTek Research）：POST /transcribe，multipart ``file``。
    asr_breeze_url: str = ""
    # SenseVoice-Small（阿里）：POST /api/v1/asr，multipart ``files`` + ``keys``。
    asr_sensevoice_url: str = ""

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
    gateway_forward_url: str = Field(
        default="",
        validation_alias="GATEWAY_FORWARD_URL",
    )
    gateway_internal_token: str = ""

    # --- Authentication ---
    session_jwt_secret: str = Field(default="", validation_alias="SESSION_JWT_SECRET")
    auth_temporary_password_secret: str = Field(
        default="",
        repr=False,
        validation_alias="AUTH_TEMPORARY_PASSWORD_SECRET",
    )
    auth_database_path: str = Field(
        default="/data/auth/accounts.db",
        validation_alias="AUTH_DATABASE_PATH",
    )
    auth_cookie_secure: bool | None = Field(
        default=None,
        validation_alias="AUTH_COOKIE_SECURE",
    )
    auth_jwt_issuer: str = Field(
        default="openvman",
        validation_alias="AUTH_JWT_ISSUER",
    )
    auth_jwt_audience: str = Field(
        default="openvman-web",
        validation_alias="AUTH_JWT_AUDIENCE",
    )
    auth_session_lifetime_seconds: int = Field(
        default=86400,
        ge=60,
        validation_alias="AUTH_SESSION_LIFETIME_SECONDS",
    )

    # --- 888a2a Agent-to-Agent Network ---
    a2a_enabled: bool = Field(
        default=False,
        validation_alias="A2A_ENABLED",
    )
    a2a_hub_url: str = Field(
        default="https://a2a.david888.com",
        validation_alias="A2A_HUB_URL",
    )
    a2a_hub_key: str = Field(
        default="",
        repr=False,
        validation_alias="A2A_HUB_KEY",
    )
    a2a_allow_public_circle: bool = Field(
        default=False,
        validation_alias="A2A_ALLOW_PUBLIC_CIRCLE",
    )
    a2a_display_name: str = Field(
        default="openVman",
        validation_alias="A2A_DISPLAY_NAME",
    )
    a2a_credentials_path: str = Field(
        default="/data/a2a/credentials.json",
        validation_alias="A2A_CREDENTIALS_PATH",
    )
    a2a_credentials_encryption_key: str = Field(
        default="",
        repr=False,
        validation_alias="A2A_CREDENTIALS_ENCRYPTION_KEY",
    )
    a2a_default_project_id: str = Field(
        default="default",
        validation_alias="A2A_DEFAULT_PROJECT_ID",
    )
    a2a_default_persona_id: str = Field(
        default="",
        validation_alias="A2A_DEFAULT_PERSONA_ID",
    )
    a2a_leader_lease_ttl_seconds: int = Field(
        default=30,
        ge=5,
        validation_alias="A2A_LEADER_LEASE_TTL_SECONDS",
    )
    a2a_queue_db_path: str = Field(
        default="/data/a2a/work.db",
        validation_alias="A2A_QUEUE_DB_PATH",
    )
    a2a_queue_retention_days: int = Field(
        default=30,
        ge=1,
        validation_alias="A2A_QUEUE_RETENTION_DAYS",
    )
    a2a_max_concurrency: int = Field(
        default=4,
        ge=1,
        le=16,
        validation_alias="A2A_MAX_CONCURRENCY",
    )
    a2a_max_tasks_per_minute: int = Field(
        default=60,
        ge=1,
        validation_alias="A2A_MAX_TASKS_PER_MINUTE",
    )
    a2a_max_delegation_hops: int = Field(
        default=3,
        ge=1,
        le=10,
        validation_alias="A2A_MAX_DELEGATION_HOPS",
    )
    a2a_allow_group_broadcast: bool = Field(
        default=False,
        validation_alias="A2A_ALLOW_GROUP_BROADCAST",
    )

    @property
    def supported_mime_types(self) -> frozenset[str]:
        return frozenset(_split_csv_values(self.media_supported_types))

    @property
    def is_dev(self) -> bool:
        return self.env == "dev"

    @property
    def session_cookie_secure(self) -> bool:
        return not self.is_dev or self.auth_cookie_secure is True

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
