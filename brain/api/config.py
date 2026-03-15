"""大腦層集中設定 — 從 .env 讀取所有環境變數"""

from pathlib import Path
from pydantic_settings import BaseSettings, SettingsConfigDict

API_INTERNAL_PORT = 8100


class BrainSettings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=Path(__file__).resolve().parent.parent / ".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # === 環境 ===
    env: str = "dev"  # dev | prod

    # === LLM 設定 ===
    brain_llm_provider: str = "gemini"
    brain_llm_api_key: str = ""
    brain_llm_api_keys: str = ""
    brain_llm_model: str = "gemini-2.0-flash"
    brain_llm_fallback_model: str = ""
    brain_llm_base_url: str = ""
    brain_llm_temperature: float = 0.3
    brain_llm_key_cooldown_seconds: int = 60
    brain_llm_key_long_cooldown_seconds: int = 300
    brain_llm_fallback_chain: str = ""
    brain_llm_max_fallback_hops: int = 4
    prompt_system_char_budget: int = 6000
    prompt_total_char_budget: int = 12000
    prompt_context_char_budget: int = 2800
    prompt_history_char_budget: int = 2200
    prompt_history_summary_char_budget: int = 900
    prompt_soul_char_budget: int = 1800
    prompt_memory_char_budget: int = 1200
    prompt_agents_char_budget: int = 1000
    prompt_tools_char_budget: int = 1000
    prompt_learnings_char_budget: int = 900
    prompt_errors_char_budget: int = 700

    # === Embedding 設定 ===
    embedding_model: str = "BAAI/bge-m3"
    embedding_use_fp16: bool = True
    embedding_device: str = "cuda"
    lancedb_path: str = "~/.openclaw/lancedb"
    knowledge_index_state_path: str = "/data/knowledge_index_state.json"
    chunk_char_limit: int = 500
    chunk_overlap_ratio: float = 0.15
    chunk_semantic_threshold: float = 0.65

    # === 記憶設定 ===
    short_term_memory_rounds: int = 20
    rag_top_k: int = 5
    rag_knowledge_top_k: int = 5
    rag_memory_top_k: int = 3
    rag_rerank_candidate_multiplier: int = 4
    rag_memory_distance_bonus: float = 0.02
    max_session_rounds: int = 100
    max_session_ttl_minutes: int = 30
    session_db_path: str = "/data/sessions.db"
    memory_maintenance_interval_seconds: int = 300
    memory_decay_rate_per_day: float = 0.005
    memory_merge_similarity_threshold: float = 0.92
    memory_importance_weight: float = 0.03

    # === Agent 設定 ===
    agent_loop_max_rounds: int = 6
    tool_call_timeout_seconds: int = 10
    tool_document_char_limit: int = 4000

    # === 備用 Provider Keys ===
    gemini_api_key: str = ""
    groq_api_key: str = ""
    openai_api_key: str = ""

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
    def resolved_llm_api_keys(self) -> list[str]:
        """Combine the legacy single key and the new key-pool env into one list."""
        candidates = []
        if self.brain_llm_api_keys.strip():
            candidates.extend(
                key.strip()
                for key in self.brain_llm_api_keys.split(",")
                if key.strip()
            )
        if self.brain_llm_api_key.strip():
            candidates.append(self.brain_llm_api_key.strip())

        return list(dict.fromkeys(candidates))

    @property
    def resolved_llm_models(self) -> list[str]:
        """Return the primary and fallback models without duplicates."""
        models = [self.brain_llm_model.strip()]
        fallback = self.brain_llm_fallback_model.strip()
        if fallback and fallback not in models:
            models.append(fallback)
        return [model for model in models if model]

    @property
    def resolved_fallback_chain(self) -> list[tuple[str, str]]:
        """Parse BRAIN_LLM_FALLBACK_CHAIN into (provider, model) pairs.

        Format: ``provider:model,provider:model,...``
        Falls back to the primary provider/model if not configured.
        """
        if not self.brain_llm_fallback_chain.strip():
            return [
                (self.brain_llm_provider, model)
                for model in self.resolved_llm_models
            ]
        pairs: list[tuple[str, str]] = []
        for raw_entry in self.brain_llm_fallback_chain.split(","):
            stripped = raw_entry.strip()
            if ":" not in stripped:
                continue
            provider, model = stripped.split(":", 1)
            if provider.strip() and model.strip():
                pairs.append((provider.strip(), model.strip()))
        return pairs if pairs else [(self.brain_llm_provider, self.brain_llm_model)]

    _BASE_URL_DEFAULTS: dict[str, str] = {
        "gemini": "https://generativelanguage.googleapis.com/v1beta/openai/",
        "groq": "https://api.groq.com/openai/v1",
    }

    @property
    def resolved_llm_base_url(self) -> str:
        """Provide a sane default base URL per provider."""
        if self.brain_llm_base_url:
            return self.brain_llm_base_url
        return self._BASE_URL_DEFAULTS.get(self.brain_llm_provider, "")

    def resolve_base_url_for_provider(self, provider: str) -> str:
        """Return the base URL for a given provider name."""
        if self.brain_llm_base_url and provider == self.brain_llm_provider:
            return self.brain_llm_base_url
        return self._BASE_URL_DEFAULTS.get(provider, "")

    def resolve_api_key_for_provider(self, provider: str) -> str:
        """Return the first API key available for a given provider."""
        if provider == self.brain_llm_provider:
            keys = self.resolved_llm_api_keys
            return keys[0] if keys else ""
        key_map = {
            "gemini": self.gemini_api_key,
            "groq": self.groq_api_key,
            "openai": self.openai_api_key,
        }
        return key_map.get(provider, "")

    @property
    def resolved_allowed_channels(self) -> list[str]:
        return [
            channel.strip()
            for channel in self.allowed_channels.split(",")
            if channel.strip()
        ]


_settings: BrainSettings | None = None


def get_settings() -> BrainSettings:
    """Singleton 取得設定實例"""
    global _settings
    if _settings is None:
        _settings = BrainSettings()
    return _settings
