"""Provider routing with API-key rotation and model fallback."""

from __future__ import annotations

from dataclasses import dataclass
from threading import Lock
from time import monotonic

from openai import APIConnectionError, APIStatusError, APITimeoutError, RateLimitError

from config import get_settings
from infra.learnings import record_error_event


@dataclass(frozen=True, slots=True)
class LLMRoute:
    api_key: str
    model: str
    base_url: str


class ProviderRouter:
    """Track key cooldowns and generate ordered route attempts."""

    def __init__(self) -> None:
        self._lock = Lock()
        self._next_key_index = 0
        self._cooldowns: dict[str, float] = {}

    def iter_routes(self) -> list[LLMRoute]:
        cfg = get_settings()
        keys = cfg.resolved_llm_api_keys
        if not keys:
            return []

        ordered_keys = self._ordered_keys(keys)
        return [
            LLMRoute(api_key=api_key, model=model, base_url=cfg.resolved_llm_base_url)
            for model in cfg.resolved_llm_models
            for api_key in ordered_keys
        ]

    def mark_success(self, api_key: str) -> None:
        with self._lock:
            self._cooldowns.pop(api_key, None)

    def mark_failure(self, api_key: str, model: str, exc: Exception) -> None:
        cfg = get_settings()
        with self._lock:
            if self._should_cooldown(exc):
                self._cooldowns[api_key] = monotonic() + cfg.brain_llm_key_cooldown_seconds

        record_error_event(
            area="provider_router",
            summary=f"{model} route failed",
            detail=f"{type(exc).__name__}: {exc}",
        )

    def _ordered_keys(self, keys: list[str]) -> list[str]:
        available_keys = self._available_keys(keys)
        if not available_keys:
            available_keys = list(keys)

        with self._lock:
            start = self._next_key_index % len(available_keys)
            ordered = available_keys[start:] + available_keys[:start]
            self._next_key_index = (start + 1) % len(available_keys)
            return ordered

    def _available_keys(self, keys: list[str]) -> list[str]:
        now = monotonic()
        with self._lock:
            return [key for key in keys if self._cooldowns.get(key, 0.0) <= now]

    @staticmethod
    def _should_cooldown(exc: Exception) -> bool:
        if isinstance(exc, (RateLimitError, APIConnectionError, APITimeoutError)):
            return True
        if isinstance(exc, APIStatusError):
            return exc.status_code in {401, 403, 429, 500, 502, 503, 504}
        return False


_router: ProviderRouter | None = None


def get_provider_router() -> ProviderRouter:
    global _router
    if _router is None:
        _router = ProviderRouter()
    return _router
