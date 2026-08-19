"""Provider registry, local BGE inference, and external embedding adapters."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
import logging
import math
import os
import time
from typing import Any, Sequence
from urllib.parse import urlparse, urlunparse

import httpx

from identity import EmbeddingSpec, make_canonical_identity

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


def _l2_normalize(vectors: Sequence[Sequence[float]]) -> list[list[float]]:
    normalized_vectors: list[list[float]] = []
    for vec in vectors:
        norm = math.sqrt(sum(float(x) * float(x) for x in vec))
        if norm > 1e-12:
            normalized_vectors.append([float(x) / norm for x in vec])
        else:
            normalized_vectors.append([float(x) for x in vec])
    return normalized_vectors


class BgeLocalProvider:
    """Lazy-loaded in-process BGE dense embedding provider with single-flight init."""

    def __init__(
        self,
        model_name: str = "BAAI/bge-m3",
        model_revision: str = "default",
        device: str = "cuda",
        use_fp16: bool = True,
        batch_size: int = 32,
        max_length: int = 8192,
        max_concurrency: int = 1,
    ) -> None:
        self.model_name = model_name
        self.model_revision = model_revision
        self.device = device
        self.use_fp16 = use_fp16
        self.batch_size = batch_size
        self.max_length = max_length
        self._dimensions = 1024
        self._semaphore = asyncio.Semaphore(max_concurrency)
        self._init_lock = asyncio.Lock()
        self._model: Any = None
        self._is_ready = False
        self._warmup_complete = False

    @property
    def is_configured(self) -> bool:
        return True

    def spec(self, input_semantics: str = "document") -> EmbeddingSpec:
        identity = make_canonical_identity(
            provider="bge",
            model=self.model_name,
            dimensions=self._dimensions,
            dtype="float32",
            normalization="l2",
            input_semantics=input_semantics,
            model_revision=self.model_revision,
        )
        return EmbeddingSpec(
            identity=identity,
            provider="bge",
            model=self.model_name,
            dimensions=self._dimensions,
            dtype="float32",
            normalized=True,
            normalization="l2",
            input_semantics=input_semantics,
            model_revision=self.model_revision,
            service_revision="1.0.0",
        )

    async def _get_or_load_model(self) -> Any:
        if self._model is not None:
            return self._model

        async with self._init_lock:
            if self._model is not None:
                return self._model

            loop = asyncio.get_running_loop()

            def _load() -> Any:
                logger.info(
                    "Initializing BGE model '%s' on %s (fp16=%s)...",
                    self.model_name,
                    self.device,
                    self.use_fp16,
                )
                from FlagEmbedding import BGEM3FlagModel
                from huggingface_hub import snapshot_download

                kwargs: dict[str, Any] = {
                    "use_fp16": self.use_fp16,
                    "device": self.device,
                }
                model_source = self.model_name
                if (
                    self.model_revision not in {"", "default"}
                    and not os.path.isdir(self.model_name)
                ):
                    model_source = snapshot_download(
                        repo_id=self.model_name,
                        revision=self.model_revision,
                    )
                return BGEM3FlagModel(model_source, **kwargs)

            self._model = await loop.run_in_executor(None, _load)
            self._is_ready = True
            logger.info("BGE model '%s' loaded successfully.", self.model_name)
            return self._model

    async def is_ready(self) -> bool:
        try:
            await self._get_or_load_model()
            return self._is_ready
        except Exception:
            return False

    async def warmup(self) -> None:
        if self._warmup_complete:
            return
        model = await self._get_or_load_model()
        loop = asyncio.get_running_loop()

        def _warm():
            if hasattr(model, "encode_dense"):
                model.encode_dense(["warmup probe"], batch_size=1, max_length=128)
            else:
                res = model.encode(["warmup probe"], batch_size=1, max_length=128)
                if isinstance(res, dict) and "dense_vecs" in res:
                    _ = res["dense_vecs"]

        async with self._semaphore:
            await loop.run_in_executor(None, _warm)
        self._warmup_complete = True

    async def encode(
        self,
        texts: list[str],
        *,
        input_type: str = "document",
    ) -> list[list[float]]:
        if not texts:
            return []

        model = await self._get_or_load_model()
        loop = asyncio.get_running_loop()

        def _do_encode() -> list[list[float]]:
            if hasattr(model, "encode_dense"):
                raw = model.encode_dense(
                    texts,
                    batch_size=self.batch_size,
                    max_length=self.max_length,
                )
            else:
                raw = model.encode(
                    texts,
                    batch_size=self.batch_size,
                    max_length=self.max_length,
                )
            if isinstance(raw, dict):
                raw = raw.get("dense_vecs", raw)
            if hasattr(raw, "tolist"):
                return raw.tolist()
            return [list(x) for x in raw]

        async with self._semaphore:
            vectors = await loop.run_in_executor(None, _do_encode)

        return _l2_normalize(vectors)

    async def shutdown(self) -> None:
        async with self._init_lock:
            self._model = None
            self._is_ready = False
            self._warmup_complete = False
        logger.info("BGE local provider shut down cleanly.")


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
    ) -> None:
        self.api_key = (api_key or "").strip()
        self.model = model.strip()
        self.dimensions = dimensions
        self.model_revision = model_revision
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout
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
        if self._client is None or self._client.is_closed:
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
            resp = await client.post(url, json=payload, headers=headers)
            resp.raise_for_status()
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
    ) -> None:
        self.api_key = (api_key or "").strip()
        self.model = model.strip()
        self.dimensions = dimensions
        self.model_revision = model_revision
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout
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
        if self._client is None or self._client.is_closed:
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
            resp = await client.post(url, json=payload, headers=headers)
            resp.raise_for_status()
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
    ) -> None:
        self.api_key = (api_key or "").strip()
        self.model = model.strip()
        self.dimensions = dimensions
        self.model_revision = model_revision
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout
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
        if self._client is None or self._client.is_closed:
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
            resp = await client.post(url, json=payload, headers=headers)
            resp.raise_for_status()
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
    ) -> tuple[list[list[float]], EmbeddingSpec, list[dict[str, Any]]]:
        """Resolve suitable provider, execute encoding, and return attempt diagnostics."""
        now = time.time()
        attempts: list[dict[str, Any]] = []
        errors: list[str] = []

        acceptable_set = {ident.strip() for ident in acceptable_identities} if acceptable_identities else None

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
                vectors = await provider.encode(texts, input_type=input_type)
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
