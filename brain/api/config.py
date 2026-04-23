"""大腦層集中設定 — 從 .env 讀取所有環境變數"""

from dataclasses import dataclass
from pathlib import Path
from pydantic_settings import BaseSettings, SettingsConfigDict

API_INTERNAL_PORT = 8100


@dataclass(frozen=True, slots=True)
class EmbeddingBackend:
    """Resolved embedding backend contract for one version alias."""

    version: str
    provider: str
    model: str
    api_key: str
    base_url: str
    dimensions: int | None
    use_fp16: bool
    device: str
    multimodal: bool


class BrainSettings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=Path(__file__).resolve().parent.parent / ".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # === 環境 ===
    env: str = "dev"  # dev | prod

    # === LLM 設定 ===
    llm_provider: str = "gemini"
    llm_api_key: str = ""
    llm_api_keys: str = ""
    llm_model: str = "gemini-2.0-flash"
    llm_fallback_model: str = ""
    llm_base_url: str = ""
    llm_temperature: float = 0.3
    llm_key_cooldown_seconds: int = 60
    llm_key_long_cooldown_seconds: int = 300
    llm_fallback_chain: str = ""
    llm_max_fallback_hops: int = 4
    prompt_system_char_budget: int = 100000
    prompt_total_char_budget: int = 150000
    prompt_context_char_budget: int = 20000
    prompt_history_char_budget: int = 15000
    prompt_history_summary_char_budget: int = 5000
    prompt_soul_char_budget: int = 20000
    prompt_memory_char_budget: int = 20000
    prompt_agents_char_budget: int = 10000
    prompt_tools_char_budget: int = 10000
    prompt_identity_char_budget: int = 3000
    prompt_learnings_char_budget: int = 8000
    prompt_errors_char_budget: int = 5000
    live_gemini_model: str = "gemini-3.1-flash-live-preview"
    live_gemini_system_instruction: str = ""
    live_gemini_output_audio_transcription: bool = True
    live_gemini_tools_enabled: bool = True
    live_gemini_thinking_level: str = ""

    # === Embedding 設定 ===
    embedding_active_version: str = "bge"
    embedding_version_order: str = "bge,gemini,openai,voyage"
    embedding_model: str = "BAAI/bge-m3"
    embedding_use_fp16: bool = True
    embedding_device: str = "cuda"
    embedding_gemini_model: str = "gemini-embedding-001"
    embedding_gemini_dimensions: int = 0
    embedding_openai_model: str = "text-embedding-3-small"
    embedding_openai_dimensions: int = 0
    embedding_voyage_model: str = "voyage-3-large"
    embedding_voyage_dimensions: int = 0
    lancedb_path: str = "/data/projects/default/lancedb"
    knowledge_index_state_path: str = "/data/knowledge_index_state.json"
    chunk_char_limit: int = 500
    chunk_overlap_ratio: float = 0.15
    chunk_semantic_threshold: float = 0.65

    # === 記憶設定 ===
    short_term_memory_rounds: int = 20
    rag_knowledge_top_k: int = 5
    rag_memory_top_k: int = 3
    rag_rerank_candidate_multiplier: int = 4
    rag_distance_cutoff: float = 1.2
    rag_memory_distance_bonus: float = 0.02
    max_session_rounds: int = 100
    max_session_ttl_minutes: int = 30 * 24 * 60
    session_db_path: str = "/data/projects/default/sessions.db"
    memory_maintenance_interval_seconds: int = 300
    memory_decay_rate_per_day: float = 0.005
    memory_merge_similarity_threshold: float = 0.92
    memory_importance_weight: float = 0.03

    # === Auto Recall 設定 ===
    auto_recall_enabled: bool = True
    auto_recall_query_mode: str = "message"  # message | recent | full
    auto_recall_recent_user_turns: int = 3
    auto_recall_recent_user_chars: int = 300
    auto_recall_max_summary_chars: int = 500
    auto_recall_timeout_ms: int = 3000
    auto_recall_cache_ttl_ms: int = 15000
    auto_recall_max_cache_entries: int = 1000
    auto_recall_use_llm_summarizer: bool = True
    auto_recall_llm_model: str = ""

    # === 歸檔設定 ===
    errors_rotation_max_lines: int = 200
    transcript_retention_days: int = 30

    # === Dreaming 設定 ===
    dreaming_enabled: bool = False
    dreaming_cron: str = "0 3 * * *"
    dreaming_timezone: str = "Asia/Taipei"
    dreaming_lookback_days: int = 7
    dreaming_min_score: float = 0.80
    dreaming_min_recall_count: int = 3
    dreaming_min_unique_queries: int = 3
    dreaming_candidate_limit: int = 100
    dreaming_similarity_threshold: float = 0.90

    # === Agent 設定 ===
    agent_loop_max_rounds: int = 6
    tool_call_timeout_seconds: int = 30
    tool_document_char_limit: int = 4000

    # === Web Search ===
    gateway_base_url: str = "http://backend:8200"
    web_search_max_chars: int = 3000

    # === 備用 Provider Keys ===
    gemini_api_key: str = ""
    groq_api_key: str = ""
    openai_api_key: str = ""
    voyage_api_key: str = ""

    # === 安全設定 ===
    max_input_length: int = 500
    enable_content_filter: bool = True
    request_rate_limit_per_minute: int = 90
    block_prompt_injection: bool = True
    allowed_channels: str = "web,api,kiosk,admin,system"

    @property
    def is_dev(self) -> bool:
        return self.env == "dev"

    @property
    def lancedb_resolved_path(self) -> str:
        """展開 ~ 為完整路徑"""
        return str(Path(self.lancedb_path).expanduser())

    @property
    def session_db_resolved_path(self) -> str:
        """展開 session db 路徑。"""
        return str(Path(self.session_db_path).expanduser())

    @property
    def knowledge_index_state_resolved_path(self) -> str:
        """展開知識索引狀態檔路徑。"""
        return str(Path(self.knowledge_index_state_path).expanduser())

    @property
    def resolved_embedding_active_version(self) -> str:
        return self._normalize_embedding_version(self.embedding_active_version)

    @property
    def resolved_embedding_version_order(self) -> list[str]:
        active = self.resolved_embedding_active_version
        ordered = [active]
        for raw_entry in self.embedding_version_order.split(","):
            version = self._normalize_embedding_version(raw_entry)
            if version not in ordered:
                ordered.append(version)
        return ordered

    @property
    def resolved_llm_api_keys(self) -> list[str]:
        """Combine the legacy single key and the new key-pool env into one list.
        If both are empty, fall back to the provider-specific key.
        """
        candidates = []
        if self.llm_api_keys.strip():
            candidates.extend(
                key.strip()
                for key in self.llm_api_keys.split(",")
                if key.strip()
            )
        if self.llm_api_key.strip():
            candidates.append(self.llm_api_key.strip())

        # If still empty, try to resolve from the specific provider's key
        if not candidates:
            specific_key = self.resolve_api_key_for_provider(self.llm_provider)
            if specific_key:
                candidates.append(specific_key)

        return list(dict.fromkeys(candidates))

    @property
    def resolved_llm_models(self) -> list[str]:
        """Return the primary and fallback models without duplicates."""
        models = [self.llm_model.strip()]
        fallback = self.llm_fallback_model.strip()
        if fallback and fallback not in models:
            models.append(fallback)
        return [model for model in models if model]

    @property
    def resolved_fallback_chain(self) -> list[tuple[str, str]]:
        """Parse LLM_FALLBACK_CHAIN into (provider, model) pairs.

        Format: ``provider:model,provider:model,...``
        Falls back to the primary provider/model if not configured.
        """
        if not self.llm_fallback_chain.strip():
            return [
                (self.llm_provider, model)
                for model in self.resolved_llm_models
            ]
        pairs: list[tuple[str, str]] = []
        for raw_entry in self.llm_fallback_chain.split(","):
            stripped = raw_entry.strip()
            if ":" not in stripped:
                continue
            provider, model = stripped.split(":", 1)
            if provider.strip() and model.strip():
                pairs.append((provider.strip(), model.strip()))
        return pairs if pairs else [(self.llm_provider, self.llm_model)]

    _BASE_URL_DEFAULTS: dict[str, str] = {
        "gemini": "https://generativelanguage.googleapis.com/v1beta/openai/",
        "groq": "https://api.groq.com/openai/v1",
    }

    @property
    def resolved_llm_base_url(self) -> str:
        """Provide a sane default base URL per provider."""
        if self.llm_base_url:
            return self.llm_base_url
        return self._BASE_URL_DEFAULTS.get(self.llm_provider, "")

    def resolve_base_url_for_provider(self, provider: str) -> str:
        """Return the base URL for a given provider name."""
        if self.llm_base_url and provider == self.llm_provider:
            return self.llm_base_url
        return self._BASE_URL_DEFAULTS.get(provider, "")

    def resolve_api_key_for_provider(self, provider: str) -> str:
        """Return the first API key available for a given provider."""
        # Check provider-specific env vars first (avoids recursion with resolved_llm_api_keys)
        key_map = {
            "gemini": self.gemini_api_key,
            "groq": self.groq_api_key,
            "openai": self.openai_api_key,
        }
        provider_key = key_map.get(provider, "")
        if provider_key:
            return provider_key
        # For the active provider, fall back to generic llm_api_key(s) without
        # going through resolved_llm_api_keys to avoid infinite recursion.
        if provider == self.llm_provider:
            if self.llm_api_keys.strip():
                return next((k.strip() for k in self.llm_api_keys.split(",") if k.strip()), "")
            if self.llm_api_key.strip():
                return self.llm_api_key.strip()
        return ""

    @property
    def resolved_allowed_channels(self) -> list[str]:
        return [
            channel.strip()
            for channel in self.allowed_channels.split(",")
            if channel.strip()
        ]

    # Lookup for API-based embedding providers: version -> (model_attr, key_attr, base_url, dims_attr)
    _API_EMBEDDING_PROVIDERS: dict[str, tuple[str, str, str, str]] = {
        "gemini": ("embedding_gemini_model", "gemini_api_key", "https://generativelanguage.googleapis.com/v1beta", "embedding_gemini_dimensions"),
        "openai": ("embedding_openai_model", "openai_api_key", "", "embedding_openai_dimensions"),
        "voyage": ("embedding_voyage_model", "voyage_api_key", "https://api.voyageai.com/v1", "embedding_voyage_dimensions"),
    }

    def resolve_embedding_backend(
        self,
        version: str | None = None,
    ) -> EmbeddingBackend:
        resolved_version = self._normalize_embedding_version(version or self.embedding_active_version)
        if resolved_version == "bge":
            return EmbeddingBackend(
                version="bge",
                provider="bge",
                model=self.embedding_model,
                api_key="",
                base_url="",
                dimensions=None,
                use_fp16=self.embedding_use_fp16,
                device=self.embedding_device,
                multimodal=False,
            )
        spec = self._API_EMBEDDING_PROVIDERS.get(resolved_version)
        if spec is None:
            raise ValueError(f"embedding version 不支援: {resolved_version}")
        model_attr, key_attr, base_url, dims_attr = spec
        return EmbeddingBackend(
            version=resolved_version,
            provider=resolved_version,
            model=getattr(self, model_attr),
            api_key=getattr(self, key_attr),
            base_url=base_url,
            dimensions=self._normalize_embedding_dimensions(getattr(self, dims_attr)),
            use_fp16=False,
            device="api",
            multimodal=False,
        )

    def _normalize_embedding_dimensions(self, value: int) -> int | None:
        return value if value > 0 else None

    def _normalize_embedding_version(self, value: str | None) -> str:
        normalized = (value or "").strip().lower()
        if normalized in {"bge", "gemini", "openai", "voyage"}:
            return normalized
        raise ValueError(f"embedding version 不支援: {value}")


_settings: BrainSettings | None = None


def get_settings() -> BrainSettings:
    """Singleton 取得設定實例"""
    global _settings
    if _settings is None:
        _settings = BrainSettings()
    return _settings
