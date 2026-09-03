from dataclasses import dataclass
from functools import cached_property
import json
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
    llm_model: str = "gemini-3.1-flash-lite"
    llm_fallback_model: str = ""
    llm_base_url: str = ""
    llm_temperature: float = 0.3
    # 串流回應要求最後一個 chunk 附帶 usage（OpenAI 相容 stream_options）。
    llm_stream_include_usage: bool = True
    llm_key_cooldown_seconds: int = 60
    llm_key_long_cooldown_seconds: int = 300
    llm_fallback_chain: str = ""
    llm_max_fallback_hops: int = 4
    llm_disable_model_discovery: bool = False
    llm_request_timeout_seconds: float = 20.0
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
    live_gemini_context_compression: bool = True

    # === Embedding 設定 ===
    embedding_active_version: str = "bge"
    embedding_version_order: str = "bge,gemini,openai,voyage"
    embedding_service_url: str = ""
    embedding_service_token: str = ""
    embedding_service_timeout: float = 30.0
    embedding_service_chunk_size: int = 32
    embedding_expected_model: str = "BAAI/bge-m3"
    embedding_expected_dimension: int = 1024
    embedding_expected_revision: str = "5617a9f61b028005a4858fdac845db406aefb181"
    embedding_write_identity: str = ""
    embedding_identity_aliases: str = ""
    embedding_compatible_legacy_identities: str = ""
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
    rag_distance_cutoff: float = 0.85
    rag_memory_distance_bonus: float = 0.02
    rag_rrf_k: int = 60
    rag_dedup_similarity_threshold: float = 0.95
    rag_query_expansion_enabled: bool = False
    rag_query_expansion_max_terms: int = 3
    rag_query_expansion_model: str = ""
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

    # === Privacy Filter 設定 ===
    privacy_filter_enabled: bool = True
    privacy_filter_device: str = "cuda"          # cpu | cuda
    privacy_filter_include_system: bool = False
    privacy_filter_cache_size: int = 512
    privacy_filter_block_categories: str = "secret"

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
    # e.g. "gemini-2.0-flash-lite" for faster forced tool calls
    forced_tool_model_override: str = ""
    forced_tool_max_tokens: int = 200
    # 一般使用者回合的第一次 LLM 呼叫強制走 search_knowledge，避免模型憑記憶亂答。
    chat_force_knowledge_search: bool = True
    # 強制查完知識庫後的回合不再提供 search_knowledge（避免重複翻書），
    # 但 search_web、wiki、技能等其他工具照常；問天氣這類題目仍能上網查。
    chat_answer_pass_excludes_knowledge_search: bool = True
    # 多條查詢（AI 改寫 + 原句）RRF 融合後最多餵給模型幾個片段；
    # 若只依單一查詢的 top_k 截斷，多查詢等於白查。
    knowledge_search_merge_limit: int = 5

    # === Web Search ===
    gateway_base_url: str = "http://backend:8200"
    url2md_primary_url: str = "https://2md.aiurl.tw"
    url2md_fallback_urls: str = "https://2md.glsoft.ai,https://create360.ai"
    url2md_search_enabled: bool = True
    url2md_read_enabled: bool = True
    web_search_max_chars: int = 3000
    web_search_max_results: int = 8

    # === David888 Wiki ===
    wiki_api_base_url: str = "https://wiki.david888.com/api"
    wiki_publish_enabled: bool = True
    wiki_publish_max_chars: int = 100000
    wiki_publish_timeout_seconds: float = 30.0

    # === 備用 Provider Keys ===
    gemini_api_key: str = ""
    groq_api_key: str = ""
    nen_api_key: str = ""
    nen_base_url: str = "https://nen.com.tw/v1"
    openai_api_key: str = ""
    voyage_api_key: str = ""

    # === 安全設定 ===
    gateway_internal_token: str = ""
    max_input_length: int = 500
    qa_image_max_bytes: int = 10 * 1024 * 1024
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
    def resolved_embedding_identity_aliases(self) -> dict[str, str]:
        """Return explicit legacy alias to document-identity mappings."""
        aliases = {
            "bge": self._embedding_identity(
                "bge",
                self.embedding_expected_model,
                self.embedding_expected_dimension or 1024,
                "document",
                self.embedding_expected_revision,
            ),
            "gemini": self._embedding_identity(
                "gemini",
                self.embedding_gemini_model,
                self.embedding_gemini_dimensions or 768,
                "document",
                "provider-managed",
            ),
            "openai": self._embedding_identity(
                "openai",
                self.embedding_openai_model,
                self.embedding_openai_dimensions or 1536,
                "document",
                "provider-managed",
            ),
            "voyage": self._embedding_identity(
                "voyage",
                self.embedding_voyage_model,
                self.embedding_voyage_dimensions or 1024,
                "document",
                "provider-managed",
            ),
        }
        raw = self.embedding_identity_aliases.strip()
        if not raw:
            return aliases
        try:
            overrides = json.loads(raw)
        except json.JSONDecodeError as exc:
            raise ValueError("EMBEDDING_IDENTITY_ALIASES 必須是 JSON object") from exc
        if not isinstance(overrides, dict):
            raise ValueError("EMBEDDING_IDENTITY_ALIASES 必須是 JSON object")
        for alias, identity in overrides.items():
            normalized_alias = self._normalize_embedding_version(str(alias))
            normalized_identity = str(identity).strip()
            self._validate_embedding_identity(normalized_identity)
            aliases[normalized_alias] = normalized_identity
        return aliases

    @property
    def resolved_embedding_write_identity(self) -> str:
        identity = self.embedding_write_identity.strip()
        if identity:
            self._validate_embedding_identity(identity)
            return identity
        return self.resolved_embedding_identity_aliases[
            self.resolved_embedding_active_version
        ]

    @property
    def resolved_embedding_compatible_legacy_identities(self) -> set[str]:
        """Return identities proven equivalent to the pinned write identity."""
        identities: set[str] = set()
        if (
            self.embedding_expected_model == "BAAI/bge-m3"
            and self.embedding_expected_dimension == 1024
            and self.embedding_expected_revision
            == "5617a9f61b028005a4858fdac845db406aefb181"
        ):
            identities.add(
                self._embedding_identity(
                    "bge",
                    "BAAI/bge-m3",
                    1024,
                    "document",
                    "default",
                )
            )
        raw = self.embedding_compatible_legacy_identities.strip()
        if not raw:
            return identities
        try:
            configured = json.loads(raw)
        except json.JSONDecodeError as exc:
            raise ValueError(
                "EMBEDDING_COMPATIBLE_LEGACY_IDENTITIES 必須是 JSON array"
            ) from exc
        if not isinstance(configured, list):
            raise ValueError(
                "EMBEDDING_COMPATIBLE_LEGACY_IDENTITIES 必須是 JSON array"
            )
        for identity in configured:
            normalized = str(identity).strip()
            self._validate_embedding_identity(normalized)
            identities.add(normalized)
        return identities

    @property
    def resolved_embedding_query_identities(self) -> list[str]:
        aliases = self.resolved_embedding_identity_aliases
        return [
            self._identity_with_semantics(aliases[version], "query")
            for version in self.resolved_embedding_version_order
        ]

    def resolve_embedding_identity(
        self,
        value: str,
        *,
        input_semantics: str = "document",
    ) -> str:
        normalized = value.strip()
        if normalized.lower() in self.resolved_embedding_identity_aliases:
            normalized = self.resolved_embedding_identity_aliases[normalized.lower()]
        self._validate_embedding_identity(normalized)
        return self._identity_with_semantics(normalized, input_semantics)

    @property
    def resolved_embedding_service_url(self) -> str:
        if self.embedding_service_url.strip():
            return self.embedding_service_url.strip()
        return "http://embedding:8009"

    @property
    def is_embedding_service_external(self) -> bool:
        return bool(self.embedding_service_url.strip())

    @cached_property
    def resolved_privacy_filter_block_categories(self) -> list[str]:
        return [
            item.strip()
            for item in self.privacy_filter_block_categories.split(",")
            if item.strip()
        ]

    @property
    def resolved_llm_api_keys(self) -> list[str]:
        """Combine raw LLM_API_KEYS pool, legacy LLM_API_KEY, and provider-specific key."""
        keys = [k.strip() for k in self.llm_api_keys.split(",") if k.strip()]
        if self.llm_api_key.strip():
            keys.append(self.llm_api_key.strip())

        if not keys:
            if specific_key := self.resolve_api_key_for_provider(self.llm_provider):
                keys.append(specific_key)

        return list(dict.fromkeys(keys))

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
        """
        raw_chain = self.llm_fallback_chain.strip()
        if not raw_chain:
            return [(self.llm_provider, model) for model in self.resolved_llm_models]

        pairs: list[tuple[str, str]] = []
        for entry in raw_chain.split(","):
            if ":" in entry:
                provider, model = entry.split(":", 1)
                if provider.strip() and model.strip():
                    pairs.append((provider.strip(), model.strip()))

        return pairs or [(self.llm_provider, self.llm_model)]

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
        if provider == "nen":
            return self.nen_base_url.strip()
        if self.llm_base_url and provider == self.llm_provider:
            return self.llm_base_url
        return self._BASE_URL_DEFAULTS.get(provider, "")

    def resolve_api_key_for_provider(self, provider: str) -> str:
        """Return the first API key available for a given provider."""
        key_map = {
            "gemini": self.gemini_api_key,
            "groq": self.groq_api_key,
            "nen": self.nen_api_key,
            "openai": self.openai_api_key,
            "voyage": self.voyage_api_key,
        }
        if key := key_map.get(provider):
            return key

        if provider == self.llm_provider:
            # Check llm_api_keys pool first
            for k in self.llm_api_keys.split(","):
                if stripped := k.strip():
                    return stripped
            return self.llm_api_key.strip()

        return ""

    @property
    def resolved_allowed_channels(self) -> list[str]:
        return [
            channel.strip()
            for channel in self.allowed_channels.split(",")
            if channel.strip()
        ]

    def resolve_embedding_backend(
        self,
        version: str | None = None,
    ) -> EmbeddingBackend:
        resolved_version = self._normalize_embedding_version(
            version or self.embedding_active_version
        )
        provider_models = {
            "gemini": (
                self.embedding_gemini_model,
                self.embedding_gemini_dimensions or 768,
            ),
            "openai": (
                self.embedding_openai_model,
                self.embedding_openai_dimensions or 1536,
            ),
            "voyage": (
                self.embedding_voyage_model,
                self.embedding_voyage_dimensions or 1024,
            ),
            "bge": (
                self.embedding_expected_model,
                self.embedding_expected_dimension or 1024,
            ),
        }
        model, dimensions = provider_models.get(
            resolved_version,
            (
                self.embedding_expected_model,
                self.embedding_expected_dimension or 1024,
            ),
        )

        return EmbeddingBackend(
            version=resolved_version,
            provider=resolved_version,
            model=model,
            api_key=self.embedding_service_token,
            base_url=self.resolved_embedding_service_url,
            dimensions=dimensions,
        )

    def _normalize_embedding_dimensions(self, value: int) -> int | None:
        return value if value > 0 else None

    def _normalize_embedding_version(self, value: str | None) -> str:
        normalized = (value or "").strip().lower()
        if normalized in {"bge", "gemini", "openai", "voyage"}:
            return normalized
        raise ValueError(f"embedding version 不支援: {value}")

    @staticmethod
    def _embedding_identity(
        provider: str,
        model: str,
        dimensions: int,
        semantics: str,
        revision: str,
    ) -> str:
        return (
            f"{provider}:{model}:{dimensions}:float32:l2:"
            f"{semantics}:{revision}"
        )

    @staticmethod
    def _validate_embedding_identity(identity: str) -> None:
        parts = identity.split(":")
        if len(parts) != 7 or not all(parts):
            raise ValueError(f"embedding identity 格式不合法: {identity!r}")
        try:
            dimensions = int(parts[2])
        except ValueError as exc:
            raise ValueError(f"embedding identity 維度不合法: {identity!r}") from exc
        if dimensions <= 0:
            raise ValueError(f"embedding identity 維度不合法: {identity!r}")

    @classmethod
    def _identity_with_semantics(cls, identity: str, semantics: str) -> str:
        cls._validate_embedding_identity(identity)
        if semantics not in {"document", "query", "symmetric"}:
            raise ValueError(f"embedding input semantics 不支援: {semantics}")
        parts = identity.split(":")
        parts[5] = semantics
        return ":".join(parts)


_settings: BrainSettings | None = None


def get_settings() -> BrainSettings:
    """Singleton 取得設定實例"""
    global _settings
    if _settings is None:
        _settings = BrainSettings()
    return _settings
