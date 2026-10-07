"""Tests for Brain's remote embedding gateway client and fallback routing."""

from __future__ import annotations

import sys
import types
from pathlib import Path

import pytest

API_ROOT = Path(__file__).resolve().parents[1]
if str(API_ROOT) not in sys.path:
    sys.path.insert(0, str(API_ROOT))

from config import BrainSettings
from memory.embedder import (
    GatewayRemoteTextEmbedder,
    encode_query_with_fallback,
    get_embedder,
)


def test_gateway_remote_embedder_calls_gateway_and_parses_spec(monkeypatch):
    embedder = GatewayRemoteTextEmbedder(
        base_url="http://fake-embedding:8009",
        expected_model="google/embeddinggemma-2",
        expected_dimension=768,
    )

    class FakeResponse:
        def raise_for_status(self):
            pass

        def json(self):
            return {
                "vectors": [[0.1] * 768],
                "model": "google/embeddinggemma-2",
                "embedding_spec": {
                    "identity": "gemma:google/embeddinggemma-2:768:float32:l2:document:default",
                    "provider": "gemma",
                    "model": "google/embeddinggemma-2",
                    "dimensions": 768,
                    "dtype": "float32",
                    "normalization": "l2",
                    "input_semantics": "document",
                    "model_revision": "default",
                },
                "attempts": [{"provider": "gemma", "status": "selected"}],
            }

    class FakeClient:
        def post(self, url, json=None):
            assert url == "/embed"
            assert json["texts"] == ["hello"]
            return FakeResponse()

    monkeypatch.setattr(embedder, "_get_client", lambda: FakeClient())

    vectors, spec, attempts = embedder.encode_with_metadata(["hello"])
    assert len(vectors) == 1
    assert len(vectors[0]) == 768
    assert spec["provider"] == "gemma"
    assert spec["dimensions"] == 768
    assert attempts[0]["status"] == "selected"


def test_gateway_remote_embedder_rejects_identity_drift_across_chunks(monkeypatch):
    embedder = GatewayRemoteTextEmbedder(
        base_url="http://fake-embedding:8009",
        chunk_size=2,
        expected_dimension=768,
    )

    call_count = 0

    class FakeResponse:
        def __init__(self, spec, vectors):
            self._spec = spec
            self._vectors = vectors

        def raise_for_status(self):
            pass

        def json(self):
            return {
                "vectors": self._vectors,
                "model": self._spec["model"],
                "embedding_spec": self._spec,
                "attempts": [],
            }

    class FakeClient:
        def post(self, url, json=None):
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                # First chunk returns the gemma identity
                return FakeResponse(
                    spec={
                        "identity": "gemma:google/embeddinggemma-2:768:float32:l2:document:default",
                        "provider": "gemma",
                        "model": "google/embeddinggemma-2",
                        "dimensions": 768,
                    },
                    vectors=[[0.1] * 768, [0.2] * 768],
                )
            # Second chunk drifts to another revision
            return FakeResponse(
                spec={
                    "identity": "gemma:google/embeddinggemma-2:768:float32:l2:document:rev-two",
                    "provider": "gemma",
                    "model": "google/embeddinggemma-2",
                    "dimensions": 768,
                },
                vectors=[[0.3] * 768, [0.4] * 768],
            )

    monkeypatch.setattr(embedder, "_get_client", lambda: FakeClient())

    with pytest.raises(RuntimeError) as exc_info:
        embedder.encode_with_metadata(["a", "b", "c", "d"])

    assert "specification drift across chunks" in str(exc_info.value)


GEMMA_QUERY = "gemma:google/embeddinggemma-2:768:float32:l2:query:rev-one"
NEXT_QUERY = "next:fake/next-model:512:float32:l2:query:rev-one"


def _two_version_settings():
    # config 只接受 gemma 一個版本；版本 fallback 機制本身仍要測，所以用假設定給兩個版本。
    return types.SimpleNamespace(
        resolved_embedding_active_version="gemma",
        resolved_embedding_version_order=["gemma", "next"],
        resolved_embedding_query_identities=[GEMMA_QUERY, NEXT_QUERY],
    )


def _fake_tables(monkeypatch, existing):
    fake_db_mod = types.ModuleType("infra.db")
    fake_db_mod.vector_table_exists = (
        lambda table_name, project_id="default", embedding_version=None: embedding_version
        in existing
    )
    monkeypatch.setitem(sys.modules, "infra.db", fake_db_mod)


def test_encode_query_with_fallback_uses_the_gemma_query_identity(monkeypatch):
    settings = BrainSettings()
    monkeypatch.setattr("memory.embedder.get_settings", lambda: settings)
    [gemma_identity] = settings.resolved_embedding_query_identities
    _fake_tables(monkeypatch, {gemma_identity})

    class FakeEmbedder:
        def encode_with_metadata(self, texts, input_type="document", acceptable_identities=None, forced_identity=None):
            assert input_type == "query"
            assert acceptable_identities == [gemma_identity]
            return (
                [[0.4] * 768],
                {"identity": gemma_identity, "provider": "gemma", "dimensions": 768},
                [{"provider": "gemma", "status": "selected"}],
            )

    monkeypatch.setattr("memory.embedder.get_embedder", lambda version=None: FakeEmbedder())

    route = encode_query_with_fallback("什麼是 ESG？", project_id="test-proj")
    assert route.version == gemma_identity
    assert len(route.vector) == 768


def test_encode_query_with_fallback_passes_acceptable_identities_and_selects_provider(monkeypatch):
    monkeypatch.setattr("memory.embedder.get_settings", _two_version_settings)
    _fake_tables(monkeypatch, {GEMMA_QUERY, NEXT_QUERY})

    class FakeEmbedder:
        def encode_with_metadata(self, texts, input_type="document", acceptable_identities=None, forced_identity=None):
            assert input_type == "query"
            assert acceptable_identities == [GEMMA_QUERY, NEXT_QUERY]
            return (
                [[0.4] * 512],
                {"identity": NEXT_QUERY, "provider": "next", "dimensions": 512},
                [
                    {"provider": "gemma", "status": "error", "reason": "timeout"},
                    {"provider": "next", "status": "selected"},
                ],
            )

    monkeypatch.setattr("memory.embedder.get_embedder", lambda version=None: FakeEmbedder())

    route = encode_query_with_fallback("什麼是 ESG？", project_id="test-proj")
    assert route.version == NEXT_QUERY
    assert len(route.vector) == 512
    assert len(route.attempted_versions) == 2
    assert route.attempted_versions[1]["status"] == "selected"


def test_encode_query_with_fallback_skips_versions_without_tables(monkeypatch):
    monkeypatch.setattr("memory.embedder.get_settings", _two_version_settings)
    _fake_tables(monkeypatch, {NEXT_QUERY})

    class FakeEmbedder:
        def encode_with_metadata(self, texts, input_type="document", acceptable_identities=None, forced_identity=None):
            assert acceptable_identities == [NEXT_QUERY]
            return (
                [[0.8] * 512],
                {"identity": NEXT_QUERY, "provider": "next", "dimensions": 512},
                [{"provider": "next", "status": "selected"}],
            )

    monkeypatch.setattr("memory.embedder.get_embedder", lambda version=None: FakeEmbedder())

    route = encode_query_with_fallback("查詢文字", project_id="test-proj")
    assert route.version == NEXT_QUERY
    assert len(route.vector) == 512


def test_encode_query_with_fallback_rejects_an_unrequested_identity(monkeypatch):
    monkeypatch.setattr("memory.embedder.get_settings", _two_version_settings)
    _fake_tables(monkeypatch, {GEMMA_QUERY})

    class FakeEmbedder:
        def encode_with_metadata(self, texts, input_type="document", acceptable_identities=None, forced_identity=None):
            return (
                [[0.8] * 512],
                {"identity": NEXT_QUERY, "provider": "next", "dimensions": 512},
                [],
            )

    monkeypatch.setattr("memory.embedder.get_embedder", lambda version=None: FakeEmbedder())

    with pytest.raises(RuntimeError):
        encode_query_with_fallback("查詢文字", project_id="test-proj")
