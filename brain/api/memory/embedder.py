"""Provider-aware embedding adapters for the active embedding version."""

from __future__ import annotations

import json
from dataclasses import dataclass
from threading import Lock
from typing import TYPE_CHECKING, Any, Protocol
from urllib import request

from FlagEmbedding import BGEM3FlagModel
from openai import OpenAI

from config import get_settings

if TYPE_CHECKING:
    from config import EmbeddingBackend

_embedder_cache: dict[str, "TextEmbedder"] = {}
_embedder_lock = Lock()
_encode_lock = Lock()


@dataclass(frozen=True, slots=True)
class QueryEmbeddingRoute:
    """Resolved query vector and the embedding version used to produce it."""

    version: str
    vector: list[float]
    attempted_versions: list[dict[str, str]]


class TextEmbedder(Protocol):
    def encode(
        self,
        texts: list[str],
        *,
        input_type: str = "document",
    ) -> list[list[float]]:
        ...


def get_embedder(embedding_version: str | None = None) -> TextEmbedder:
    """Return the cached text embedder for the active embedding version."""
    backend = get_settings().resolve_embedding_backend(embedding_version)
    if backend.version in _embedder_cache:
        return _embedder_cache[backend.version]

    with _embedder_lock:
        if backend.version not in _embedder_cache:
            _embedder_cache[backend.version] = _build_embedder(backend)
    return _embedder_cache[backend.version]


def encode_query_with_fallback(
    query: str,
    *,
    project_id: str = "default",
    table_names: tuple[str, ...] = ("knowledge", "memories"),
) -> QueryEmbeddingRoute:
    """Encode a search query using the first queryable embedding version."""
    cfg = get_settings()
    active_version = cfg.resolved_embedding_active_version
    attempted_versions: list[dict[str, str]] = []

    for version in cfg.resolved_embedding_version_order:
        if version != active_version and not _version_has_queryable_tables(
            project_id,
            version,
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
        try:
            vector = get_embedder(version).encode([query], input_type="query")[0]
        except Exception as exc:
            attempted_versions.append(
                {
                    "version": version,
                    "status": "error",
                    "reason": type(exc).__name__,
                }
            )
            continue
        attempted_versions.append({"version": version, "status": "selected"})
        return QueryEmbeddingRoute(
            version=version,
            vector=vector,
            attempted_versions=attempted_versions,
        )

    raise RuntimeError("沒有可用的 embedding version 可供查詢")


def _build_embedder(backend: EmbeddingBackend) -> TextEmbedder:
    if backend.provider == "bge":
        return BgeTextEmbedder(
            BGEM3FlagModel(
                backend.model,
                use_fp16=backend.use_fp16,
                device=backend.device,
            )
        )
    if backend.provider == "gemini":
        _require_api_key(backend)
        return GeminiTextEmbedder(backend)
    if backend.provider == "openai":
        _require_api_key(backend)
        return OpenAITextEmbedder(backend)
    if backend.provider == "voyage":
        _require_api_key(backend)
        return VoyageTextEmbedder(backend)
    raise ValueError(f"embedding provider 不支援: {backend.provider}")


def _require_api_key(backend: EmbeddingBackend) -> None:
    if backend.api_key.strip():
        return
    raise RuntimeError(f"{backend.version} embedding API key 未設定")


class BgeTextEmbedder:
    """Local BGE embedder backed by FlagEmbedding."""

    def __init__(self, model: BGEM3FlagModel) -> None:
        self._model = model

    def encode(
        self,
        texts: list[str],
        *,
        input_type: str = "document",
    ) -> list[list[float]]:
        del input_type
        with _encode_lock:
            result = self._model.encode(texts)
        dense_vectors = result["dense_vecs"]
        return [vector.tolist() for vector in dense_vectors]


class OpenAITextEmbedder:
    """OpenAI-compatible text embeddings."""

    def __init__(self, backend: EmbeddingBackend) -> None:
        client_kwargs: dict[str, Any] = {"api_key": backend.api_key}
        if backend.base_url:
            client_kwargs["base_url"] = backend.base_url
        self._client = OpenAI(**client_kwargs)
        self._model = backend.model
        self._dimensions = backend.dimensions

    def encode(
        self,
        texts: list[str],
        *,
        input_type: str = "document",
    ) -> list[list[float]]:
        del input_type
        request_kwargs: dict[str, Any] = {
            "model": self._model,
            "input": texts,
        }
        if self._dimensions is not None:
            request_kwargs["dimensions"] = self._dimensions
        response = self._client.embeddings.create(**request_kwargs)
        return [list(item.embedding) for item in response.data]


class GeminiTextEmbedder:
    """Gemini batch embeddings using the direct Google API."""

    def __init__(self, backend: EmbeddingBackend) -> None:
        self._api_key = backend.api_key
        self._model = backend.model
        self._dimensions = backend.dimensions
        self._base_url = backend.base_url.rstrip("/") or "https://generativelanguage.googleapis.com/v1beta"

    def encode(
        self,
        texts: list[str],
        *,
        input_type: str = "document",
    ) -> list[list[float]]:
        requests_payload: list[dict[str, Any]] = []
        for text in texts:
            request_payload: dict[str, Any] = {
                "model": f"models/{self._model}",
                "content": {"parts": [{"text": text}]},
                "taskType": _resolve_gemini_task_type(input_type),
            }
            if self._dimensions is not None:
                request_payload["outputDimensionality"] = self._dimensions
            requests_payload.append(request_payload)

        response = _post_json(
            url=f"{self._base_url}/models/{self._model}:batchEmbedContents",
            headers={"x-goog-api-key": self._api_key},
            payload={"requests": requests_payload},
        )
        embeddings = response.get("embeddings", [])
        return [list(item.get("values", [])) for item in embeddings]


class VoyageTextEmbedder:
    """Voyage text embeddings via HTTPS API."""

    def __init__(self, backend: EmbeddingBackend) -> None:
        self._api_key = backend.api_key
        self._model = backend.model
        self._dimensions = backend.dimensions
        self._base_url = backend.base_url.rstrip("/") or "https://api.voyageai.com/v1"

    def encode(
        self,
        texts: list[str],
        *,
        input_type: str = "document",
    ) -> list[list[float]]:
        payload: dict[str, Any] = {
            "input": texts,
            "model": self._model,
            "input_type": "query" if input_type == "query" else "document",
        }
        if self._dimensions is not None:
            payload["output_dimension"] = self._dimensions

        response = _post_json(
            url=f"{self._base_url}/embeddings",
            headers={"Authorization": f"Bearer {self._api_key}"},
            payload=payload,
        )
        return [list(item.get("embedding", [])) for item in response.get("data", [])]


def _post_json(
    *,
    url: str,
    headers: dict[str, str],
    payload: dict[str, Any],
) -> dict[str, Any]:
    request_headers = {
        "Content-Type": "application/json",
        **headers,
    }
    body = json.dumps(payload).encode("utf-8")
    req = request.Request(url, data=body, headers=request_headers, method="POST")
    with request.urlopen(req, timeout=60) as response:
        parsed = json.loads(response.read().decode("utf-8"))
    return parsed if isinstance(parsed, dict) else {}


def _resolve_gemini_task_type(input_type: str) -> str:
    return "RETRIEVAL_QUERY" if input_type == "query" else "RETRIEVAL_DOCUMENT"


def _version_has_queryable_tables(
    project_id: str,
    embedding_version: str,
    table_names: tuple[str, ...],
) -> bool:
    from infra.db import vector_table_exists

    unique_tables = {name.strip() for name in table_names if name.strip()}
    return any(
        vector_table_exists(table_name, project_id, embedding_version)
        for table_name in unique_tables
    )


def encode_text(
    text: str,
    embedding_version: str | None = None,
) -> list[float]:
    """Encode a single text using the active embedding version."""
    return get_embedder(embedding_version).encode([text])[0]
