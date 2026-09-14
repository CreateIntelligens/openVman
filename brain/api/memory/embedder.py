"""Remote embedding gateway adapter and query fallback router for Brain."""

from __future__ import annotations

from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
import logging
import random
from threading import Lock
import time
from typing import Any, Protocol

import httpx

from config import EmbeddingBackend, get_settings

logger = logging.getLogger("brain.memory.embedder")


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


class TextEmbedder(Protocol):
    """Protocol for text embedding backends."""

    def encode(
        self,
        texts: list[str],
        *,
        input_type: str = "document",
        acceptable_identities: list[str] | None = None,
        forced_identity: str | None = None,
    ) -> list[list[float]]:
        ...

    def encode_with_metadata(
        self,
        texts: list[str],
        *,
        input_type: str = "document",
        acceptable_identities: list[str] | None = None,
        forced_identity: str | None = None,
    ) -> tuple[list[list[float]], dict[str, Any], list[dict[str, Any]]]:
        ...


class QueryEmbeddingRoute:
    """Result of encoding a search query with metadata."""

    def __init__(
        self,
        version: str,
        vector: list[float],
        attempted_versions: list[dict[str, Any]],
        embedding_spec: dict[str, Any] | None = None,
    ) -> None:
        self.version = version
        self.vector = vector
        self.attempted_versions = attempted_versions
        self.embedding_spec = embedding_spec or {}


_embedder_cache: dict[str, TextEmbedder] = {}
_embedder_lock = Lock()


def get_embedder(embedding_version: str | None = None) -> TextEmbedder:
    """Return a singleton embedding gateway client instance for the requested version."""
    cfg = get_settings()
    backend = cfg.resolve_embedding_backend(embedding_version)

    if backend.version in _embedder_cache:
        return _embedder_cache[backend.version]

    with _embedder_lock:
        if backend.version not in _embedder_cache:
            _embedder_cache[backend.version] = _build_embedder(backend)
    return _embedder_cache[backend.version]


def _version_has_queryable_tables(
    project_id: str,
    version: str,
    table_names: tuple[str, ...],
) -> bool:
    """Check if LanceDB contains queryable tables for the given embedding version or identity."""
    try:
        from infra.db import vector_table_exists
        for name in table_names:
            if vector_table_exists(name, project_id=project_id, embedding_version=version):
                return True
        return False
    except Exception:
        return True


def encode_query_with_fallback(
    query: str,
    *,
    project_id: str = "default",
    table_names: tuple[str, ...] = ("knowledge", "memories"),
) -> QueryEmbeddingRoute:
    """Encode search query via remote embedding gateway with candidate identity filtering."""
    cfg = get_settings()
    active_version = cfg.resolved_embedding_active_version

    # Collect candidate versions that have queryable tables
    candidate_versions: list[str] = []
    attempted_versions: list[dict[str, Any]] = []

    for version, identity in zip(
        cfg.resolved_embedding_version_order,
        cfg.resolved_embedding_query_identities,
    ):
        if not _version_has_queryable_tables(
            project_id,
            identity,
            table_names,
        ):
            attempted_versions.append(
                {
                    "version": version,
                    "status": "skipped",
                    "reason": "missing_tables",
                }
            )
            continue
        candidate_versions.append(identity)

    if not candidate_versions:
        raise RuntimeError("沒有可用的 embedding version 可供查詢")

    embedder = get_embedder(active_version)
    if hasattr(embedder, "encode_with_metadata"):
        try:
            vectors, spec, attempts = embedder.encode_with_metadata(
                [query],
                input_type="query",
                acceptable_identities=candidate_versions,
            )
            selected_identity = spec.get("identity", "") if spec else ""
            if selected_identity not in candidate_versions:
                raise RuntimeError("Gateway returned an unrequested embedding identity")
            return QueryEmbeddingRoute(
                version=selected_identity,
                vector=vectors[0],
                attempted_versions=attempts,
                embedding_spec=spec,
            )
        except Exception as exc:
            logger.warning("Gateway query encode failed: %s", exc)
            attempted_versions.append({"version": active_version, "status": "error", "reason": type(exc).__name__})
            raise RuntimeError(f"沒有可用的 embedding version 可供查詢: {exc}")

    # Fallback path for mock embedders
    for version in candidate_versions:
        try:
            vector = get_embedder().encode(
                [query],
                input_type="query",
                forced_identity=version,
            )[0]
            attempted_versions.append({"version": version, "status": "selected"})
            return QueryEmbeddingRoute(
                version=version,
                vector=vector,
                attempted_versions=attempted_versions,
            )
        except Exception as exc:
            attempted_versions.append({"version": version, "status": "error", "reason": type(exc).__name__})
            continue

    raise RuntimeError("沒有可用的 embedding version 可供查詢")


def _build_embedder(backend: EmbeddingBackend) -> TextEmbedder:
    cfg = get_settings()
    return GatewayRemoteTextEmbedder(
        base_url=backend.base_url or cfg.resolved_embedding_service_url,
        api_key=backend.api_key or cfg.embedding_service_token,
        timeout=cfg.embedding_service_timeout,
        chunk_size=cfg.embedding_service_chunk_size,
        expected_model=cfg.embedding_expected_model,
        expected_dimension=cfg.embedding_expected_dimension,
        version=backend.version,
        max_retries=cfg.embedding_service_max_retries,
        retry_base_delay=cfg.embedding_service_retry_base_delay,
        retry_max_delay=cfg.embedding_service_retry_max_delay,
    )


class GatewayRemoteTextEmbedder:
    """Remote embedding client connecting to the standalone embedding gateway over HTTP."""

    def __init__(
        self,
        base_url: str,
        api_key: str = "",
        timeout: float = 30.0,
        chunk_size: int = 32,
        expected_model: str = "BAAI/bge-m3",
        expected_dimension: int = 1024,
        version: str = "bge",
        max_retries: int = 3,
        retry_base_delay: float = 0.25,
        retry_max_delay: float = 8.0,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.api_key = api_key.strip()
        self.timeout = timeout
        self.chunk_size = max(1, chunk_size)
        self.expected_model = expected_model
        self.expected_dimension = expected_dimension
        self.version = version
        self.max_retries = max(0, max_retries)
        self.retry_base_delay = max(0.05, retry_base_delay)
        self.retry_max_delay = max(self.retry_base_delay, retry_max_delay)
        self._client: httpx.Client | None = None
        self._lock = Lock()

    def _get_client(self) -> httpx.Client:
        if self._client is not None:
            return self._client
        with self._lock:
            if self._client is None:
                headers = {}
                if self.api_key:
                    headers["Authorization"] = f"Bearer {self.api_key}"
                self._client = httpx.Client(
                    base_url=self.base_url,
                    headers=headers,
                    timeout=self.timeout,
                )
            return self._client

    def _post_chunk_with_retry(
        self,
        client: httpx.Client,
        payload: dict[str, Any],
        chunk_idx: int,
        chunk_len: int,
    ) -> dict[str, Any]:
        retryable_statuses = frozenset({429, 500, 502, 503, 504})
        last_exc: Exception | None = None

        for attempt in range(self.max_retries + 1):
            try:
                resp = client.post("/embed", json=payload)
                status_code = getattr(resp, "status_code", 200)
                if status_code in retryable_statuses and attempt < self.max_retries:
                    retry_headers = getattr(resp, "headers", {})
                    retry_after = _parse_retry_after(retry_headers.get("retry-after"), self.retry_max_delay)
                    if retry_after is not None:
                        delay = retry_after
                    else:
                        delay = min(
                            self.retry_base_delay * (2 ** attempt) + random.uniform(0.1, 0.4),
                            self.retry_max_delay,
                        )
                    logger.warning(
                        "Embedding gateway returned %d on chunk %d (len %d), retrying in %.2fs (attempt %d/%d)...",
                        status_code,
                        chunk_idx,
                        chunk_len,
                        delay,
                        attempt + 1,
                        self.max_retries,
                    )
                    time.sleep(delay)
                    continue
                resp.raise_for_status()
                return resp.json()
            except (httpx.TimeoutException, httpx.NetworkError) as exc:
                last_exc = exc
                if attempt < self.max_retries:
                    delay = min(
                        self.retry_base_delay * (2 ** attempt) + random.uniform(0.1, 0.4),
                        self.retry_max_delay,
                    )
                    logger.warning(
                        "Embedding gateway network/timeout error on chunk %d (%s), retrying in %.2fs (attempt %d/%d)...",
                        chunk_idx,
                        type(exc).__name__,
                        delay,
                        attempt + 1,
                        self.max_retries,
                    )
                    time.sleep(delay)
                    continue
                raise

        if last_exc is not None:
            raise last_exc
        raise RuntimeError(f"Embedding gateway chunk {chunk_idx} exhausted retries")

    def encode(
        self,
        texts: list[str],
        *,
        input_type: str = "document",
        acceptable_identities: list[str] | None = None,
        forced_identity: str | None = None,
    ) -> list[list[float]]:
        vectors, _, _ = self.encode_with_metadata(
            texts,
            input_type=input_type,
            acceptable_identities=acceptable_identities,
            forced_identity=forced_identity,
        )
        return vectors

    def encode_with_metadata(
        self,
        texts: list[str],
        *,
        input_type: str = "document",
        acceptable_identities: list[str] | None = None,
        forced_identity: str | None = None,
    ) -> tuple[list[list[float]], dict[str, Any], list[dict[str, Any]]]:
        if not texts:
            return [], {}, []

        client = self._get_client()
        all_vectors: list[list[float]] = []
        locked_spec: dict[str, Any] | None = None
        all_attempts: list[dict[str, Any]] = []

        active_identity = forced_identity
        leased_identity = forced_identity

        for i in range(0, len(texts), self.chunk_size):
            chunk = texts[i : i + self.chunk_size]
            payload: dict[str, Any] = {
                "texts": chunk,
                "input_type": input_type,
            }
            if active_identity:
                payload["identity"] = active_identity
            elif acceptable_identities:
                payload["acceptable_identities"] = acceptable_identities

            try:
                data = self._post_chunk_with_retry(client, payload, i // self.chunk_size, len(chunk))
            except Exception as exc:
                logger.error("Failed chunk embed request (range %d-%d): %s", i, i + len(chunk), exc)
                raise RuntimeError(f"Embedding gateway call failed: {exc}")

            chunk_vectors = data.get("vectors", [])
            chunk_spec = data.get("embedding_spec", {})
            chunk_attempts = data.get("attempts", [])

            if len(chunk_vectors) != len(chunk):
                raise RuntimeError(
                    f"Gateway returned {len(chunk_vectors)} vectors for {len(chunk)} inputs"
                )

            returned_identity = str(chunk_spec.get("identity", ""))
            if leased_identity and returned_identity != leased_identity:
                raise RuntimeError("Gateway returned an unrequested embedding identity")
            if (
                not active_identity
                and acceptable_identities
                and returned_identity not in acceptable_identities
            ):
                raise RuntimeError("Gateway returned an unrequested embedding identity")

            # Validate vector dimensions
            expected_dim = chunk_spec.get("dimensions") or self.expected_dimension
            for vec in chunk_vectors:
                if len(vec) != expected_dim:
                    raise ValueError(
                        f"Vector dimension mismatch: expected {expected_dim}, got {len(vec)}"
                    )

            # Enforce strict cross-chunk specification matching
            if locked_spec is None:
                locked_spec = chunk_spec
                active_identity = chunk_spec.get("identity")
            else:
                mismatch_fields = [
                    f"{field}: initial={locked_spec.get(field)!r} vs chunk_{i}={chunk_spec.get(field)!r}"
                    for field in (
                        "identity",
                        "model",
                        "dimensions",
                        "dtype",
                        "normalization",
                        "input_semantics",
                        "model_revision",
                    )
                    if locked_spec.get(field) != chunk_spec.get(field)
                ]
                if mismatch_fields:
                    msg = f"Embedding specification drift across chunks in single batch: {'; '.join(mismatch_fields)}"
                    logger.error(msg)
                    raise RuntimeError(msg)

            all_attempts.extend(chunk_attempts)
            all_vectors.extend(chunk_vectors)

        return all_vectors, locked_spec or {}, all_attempts

    def close(self) -> None:
        with self._lock:
            if self._client is not None:
                self._client.close()
                self._client = None


def encode_text(text: str, *, embedding_version: str | None = None) -> list[float]:
    """Encode a single string into a vector."""
    cfg = get_settings()
    value = embedding_version or cfg.resolved_embedding_active_version
    resolver = getattr(cfg, "resolve_embedding_identity", None)
    identity = (
        resolver(value, input_semantics="document")
        if callable(resolver)
        else value
    )
    return get_embedder().encode(
        [text],
        input_type="document",
        forced_identity=identity if ":" in identity else None,
    )[0]
