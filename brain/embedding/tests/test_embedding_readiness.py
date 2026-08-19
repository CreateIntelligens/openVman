"""Readiness and authentication tests for embedding-service."""

from __future__ import annotations

from typing import Any
from fastapi.testclient import TestClient
import pytest

try:
    import brain.embedding.app as embedding_app
    from brain.embedding.identity import EmbeddingSpec, make_canonical_identity
    from brain.embedding.registry import ProviderRegistry
    from brain.embedding.tests.fixtures.embedding_fixtures import (
        EXPECTED_BGE_MODEL,
        EXPECTED_DENSE_DIMENSION,
    )
except ModuleNotFoundError:
    try:
        import app.app as embedding_app
    except ModuleNotFoundError:
        import app as embedding_app
    from identity import EmbeddingSpec, make_canonical_identity
    from registry import ProviderRegistry
    from tests.fixtures.embedding_fixtures import (
        EXPECTED_BGE_MODEL,
        EXPECTED_DENSE_DIMENSION,
    )


class MockHealthyProvider:
    def __init__(self, spec: EmbeddingSpec) -> None:
        self._spec = spec

    @property
    def is_configured(self) -> bool:
        return True

    def spec(self, input_semantics: str = "document") -> EmbeddingSpec:
        return self._spec

    async def is_ready(self) -> bool:
        return True

    async def warmup(self) -> None:
        pass

    async def encode(self, texts: list[str], *, input_type: str = "document") -> list[list[float]]:
        return [[0.0] * self._spec.dimensions for _ in texts]

    async def shutdown(self) -> None:
        pass


class MockFailingWarmupProvider:
    def __init__(self, spec: EmbeddingSpec) -> None:
        self._spec = spec

    @property
    def is_configured(self) -> bool:
        return True

    def spec(self, input_semantics: str = "document") -> EmbeddingSpec:
        return self._spec

    async def is_ready(self) -> bool:
        return False

    async def warmup(self) -> None:
        raise RuntimeError("CUDA out of memory during warmup encode")

    async def encode(self, texts: list[str], *, input_type: str = "document") -> list[list[float]]:
        raise RuntimeError("CUDA out of memory")

    async def shutdown(self) -> None:
        pass


def test_health_ready_metadata(monkeypatch):
    reg = ProviderRegistry()
    spec = EmbeddingSpec(
        identity=make_canonical_identity("bge", EXPECTED_BGE_MODEL, EXPECTED_DENSE_DIMENSION, "float32", "l2", "document", "default"),
        provider="bge",
        model=EXPECTED_BGE_MODEL,
        dimensions=EXPECTED_DENSE_DIMENSION,
    )
    reg.register("bge", MockHealthyProvider(spec))
    monkeypatch.setattr(embedding_app, "_get_registry", lambda: reg)
    monkeypatch.setattr(embedding_app, "BEARER_TOKEN", "")

    client = TestClient(embedding_app.app)
    response = client.get("/health/ready")
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "ready"
    assert data["model"] == EXPECTED_BGE_MODEL
    assert data["dimension"] == EXPECTED_DENSE_DIMENSION
    assert data["normalization"] == "l2"
    assert "embedding_spec" in data
    assert "available_providers" in data


def test_health_ready_failure_on_warmup_error(monkeypatch):
    reg = ProviderRegistry()
    spec = EmbeddingSpec(
        identity=make_canonical_identity("bge", EXPECTED_BGE_MODEL, EXPECTED_DENSE_DIMENSION, "float32", "l2", "document", "default"),
        provider="bge",
        model=EXPECTED_BGE_MODEL,
        dimensions=EXPECTED_DENSE_DIMENSION,
    )
    reg.register("bge", MockFailingWarmupProvider(spec))
    monkeypatch.setattr(embedding_app, "_get_registry", lambda: reg)
    monkeypatch.setattr(embedding_app, "BEARER_TOKEN", "")

    client = TestClient(embedding_app.app)
    response = client.get("/health/ready")
    assert response.status_code == 503
    assert "CUDA out of memory" in str(response.json()["detail"])


def test_bearer_token_enforcement(monkeypatch):
    secret_token = "super-secret-token-xyz-123"
    monkeypatch.setattr(embedding_app, "BEARER_TOKEN", secret_token)

    reg = ProviderRegistry()
    spec = EmbeddingSpec(
        identity=make_canonical_identity("bge", EXPECTED_BGE_MODEL, EXPECTED_DENSE_DIMENSION, "float32", "l2", "document", "default"),
        provider="bge",
        model=EXPECTED_BGE_MODEL,
        dimensions=EXPECTED_DENSE_DIMENSION,
    )
    reg.register("bge", MockHealthyProvider(spec))
    monkeypatch.setattr(embedding_app, "_get_registry", lambda: reg)

    client = TestClient(embedding_app.app)

    # 1. Missing Authorization header -> 401
    res_no_auth = client.post("/embed", json={"texts": ["hello"]})
    assert res_no_auth.status_code == 401
    assert "Authorization" in res_no_auth.json()["detail"]
    assert secret_token not in str(res_no_auth.json())

    # 2. Invalid token -> 401
    res_bad_auth = client.post(
        "/embed",
        json={"texts": ["hello"]},
        headers={"Authorization": "Bearer wrong-token"},
    )
    assert res_bad_auth.status_code == 401

    # 3. Valid token -> 200
    res_valid_auth = client.post(
        "/embed",
        json={"texts": ["hello"]},
        headers={"Authorization": f"Bearer {secret_token}"},
    )
    assert res_valid_auth.status_code == 200
    assert len(res_valid_auth.json()["vectors"]) == 1


def test_bearer_token_ready_endpoint(monkeypatch):
    secret_token = "ready-token-abc-456"
    monkeypatch.setattr(embedding_app, "BEARER_TOKEN", secret_token)

    reg = ProviderRegistry()
    spec = EmbeddingSpec(
        identity=make_canonical_identity("bge", EXPECTED_BGE_MODEL, EXPECTED_DENSE_DIMENSION, "float32", "l2", "document", "default"),
        provider="bge",
        model=EXPECTED_BGE_MODEL,
        dimensions=EXPECTED_DENSE_DIMENSION,
    )
    reg.register("bge", MockHealthyProvider(spec))
    monkeypatch.setattr(embedding_app, "_get_registry", lambda: reg)

    client = TestClient(embedding_app.app)

    # Unauthenticated /health/ready -> 401
    res_unauth = client.get("/health/ready")
    assert res_unauth.status_code == 401

    # Authenticated /health/ready -> 200
    res_auth = client.get(
        "/health/ready",
        headers={"Authorization": f"Bearer {secret_token}"},
    )
    assert res_auth.status_code == 200
    assert res_auth.json()["status"] == "ready"
