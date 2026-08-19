"""Unit tests for remote Gateway embedding adapter, readiness, and candidate routing."""

from __future__ import annotations

import httpx
import pytest

from config import BrainSettings
from health_payload import build_readiness_payload, check_embedding_service_readiness
from memory.embedder import (
    GatewayRemoteTextEmbedder,
    QueryEmbeddingRoute,
    encode_query_with_fallback,
    get_embedder,
)


def test_external_url_precedence_and_internal_default():
    # 1. Unset URL -> internal default
    cfg_default = BrainSettings(embedding_service_url="")
    assert cfg_default.resolved_embedding_service_url == "http://embedding:8009"
    assert cfg_default.is_embedding_service_external is False

    # 2. Explicit external URL -> external precedence
    cfg_external = BrainSettings(embedding_service_url="http://shared-gpu-node:8009")
    assert cfg_external.resolved_embedding_service_url == "http://shared-gpu-node:8009"
    assert cfg_external.is_embedding_service_external is True


def test_remote_adapter_chunks_requests_and_leases_identity(monkeypatch):
    recorded_batches: list[list[str]] = []

    def mock_post(self, endpoint, json=None, **kwargs):
        texts = json.get("texts", [])
        recorded_batches.append(texts)
        vectors = [[0.1 * (i + 1)] * 1024 for i in range(len(texts))]
        request = httpx.Request("POST", f"http://test{endpoint}", json=json)
        return httpx.Response(
            200,
            json={
                "vectors": vectors,
                "model": "BAAI/bge-m3",
                "embedding_spec": {
                    "identity": "bge:BAAI/bge-m3:1024:float32:l2:1.0.0",
                    "provider": "bge",
                    "dimensions": 1024,
                },
                "attempts": [{"provider": "bge", "status": "selected"}],
            },
            request=request,
        )

    monkeypatch.setattr(httpx.Client, "post", mock_post)

    adapter = GatewayRemoteTextEmbedder(
        base_url="http://fake-embedding:8009",
        chunk_size=2,
        expected_dimension=1024,
    )
    texts = ["t1", "t2", "t3", "t4", "t5"]
    vectors, spec, attempts = adapter.encode_with_metadata(texts, input_type="document")

    assert len(vectors) == 5
    assert len(recorded_batches) == 3
    assert recorded_batches == [["t1", "t2"], ["t3", "t4"], ["t5"]]
    assert len(vectors[0]) == 1024
    assert spec["identity"] == "bge:BAAI/bge-m3:1024:float32:l2:1.0.0"
    assert len(attempts) >= 1


def test_remote_adapter_rejects_dimension_mismatch(monkeypatch):
    def mock_post(self, endpoint, json=None, **kwargs):
        texts = json.get("texts", [])
        # Return 512-dim vector when 1024 expected
        vectors = [[0.1] * 512 for _ in texts]
        request = httpx.Request("POST", f"http://test{endpoint}", json=json)
        return httpx.Response(
            200,
            json={
                "vectors": vectors,
                "embedding_spec": {"dimensions": 1024, "identity": "fake"},
            },
            request=request,
        )

    monkeypatch.setattr(httpx.Client, "post", mock_post)

    adapter = GatewayRemoteTextEmbedder(
        base_url="http://fake-embedding:8009",
        expected_dimension=1024,
    )
    with pytest.raises(ValueError) as exc:
        adapter.encode(["test query"])
    assert "Vector dimension mismatch" in str(exc.value)


def test_remote_adapter_connection_error(monkeypatch):
    def mock_post_err(self, endpoint, **kwargs):
        raise httpx.ConnectError("Connection refused")

    monkeypatch.setattr(httpx.Client, "post", mock_post_err)

    adapter = GatewayRemoteTextEmbedder(base_url="http://broken:8009")
    with pytest.raises(RuntimeError) as exc:
        adapter.encode(["test query"])
    assert "Embedding gateway call failed" in str(exc.value)


def test_readiness_incompatible_model(monkeypatch):
    def mock_get(self, url, **kwargs):
        req = httpx.Request("GET", url)
        return httpx.Response(
            200,
            json={
                "status": "ready",
                "model": "wrong/model-v1",
                "dimension": 1024,
            },
            request=req,
        )

    monkeypatch.setattr(httpx.Client, "get", mock_get)

    cfg = BrainSettings(
        embedding_active_version="bge",
        embedding_service_url="http://shared:8009",
        embedding_expected_model="BAAI/bge-m3",
    )
    ok, info = check_embedding_service_readiness(cfg)
    assert ok is False
    assert info["status"] == "incompatible"
    assert "Model mismatch" in info["error"]


def test_readiness_incompatible_dimension(monkeypatch):
    def mock_get(self, url, **kwargs):
        req = httpx.Request("GET", url)
        return httpx.Response(
            200,
            json={
                "status": "ready",
                "model": "BAAI/bge-m3",
                "dimension": 512,
            },
            request=req,
        )

    monkeypatch.setattr(httpx.Client, "get", mock_get)

    cfg = BrainSettings(
        embedding_active_version="bge",
        embedding_service_url="http://shared:8009",
        embedding_expected_dimension=1024,
    )
    ok, info = check_embedding_service_readiness(cfg)
    assert ok is False
    assert info["status"] == "incompatible"
    assert "Dimension mismatch" in info["error"]
