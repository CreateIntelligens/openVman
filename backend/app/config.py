"""openVman backend configuration."""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from urllib.parse import urlsplit, urlunsplit

from pydantic import AliasChoices, Field
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


def _service_endpoint(
    base_url: str,
    path: str,
    *,
    websocket: bool = False,
    trim_suffix: str = "",
) -> str:
    try:
        base = urlsplit(base_url.strip())
    except ValueError:
        return ""
    if base.scheme not in ("http", "https") or not base.netloc:
        return ""
    prefix = base.path.rstrip("/")
    if trim_suffix and prefix.endswith(trim_suffix):
        prefix = prefix[:-len(trim_suffix)]
    scheme = base.scheme
    if websocket:
        scheme = {"http": "ws", "https": "wss"}[scheme]
    return urlunsplit((scheme, base.netloc, prefix + path, "", ""))


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
    # 台語那一輪的引擎順序（沒設專案順位時用）：第一個在跑的引擎先念，失敗照後面
    # 的順序換，聲音對應成同一個人；全部失敗才退 Edge。
    tts_taiwanese_fallback_order: str = Field(
        default="cosyvoice,voxcpm,indextts",
        validation_alias="TTS_TAIWANESE_FALLBACK_ORDER",
    )

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
    tts_gemini_model: str = Field(
        default="gemini-3.8-flash-tts", validation_alias="TTS_GEMINI_MODEL",
        pattern=r"^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$",
    )

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
    tts_hanji_convert_url: str = Field(
        default="", validation_alias="TTS_HANJI_CONVERT_URL",
    )
    tts_hanji_convert_enabled: bool = Field(
        default=True, validation_alias="TTS_HANJI_CONVERT_ENABLED",
    )
    tts_voxcpm_hanji_version: str = Field(
        default="v6", min_length=1,
        validation_alias="TTS_VOXCPM_HANJI_VERSION",
    )
    tts_cosyvoice_hanji_version: str = Field(
        default="v1", min_length=1,
        validation_alias="TTS_COSYVOICE_HANJI_VERSION",
    )

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
    # 微軟常改 Edge 朗讀服務的連線驗證，舊版 edge-tts 會整個被擋；定時試念一句，
    # 壞了在 /healthz 與 vman_edge_tts_up 指標上看得到。0 表示不檢查。
    edge_tts_probe_interval_seconds: int = Field(
        default=1800,
        ge=0,
        validation_alias="TTS_EDGE_PROBE_INTERVAL_SECONDS",
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
    # 影片轉素材包的工作目錄；backend 與 avatar-pipeline 容器掛同一個 /data，
    # 路徑才能直接交給 worker。
    avatar_jobs_dir: str = Field(
        default="/data/avatar-jobs",
        validation_alias="AVATAR_JOBS_DIR",
    )
    avatar_source_max_upload_bytes: int = Field(
        default=512 * 1024 * 1024,
        validation_alias="AVATAR_SOURCE_MAX_UPLOAD_BYTES",
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

    # --- 視覺事件改問 Clef ---
    # 攝影機每秒一幀，每個事件是一題是非題。2026-10-09 實測 33 張圖：Clef 每張 0.41 秒、
    # 抓到訪客 15/18、誤報 0/63；Gemini VLM 18/18 但每張 1.3 秒，跟不上每秒一幀，退居備援。
    # 留空就只用 VLM。金鑰沿用 CLEF_API_KEY（自架端點不需要）。
    vision_clef_url: str = "https://clef.create360.ai/v1/systemone"
    vision_clef_model: str = "clef-flash"
    # Clef 第一次收圖曾花 16 秒載入影像模組，之後 0.4 秒；逾時太短會一直斷在第一張。
    vision_clef_timeout_seconds: float = Field(default=5.0, gt=0, le=30)

    # --- ASR ---
    # "breeze" | "r2t2" | "r2t2-dev" | "sensevoice" | "openai"
    # 都是整檔上傳、無串流端點：使用者講完才開始辨識。我們要的是華語逐字稿：
    # breeze 把臺語轉寫成華語，sensevoice 則保留臺語漢字，所以它
    # 退居備援——全掛時臺語漢字仍比「音訊轉錄失敗」六個字進 prompt 好。
    #
    # 四個選項沒有一個是 Whisper，叫 WHISPER_PROVIDER 只會讓人以為改了沒用。
    # 舊名留著讀，既有部署的 .env 不必跟著改。
    asr_provider: str = Field(
        default="breeze",
        validation_alias=AliasChoices("ASR_PROVIDER", "WHISPER_PROVIDER"),
    )
    whisper_api_key: str = ""
    # OpenAI 轉錄模型。gpt-4o-mini-transcribe 不指定語言時自動判斷，中文直接出
    # 繁體、長句西語也不會被改寫成中文（2026-09-23 實測；自架三家都會）。
    asr_openai_model: str = Field(default="gpt-4o-mini-transcribe", validation_alias="ASR_OPENAI_MODEL")
    # 空字串走 OpenAI 官方端點。以前誤用 VISION_LLM_BASE_URL，設了 VLM 就會把
    # 語音送到 VLM 閘道。
    asr_openai_base_url: str = Field(default="", validation_alias="ASR_OPENAI_BASE_URL")
    # Breeze-ASR-26（MediaTek Research）：POST /transcribe，multipart ``file``。
    asr_breeze_url: str = ""
    # SenseVoice-Small（阿里）：POST /api/v1/asr，multipart ``files`` + ``keys``。
    asr_sensevoice_url: str = ""
    # Confucius4-R2T2（網易有道，Qwen3-ASR-1.7B）：POST /transcribe，multipart
    # ``file`` + ``language`` + ``context``（熱詞）。輸出簡體。同一台也有 WebSocket 串流。
    # 部署接 .35（vLLM 版，對外是 asr.5gao.ai），2026-10-05 起它是主機。
    asr_r2t2_url: str = ""
    asr_r2t2_stream_url: str = ""
    asr_r2t2_secret_key: str = ""
    # R2T2 dev（部署接 .37 GB10，transformers 版）：獨立的引擎 r2t2-dev／r2t2-dev-live，
    # 帳號自己選了才用，不當其他引擎的備援；批次只等這麼久，等不到交給下一家。
    asr_r2t2_dev_url: str = ""
    asr_r2t2_dev_stream_url: str = ""
    asr_r2t2_dev_secret_key: str = ""
    asr_r2t2_dev_timeout_seconds: float = 20.0
    # 台語分流時 ASR 要等「是不是台語」的判斷才回，這是判斷的等待上限。真人 95 句
    # p50 1.9 秒、p90 2.2 秒，但有一句拖到 22.7 秒；逾時就當不是台語，照原本的 TTS。
    asr_language_check_timeout_seconds: float = 2.5

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
    # 加密後台「模型供應商」頁存的所有金鑰（決策、主對話…各類共用）。
    model_provider_encryption_secret: str = Field(
        default="",
        repr=False,
        validation_alias="MODEL_PROVIDER_ENCRYPTION_SECRET",
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

    # --- Jev (TypeSafe System One) ---
    typesafe_api_key: str = Field(default="", repr=False, validation_alias="TYPESAFE_API_KEY")
    jev_base_url: str = Field(default="https://api.typesafe.ai", validation_alias="JEV_BASE_URL")
    clef_api_key: str = Field(default="", repr=False, validation_alias="CLEF_API_KEY")
    openai_api_key: str = Field(default="", repr=False, validation_alias="OPENAI_API_KEY")
    # --- 主對話 LLM（Brain 實際呼叫；這裡只是後台「模型供應商」頁的部署預設值）---
    gemini_api_key: str = Field(default="", repr=False, validation_alias="GEMINI_API_KEY")
    groq_api_key: str = Field(default="", repr=False, validation_alias="GROQ_API_KEY")
    nen_api_key: str = Field(default="", repr=False, validation_alias="NEN_API_KEY")
    nen_base_url: str = Field(default="", validation_alias="NEN_BASE_URL")
    llm_provider: str = Field(default="gemini", validation_alias="LLM_PROVIDER")
    llm_model: str = Field(default="gemini-3.5-flash-lite", validation_alias="LLM_MODEL")
    llm_fallback_chain: str = Field(default="", validation_alias="LLM_FALLBACK_CHAIN")
    # 語音打斷：規則判不出來、原本「超過 5 字就當打斷」的那一段改問 Jev。自寫 30 題規則
    # 23/30、Jev 29/30（附和、對旁人說話不再誤停），2026-10-02 改預設開。只有這段長句會
    # 多等最多 timeout；沒有 TYPESAFE_API_KEY、失敗或逾時都維持 STOP。
    jev_interrupt_enabled: bool = Field(default=True, validation_alias="JEV_INTERRUPT_ENABLED")
    jev_interrupt_timeout_seconds: float = Field(
        default=0.6, gt=0, le=5, validation_alias="JEV_INTERRUPT_TIMEOUT_SECONDS",
    )

    # 允許哪些網站的瀏覽器前端直接呼叫 API：逗號分隔的完整來源（https://a.example），
    # 或 * 表示全部；留空不開放。不允許帶 cookie，跨網域只能用 Authorization 或
    # X-Embed-Key，別的網站借不到使用者已登入的後台身分。
    cors_allowed_origins: str = Field(default="", validation_alias="CORS_ALLOWED_ORIGINS")
    # 每把帳號 API key 每分鐘最多幾個請求，超過回 429；0 表示不限。Embed key 有自己的額度。
    # 預設 300：多台機台常共用一把 key，每輪對話約 ASR、chat 各 1 次加 TTS 1～數次。
    api_key_rate_limit_per_minute: int = Field(
        default=300, ge=0, validation_alias="API_KEY_RATE_LIMIT_PER_MINUTE",
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
    # 沒指定專案時用的專案；"default" 是它的保留別名（見 app/project_ids.py）。
    default_project_id: str = Field(
        default="default",
        validation_alias="DEFAULT_PROJECT_ID",
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
    def effective_asr_r2t2_stream_url(self) -> str:
        return self.asr_r2t2_stream_url.strip() or _service_endpoint(
            self.asr_r2t2_url, "/asr_stream_api_v1", websocket=True,
        )

    @property
    def effective_asr_r2t2_dev_stream_url(self) -> str:
        return self.asr_r2t2_dev_stream_url.strip() or _service_endpoint(
            self.asr_r2t2_dev_url, "/asr_stream_api_v1", websocket=True,
        )

    @property
    def effective_tts_hanji_convert_url(self) -> str:
        if not self.tts_hanji_convert_enabled:
            return ""
        return self.tts_hanji_convert_url.strip() or _service_endpoint(
            self.tts_cosyvoice_url, "/api/convert", trim_suffix="/v1",
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
