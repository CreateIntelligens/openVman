"""Contract tests for JTAI /embed, OpenAI /v1/embeddings, and GET /v1/models."""

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
        validate_vector_contract,
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
        validate_vector_contract,
    )


class MockProvider:
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
        res = []
        for idx, _ in enumerate(texts):
            vec = [float(idx + 1) * 0.001] * self._spec.dimensions
            res.append(vec)
        return res

    async def shutdown(self) -> None:
        pass


@pytest.fixture(autouse=True)
def mock_registry(monkeypatch):
    reg = ProviderRegistry(cooldown_seconds=10.0)
    bge_spec = EmbeddingSpec(
        identity=make_canonical_identity("bge", EXPECTED_BGE_MODEL, EXPECTED_DENSE_DIMENSION, "float32", "l2", "document", "default"),
        provider="bge",
        model=EXPECTED_BGE_MODEL,
        dimensions=EXPECTED_DENSE_DIMENSION,
        dtype="float32",
        normalized=True,
        normalization="l2",
        input_semantics="document",
        model_revision="default",
        service_revision="1.0.0",
    )
    reg.register("bge", MockProvider(bge_spec))
    monkeypatch.setattr(embedding_app, "_get_registry", lambda: reg)
    monkeypatch.setattr(embedding_app, "BEARER_TOKEN", "embedding-test-token")


def test_health_liveness():
    client = TestClient(embedding_app.app, headers={"Authorization": "Bearer embedding-test-token"})
    response = client.get("/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok", "service": "embedding-service"}


def test_v1_models_endpoint():
    client = TestClient(embedding_app.app, headers={"Authorization": "Bearer embedding-test-token"})
    response = client.get("/v1/models")
    assert response.status_code == 200
    data = response.json()
    assert data["object"] == "list"
    assert len(data["data"]) >= 1
    m0 = data["data"][0]
    assert m0["id"] == EXPECTED_BGE_MODEL
    assert m0["dimensions"] == EXPECTED_DENSE_DIMENSION
    assert "identity" in m0


def test_jtai_embed_endpoint():
    client = TestClient(embedding_app.app, headers={"Authorization": "Bearer embedding-test-token"})
    payload = {
        "texts": ["第一段文字測試", "第二段文字測試", "第三段文字測試"],
        "input_type": "document",
    }
    response = client.post("/embed", json=payload)
    assert response.status_code == 200
    data = response.json()
    assert "vectors" in data
    assert "embedding_spec" in data
    assert data["model"] == EXPECTED_BGE_MODEL
    assert data["embedding_spec"]["dimensions"] == EXPECTED_DENSE_DIMENSION
    assert data["embedding_spec"]["provider"] == "bge"
    assert len(data["attempts"]) == 1
    assert data["attempts"][0]["status"] == "selected"

    vectors = data["vectors"]
    validate_vector_contract(vectors, 3)
    assert vectors[0][0] != vectors[1][0]
    assert vectors[1][0] != vectors[2][0]


def test_jtai_embed_empty_batch():
    client = TestClient(embedding_app.app, headers={"Authorization": "Bearer embedding-test-token"})
    response = client.post("/embed", json={"texts": [], "input_type": "query"})
    assert response.status_code == 200
    data = response.json()
    assert data["vectors"] == []
    assert data["model"] == EXPECTED_BGE_MODEL
    assert "embedding_spec" in data


def test_jtai_embed_empty_batch_invalid_identity():
    client = TestClient(embedding_app.app, headers={"Authorization": "Bearer embedding-test-token"})
    response = client.post("/embed", json={"texts": [], "identity": "invalid:identity:999"})
    assert response.status_code == 400


def test_jtai_embed_invalid_payload():
    client = TestClient(embedding_app.app, headers={"Authorization": "Bearer embedding-test-token"})
    response = client.post("/embed", json={"input_type": "query"})
    assert response.status_code == 422


def test_openai_embeddings_single_string():
    client = TestClient(embedding_app.app, headers={"Authorization": "Bearer embedding-test-token"})
    payload = {
        "input": "測試單一字串嵌入",
        "model": EXPECTED_BGE_MODEL,
    }
    response = client.post("/v1/embeddings", json=payload)
    assert response.status_code == 200
    data = response.json()
    assert data["object"] == "list"
    assert len(data["data"]) == 1
    assert data["data"][0]["index"] == 0
    assert len(data["data"][0]["embedding"]) == EXPECTED_DENSE_DIMENSION
    assert data["model"] == EXPECTED_BGE_MODEL
    assert "openvman_embedding_spec" in data
    assert data["openvman_embedding_spec"]["dimensions"] == EXPECTED_DENSE_DIMENSION


def test_openai_embeddings_rejects_unsupported_model():
    client = TestClient(embedding_app.app, headers={"Authorization": "Bearer embedding-test-token"})
    payload = {
        "input": "測試不支援的模型",
        "model": "not-the-served-model",
    }
    response = client.post("/v1/embeddings", json=payload)
    assert response.status_code == 400
    assert "not exist or is not served" in response.json()["detail"]


def test_openai_embeddings_batch_order_preservation():
    client = TestClient(embedding_app.app, headers={"Authorization": "Bearer embedding-test-token"})
    inputs = ["文字 A", "文字 B", "文字 C", "文字 D"]
    payload = {"input": inputs}
    response = client.post("/v1/embeddings", json=payload)
    assert response.status_code == 200
    data = response.json()
    assert len(data["data"]) == 4
    for idx, item in enumerate(data["data"]):
        assert item["index"] == idx
        assert len(item["embedding"]) == EXPECTED_DENSE_DIMENSION


def test_max_request_texts_limit():
    client = TestClient(embedding_app.app, headers={"Authorization": "Bearer embedding-test-token"})
    oversized = [f"text_{i}" for i in range(embedding_app.MAX_REQUEST_TEXTS + 1)]
    response = client.post("/embed", json={"texts": oversized})
    assert response.status_code == 413
