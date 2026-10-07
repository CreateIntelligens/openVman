"""Provider registry: readiness, cooldowns and identity-constrained provider selection."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
import logging
import time
from typing import Any, Sequence

from identity import EmbeddingSpec

logger = logging.getLogger("embedding_gateway.registry")


@dataclass
class _ProviderState:
    provider_name: str
    instance: Any
    failure_count: int = 0
    last_failure_time: float = 0.0


class ProviderRegistry:
    """Registry managing available embedding providers, cooldowns, and fallback."""

    def __init__(
        self,
        cooldown_seconds: float = 60.0,
        fallback_order: Sequence[str] | None = None,
    ) -> None:
        self.cooldown_seconds = cooldown_seconds
        self.fallback_order = list(fallback_order or ["gemma"])
        self._providers: dict[str, _ProviderState] = {}
        self._readiness_lock = asyncio.Lock()

    def register(self, name: str, provider: Any) -> None:
        self._providers[name.strip().lower()] = _ProviderState(
            provider_name=name.strip().lower(),
            instance=provider,
        )

    def get_provider(self, name: str) -> Any | None:
        state = self._providers.get(name.strip().lower())
        return state.instance if state else None

    def get_configured_providers(self) -> dict[str, Any]:
        """Return only providers whose keys and configurations are set."""
        return {
            name: state.instance
            for name, state in self._providers.items()
            if getattr(state.instance, "is_configured", True)
        }

    def get_available_specs(self, input_semantics: str = "document") -> list[EmbeddingSpec]:
        """Return specs only for configured providers."""
        specs: list[EmbeddingSpec] = []
        for name in self.fallback_order:
            state = self._providers.get(name)
            if state and getattr(state.instance, "is_configured", True):
                if hasattr(state.instance, "spec"):
                    specs.append(state.instance.spec(input_semantics))
        return specs

    def _is_in_cooldown(self, state: _ProviderState, now: float) -> bool:
        if state.failure_count == 0:
            return False
        return (now - state.last_failure_time) < self.cooldown_seconds

    def _record_success(self, state: _ProviderState) -> None:
        state.failure_count = 0
        state.last_failure_time = 0.0

    def _record_failure(self, state: _ProviderState) -> None:
        state.failure_count += 1
        state.last_failure_time = time.time()

    async def inspect_readiness(self) -> dict[str, Any]:
        """Serialize expensive warmups and return provider readiness."""
        async with self._readiness_lock:
            return await self._inspect_readiness_unlocked()

    async def _inspect_readiness_unlocked(self) -> dict[str, Any]:
        """Inspect all registered providers and determine overall status."""
        configured_providers = self.get_configured_providers()
        if not configured_providers:
            return {
                "status": "unavailable",
                "detail": "No embedding providers configured",
                "providers": {},
            }

        provider_statuses: dict[str, Any] = {}
        has_ready = False
        preferred_ready = False
        preferred_name = self.fallback_order[0] if self.fallback_order else "gemma"

        for name, provider in configured_providers.items():
            state = self._providers[name]
            if self._is_in_cooldown(state, time.time()):
                provider_statuses[name] = {
                    "status": "cooldown",
                    "spec": provider.spec().to_dict()
                    if hasattr(provider, "spec")
                    else {},
                }
                continue
            try:
                await provider.warmup()
                is_ready = await provider.is_ready()
                if is_ready:
                    self._record_success(state)
                    has_ready = True
                    if name == preferred_name:
                        preferred_ready = True
                provider_statuses[name] = {
                    "status": "ready" if is_ready else "unready",
                    "spec": provider.spec().to_dict() if hasattr(provider, "spec") else {},
                }
            except Exception as exc:
                self._record_failure(state)
                provider_statuses[name] = {
                    "status": "error",
                    "error_type": type(exc).__name__,
                    "spec": provider.spec().to_dict() if hasattr(provider, "spec") else {},
                }

        if preferred_ready:
            overall_status = "ready"
        elif has_ready:
            overall_status = "degraded"
        else:
            overall_status = "unavailable"

        return {
            "status": overall_status,
            "providers": provider_statuses,
        }

    async def resolve_and_encode(
        self,
        texts: list[str],
        *,
        input_type: str = "document",
        acceptable_identities: Sequence[str] | None = None,
        requested_identity: str | None = None,
        titles: Sequence[str] | None = None,
    ) -> tuple[list[list[float]], EmbeddingSpec, list[dict[str, Any]]]:
        """Resolve suitable provider, execute encoding, and return attempt diagnostics."""
        now = time.time()
        attempts: list[dict[str, Any]] = []
        errors: list[str] = []

        acceptable_list = [ident.strip() for ident in acceptable_identities] if acceptable_identities else None
        acceptable_set = set(acceptable_list) if acceptable_list is not None else None

        candidate_names: list[str] = []
        for name in self.fallback_order:
            state = self._providers.get(name)
            if not state or not getattr(state.instance, "is_configured", True):
                continue

            provider = state.instance
            spec = provider.spec(input_semantics=input_type)

            # A lease is an exact vector identity, never a provider/model alias.
            if requested_identity:
                req = requested_identity.strip()
                if req != spec.identity:
                    continue

            # Query fallback is constrained to exact identities backed by indexes.
            if acceptable_set is not None:
                if spec.identity not in acceptable_set:
                    continue

            candidate_names.append(name)

        if acceptable_list:
            # 呼叫端列的順序就是偏好，不是 gateway 的 fallback 順序。
            def _preference(provider_name: str) -> int:
                identity = self._providers[provider_name].instance.spec(input_semantics=input_type).identity
                return acceptable_list.index(identity)

            candidate_names.sort(key=_preference)

        if not candidate_names:
            msg = (
                f"No configured embedding provider matched requested criteria "
                f"(requested_identity={requested_identity!r}, acceptable_identities={acceptable_identities!r})"
            )
            logger.warning(msg)
            raise RuntimeError(msg)

        for name in candidate_names:
            state = self._providers[name]
            provider = state.instance
            spec = provider.spec(input_semantics=input_type)

            if self._is_in_cooldown(state, now):
                attempts.append({
                    "provider": name,
                    "model": spec.model,
                    "identity": spec.identity,
                    "status": "cooldown",
                    "reason": f"Provider in cooldown ({self.cooldown_seconds}s)",
                })
                continue

            try:
                extra = {"titles": list(titles)} if titles and getattr(provider, "accepts_titles", False) else {}
                vectors = await provider.encode(texts, input_type=input_type, **extra)
                # Verify vector dimensions
                if vectors and len(vectors[0]) != spec.dimensions:
                    raise ValueError(
                        f"Provider {name} returned vector dimension {len(vectors[0])} != expected {spec.dimensions}"
                    )
                self._record_success(state)
                attempts.append({
                    "provider": name,
                    "model": spec.model,
                    "identity": spec.identity,
                    "status": "selected",
                })
                return vectors, spec, attempts
            except Exception as exc:
                self._record_failure(state)
                attempts.append({
                    "provider": name,
                    "model": spec.model,
                    "identity": spec.identity,
                    "status": "error",
                    "error_type": type(exc).__name__,
                })
                errors.append(f"{name}: {type(exc).__name__}")

        raise RuntimeError(
            f"No acceptable embedding provider succeeded for batch (attempted {len(attempts)} providers). Errors: {'; '.join(errors)}"
        )

    async def shutdown(self) -> None:
        for state in self._providers.values():
            if hasattr(state.instance, "shutdown"):
                try:
                    await state.instance.shutdown()
                except Exception as exc:
                    logger.warning("Error shutting down provider %s: %s", state.provider_name, exc)
