"""Provider routing with key-pool integration and failure classification."""

from __future__ import annotations

from dataclasses import dataclass

from config import get_settings
from core.key_pool import KeyPoolManager, classify_failure
from infra.learnings import record_error_event


@dataclass(frozen=True, slots=True)
class LLMRoute:
    api_key: str
    model: str
    base_url: str


class ProviderRouter:
    """Route LLM requests through the key pool with failure classification."""

    def __init__(self) -> None:
        self._pool: KeyPoolManager | None = None

    def _ensure_pool(self) -> KeyPoolManager:
        if self._pool is None:
            cfg = get_settings()
            self._pool = KeyPoolManager(
                cfg.resolved_llm_api_keys,
                short_cooldown=cfg.llm_key_cooldown_seconds,
                long_cooldown=cfg.llm_key_long_cooldown_seconds,
            )
        return self._pool

    @property
    def pool(self) -> KeyPoolManager:
        """Expose the key pool for diagnostics."""
        return self._ensure_pool()

    def iter_routes(self) -> list[LLMRoute]:
        cfg = get_settings()
        pool = self._ensure_pool()
        keys = cfg.resolved_llm_api_keys
        if not keys:
            return []

        # Build ordered key list: selected key first, then remaining healthy keys
        selected = pool.select_key()
        if selected is None:
            return []

        ordered_keys = [selected]
        for key in keys:
            if key != selected:
                state = pool.get_state(key)
                if state is not None and not state.disabled:
                    ordered_keys.append(key)

        return [
            LLMRoute(api_key=api_key, model=model, base_url=cfg.resolved_llm_base_url)
            for model in cfg.resolved_llm_models
            for api_key in ordered_keys
        ]

    def mark_success(self, api_key: str) -> None:
        self._ensure_pool().mark_success(api_key)

    def mark_failure(self, api_key: str, model: str, exc: Exception) -> None:
        reason = classify_failure(exc)
        self._ensure_pool().mark_failure(api_key, reason)

        record_error_event(
            area="provider_router",
            summary=f"{model} route failed ({reason})",
            detail=f"{type(exc).__name__}: {exc}",
        )


_router: ProviderRouter | None = None


def get_provider_router() -> ProviderRouter:
    global _router
    if _router is None:
        _router = ProviderRouter()
    return _router
