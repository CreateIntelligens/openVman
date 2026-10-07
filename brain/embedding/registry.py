"""Provider registry and external embedding adapters; local GPU providers live in local_providers."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
import logging
import random
import time
from typing import Any, Sequence
from urllib.parse import urlparse, urlunparse

import httpx

from identity import EmbeddingSpec, make_canonical_identity
from local_providers import _l2_normalize

logger = logging.getLogger("embedding_gateway.registry")


def _sanitize_url(url: str) -> str:
    if not url:
        return ""
    try:
        parsed = urlparse(url)
        netloc = parsed.netloc
        if "@" in netloc:
            auth, _, host = netloc.partition("@")
            user = auth.split(":")[0] if ":" in auth else auth
            netloc = f"{user}:***@{host}" if user else host
        return urlunparse((parsed.scheme, netloc, parsed.path, "", "", "")).rstrip("/")
    except Exception:
        return url.split("?")[0]


def _parse_retry_after(retry_after_val: str | None, max_delay: float) -> float | None:
    if not retry_after_val:
        return None
    val = retry_after_val.strip()
    try:
        delay = float(val)
        if delay >= 0:
            return min(delay, max_delay)
    except ValueError:
        pass
    try:
        dt = parsedate_to_datetime(val)
        if dt is not None:
            now = datetime.now(timezone.utc)
            delay = (dt - now).total_seconds()
            if delay > 0:
                return min(delay, max_delay)
    except Exception:
        pass
    return None


RETRYABLE_STATUS_CODES = frozenset({429, 500, 502, 503, 504})


def _calculate_backoff(
    base_delay: float,
    attempt: int,
    max_delay: float,
    retry_after: float | None = None,
) -> float:
    if retry_after is not None:
        return retry_after
    return min(base_delay * (2 ** attempt) + random.uniform(0.1, 0.4), max_delay)


async def _post_with_retry(
    client: httpx.AsyncClient,
    url: str,
    *,
    json: Any,
    headers: dict[str, str],
    max_retries: int = 3,
    base_delay: float = 0.25,
    max_delay: float = 8.0,
) -> httpx.Response:
    """Execute an HTTP POST with exponential backoff and jitter for transient errors (429, 5xx, network errors)."""
    last_exc: Exception | None = None
    sanitized_url = _sanitize_url(url)
    for attempt in range(max_retries + 1):
        try:
            resp = await client.post(url, json=json, headers=headers)
            status_code = getattr(resp, "status_code", 200)
            if status_code in RETRYABLE_STATUS_CODES and attempt < max_retries:
                retry_headers = getattr(resp, "headers", {})
                retry_after = _parse_retry_after(retry_headers.get("retry-after"), max_delay)
                delay = _calculate_backoff(base_delay, attempt, max_delay, retry_after)
                logger.warning(
                    "Embedding HTTP call to %s returned %d, retrying in %.2fs (attempt %d/%d)...",
                    sanitized_url,
                    status_code,
                    delay,
                    attempt + 1,
                    max_retries,
                )
                await asyncio.sleep(delay)
                continue
            resp.raise_for_status()
            return resp
        except (httpx.TimeoutException, httpx.NetworkError) as exc:
            last_exc = exc
            if attempt < max_retries:
                delay = _calculate_backoff(base_delay, attempt, max_delay)
                logger.warning(
                    "Embedding network/timeout error calling %s (%s), retrying in %.2fs (attempt %d/%d)...",
                    sanitized_url,
                    type(exc).__name__,
                    delay,
                    attempt + 1,
                    max_retries,
                )
                await asyncio.sleep(delay)
                continue
            raise
    if last_exc is not None:
        raise last_exc
    raise RuntimeError(f"Request to {url} exhausted retries")


class GeminiApiProvider:
    """Gemini embedding provider using header-based auth and sanitized calls."""

    def __init__(
        self,
        api_key: str,
        model: str = "gemini-embedding-001",
        dimensions: int = 768,
        model_revision: str = "provider-managed",
        base_url: str = "https://generativelanguage.googleapis.com/v1beta",
        timeout: float = 30.0,
        max_retries: int = 3,
        base_delay: float = 0.25,
        max_delay: float = 8.0,
    ) -> None:
        self.api_key = (api_key or "").strip()
        self.model = model.strip()
        self.dimensions = dimensions
        self.model_revision = model_revision
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout
        self.max_retries = max(0, max_retries)
        self.base_delay = max(0.05, base_delay)
        self.max_delay = max(self.base_delay, max_delay)
        self._client: httpx.AsyncClient | None = None
        self._is_ready = False

    @property
    def is_configured(self) -> bool:
        return bool(self.api_key)

    def spec(self, input_semantics: str = "document") -> EmbeddingSpec:
        identity = make_canonical_identity(
            provider="gemini",
            model=self.model,
            dimensions=self.dimensions,
            dtype="float32",
            normalization="l2",
            input_semantics=input_semantics,
            model_revision=self.model_revision,
        )
        return EmbeddingSpec(
            identity=identity,
            provider="gemini",
            model=self.model,
            dimensions=self.dimensions,
            dtype="float32",
            normalized=True,
            normalization="l2",
            input_semantics=input_semantics,
            model_revision=self.model_revision,
            service_revision="1.0.0",
        )

    def _get_client(self) -> httpx.AsyncClient:
        if self._client is None or getattr(self._client, "is_closed", False):
            self._client = httpx.AsyncClient(timeout=self.timeout)
        return self._client

    async def is_ready(self) -> bool:
        return self.is_configured and self._is_ready

    async def warmup(self) -> None:
        if not self.is_configured:
            raise RuntimeError("Gemini API key is not configured")
        if not self._is_ready:
            await self.encode(["embedding readiness probe"], input_type="document")

    async def encode(
        self,
        texts: list[str],
        *,
        input_type: str = "document",
    ) -> list[list[float]]:
        if not self.is_configured:
            raise RuntimeError("Gemini API key is not configured")
        if not texts:
            return []

        task_type = "RETRIEVAL_QUERY" if input_type == "query" else "RETRIEVAL_DOCUMENT"
        client = self._get_client()
        url = f"{self.base_url}/models/{self.model}:batchEmbedContents"
        headers = {
            "x-goog-api-key": self.api_key,
            "Content-Type": "application/json",
        }
        payload = {
            "requests": [
                {
                    "model": f"models/{self.model}",
                    "content": {"parts": [{"text": text}]},
                    "taskType": task_type,
                    "outputDimensionality": self.dimensions,
                }
                for text in texts
            ]
        }

        try:
            resp = await _post_with_retry(
                client,
                url,
                json=payload,
                headers=headers,
                max_retries=self.max_retries,
                base_delay=self.base_delay,
                max_delay=self.max_delay,
            )
            data = resp.json()
            raw_embeddings = data.get("embeddings", [])
            vectors = [item.get("values", []) for item in raw_embeddings]
            if len(vectors) != len(texts):
                raise RuntimeError(
                    f"Gemini returned {len(vectors)} vectors for {len(texts)} texts"
                )
            self._is_ready = True
            return _l2_normalize(vectors)
        except Exception as exc:
            self._is_ready = False
            sanitized_url = _sanitize_url(url)
            logger.error(
                "Gemini embedding call to %s failed (%s)",
                sanitized_url,
                type(exc).__name__,
            )
            raise RuntimeError(
                f"Gemini embedding failed ({type(exc).__name__})"
            ) from None

    async def shutdown(self) -> None:
        if self._client and not self._client.is_closed:
            await self._client.aclose()


class OpenAiApiProvider:
    """OpenAI standard embedding provider with header authentication."""

    def __init__(
        self,
        api_key: str,
        model: str = "text-embedding-3-small",
        dimensions: int = 1536,
        model_revision: str = "provider-managed",
        base_url: str = "https://api.openai.com/v1",
        timeout: float = 30.0,
        max_retries: int = 3,
        base_delay: float = 0.25,
        max_delay: float = 8.0,
    ) -> None:
        self.api_key = (api_key or "").strip()
        self.model = model.strip()
        self.dimensions = dimensions
        self.model_revision = model_revision
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout
        self.max_retries = max(0, max_retries)
        self.base_delay = max(0.05, base_delay)
        self.max_delay = max(self.base_delay, max_delay)
        self._client: httpx.AsyncClient | None = None
        self._is_ready = False

    @property
    def is_configured(self) -> bool:
        return bool(self.api_key)

    def spec(self, input_semantics: str = "document") -> EmbeddingSpec:
        identity = make_canonical_identity(
            provider="openai",
            model=self.model,
            dimensions=self.dimensions,
            dtype="float32",
            normalization="l2",
            input_semantics=input_semantics,
            model_revision=self.model_revision,
        )
        return EmbeddingSpec(
            identity=identity,
            provider="openai",
            model=self.model,
            dimensions=self.dimensions,
            dtype="float32",
            normalized=True,
            normalization="l2",
            input_semantics=input_semantics,
            model_revision=self.model_revision,
            service_revision="1.0.0",
        )

    def _get_client(self) -> httpx.AsyncClient:
        if self._client is None or getattr(self._client, "is_closed", False):
            self._client = httpx.AsyncClient(timeout=self.timeout)
        return self._client

    async def is_ready(self) -> bool:
        return self.is_configured and self._is_ready

    async def warmup(self) -> None:
        if not self.is_configured:
            raise RuntimeError("OpenAI API key is not configured")
        if not self._is_ready:
            await self.encode(["embedding readiness probe"], input_type="document")

    async def encode(
        self,
        texts: list[str],
        *,
        input_type: str = "document",
    ) -> list[list[float]]:
        if not self.is_configured:
            raise RuntimeError("OpenAI API key is not configured")
        if not texts:
            return []

        client = self._get_client()
        url = f"{self.base_url}/embeddings"
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }
        payload = {
            "model": self.model,
            "input": texts,
            "dimensions": self.dimensions,
        }

        try:
            resp = await _post_with_retry(
                client,
                url,
                json=payload,
                headers=headers,
                max_retries=self.max_retries,
                base_delay=self.base_delay,
                max_delay=self.max_delay,
            )
            data = resp.json()
            items = sorted(data.get("data", []), key=lambda x: x.get("index", 0))
            vectors = [item.get("embedding", []) for item in items]
            if len(vectors) != len(texts):
                raise RuntimeError(
                    f"OpenAI returned {len(vectors)} vectors for {len(texts)} texts"
                )
            self._is_ready = True
            return _l2_normalize(vectors)
        except Exception as exc:
            self._is_ready = False
            sanitized_url = _sanitize_url(url)
            logger.error(
                "OpenAI embedding call to %s failed (%s)",
                sanitized_url,
                type(exc).__name__,
            )
            raise RuntimeError(
                f"OpenAI embedding failed ({type(exc).__name__})"
            ) from None

    async def shutdown(self) -> None:
        if self._client and not self._client.is_closed:
            await self._client.aclose()


class VoyageApiProvider:
    """Voyage AI embedding provider with header authentication."""

    def __init__(
        self,
        api_key: str,
        model: str = "voyage-3-large",
        dimensions: int = 1024,
        model_revision: str = "provider-managed",
        base_url: str = "https://api.voyageai.com/v1",
        timeout: float = 30.0,
        max_retries: int = 3,
        base_delay: float = 0.25,
        max_delay: float = 8.0,
    ) -> None:
        self.api_key = (api_key or "").strip()
        self.model = model.strip()
        self.dimensions = dimensions
        self.model_revision = model_revision
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout
        self.max_retries = max(0, max_retries)
        self.base_delay = max(0.05, base_delay)
        self.max_delay = max(self.base_delay, max_delay)
        self._client: httpx.AsyncClient | None = None
        self._is_ready = False

    @property
    def is_configured(self) -> bool:
        return bool(self.api_key)

    def spec(self, input_semantics: str = "document") -> EmbeddingSpec:
        identity = make_canonical_identity(
            provider="voyage",
            model=self.model,
            dimensions=self.dimensions,
            dtype="float32",
            normalization="l2",
            input_semantics=input_semantics,
            model_revision=self.model_revision,
        )
        return EmbeddingSpec(
            identity=identity,
            provider="voyage",
            model=self.model,
            dimensions=self.dimensions,
            dtype="float32",
            normalized=True,
            normalization="l2",
            input_semantics=input_semantics,
            model_revision=self.model_revision,
            service_revision="1.0.0",
        )

    def _get_client(self) -> httpx.AsyncClient:
        if self._client is None or getattr(self._client, "is_closed", False):
            self._client = httpx.AsyncClient(timeout=self.timeout)
        return self._client

    async def is_ready(self) -> bool:
        return self.is_configured and self._is_ready

    async def warmup(self) -> None:
        if not self.is_configured:
            raise RuntimeError("Voyage API key is not configured")
        if not self._is_ready:
            await self.encode(["embedding readiness probe"], input_type="document")

    async def encode(
        self,
        texts: list[str],
        *,
        input_type: str = "document",
    ) -> list[list[float]]:
        if not self.is_configured:
            raise RuntimeError("Voyage API key is not configured")
        if not texts:
            return []

        client = self._get_client()
        url = f"{self.base_url}/embeddings"
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }
        payload = {
            "model": self.model,
            "input": texts,
            "input_type": "query" if input_type == "query" else "document",
        }

        try:
            resp = await _post_with_retry(
                client,
                url,
                json=payload,
                headers=headers,
                max_retries=self.max_retries,
                base_delay=self.base_delay,
                max_delay=self.max_delay,
            )
            data = resp.json()
            items = sorted(data.get("data", []), key=lambda x: x.get("index", 0))
            vectors = [item.get("embedding", []) for item in items]
            if len(vectors) != len(texts):
                raise RuntimeError(
                    f"Voyage returned {len(vectors)} vectors for {len(texts)} texts"
                )
            self._is_ready = True
            return _l2_normalize(vectors)
        except Exception as exc:
            self._is_ready = False
            sanitized_url = _sanitize_url(url)
            logger.error(
                "Voyage embedding call to %s failed (%s)",
                sanitized_url,
                type(exc).__name__,
            )
            raise RuntimeError(
                f"Voyage embedding failed ({type(exc).__name__})"
            ) from None

    async def shutdown(self) -> None:
        if self._client and not self._client.is_closed:
            await self._client.aclose()


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
        self.fallback_order = list(fallback_order or ["bge", "gemini", "openai", "voyage"])
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
        preferred_name = self.fallback_order[0] if self.fallback_order else "bge"

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
            # 呼叫端列的順序就是偏好：Brain 把 active 版本排第一，換模型後不能被
            # 這裡的 fallback 順序（BGE 在前）搶走。
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
