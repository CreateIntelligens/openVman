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
        expected_model="BAAI/bge-m3",
        expected_dimension=1024,
    )

    class FakeResponse:
        def raise_for_status(self):
            pass

        def json(self):
            return {
                "vectors": [[0.1] * 1024],
                "model": "BAAI/bge-m3",
                "embedding_spec": {
                    "identity": "bge:BAAI/bge-m3:1024:float32:l2:document:default",
                    "provider": "bge",
                    "model": "BAAI/bge-m3",
                    "dimensions": 1024,
                    "dtype": "float32",
                    "normalization": "l2",
                    "input_semantics": "document",
                    "model_revision": "default",
                },
                "attempts": [{"provider": "bge", "status": "selected"}],
            }

    class FakeClient:
        def post(self, url, json=None):
            assert url == "/embed"
            assert json["texts"] == ["hello"]
            return FakeResponse()

    monkeypatch.setattr(embedder, "_get_client", lambda: FakeClient())

    vectors, spec, attempts = embedder.encode_with_metadata(["hello"])
    assert len(vectors) == 1
    assert len(vectors[0]) == 1024
    assert spec["provider"] == "bge"
    assert spec["dimensions"] == 1024
    assert attempts[0]["status"] == "selected"


def test_gateway_remote_embedder_rejects_identity_drift_across_chunks(monkeypatch):
    embedder = GatewayRemoteTextEmbedder(
        base_url="http://fake-embedding:8009",
        chunk_size=2,
        expected_dimension=1024,
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
                # First chunk returns BGE
                return FakeResponse(
                    spec={
                        "identity": "bge:BAAI/bge-m3:1024:float32:l2:document:default",
                        "provider": "bge",
                        "model": "BAAI/bge-m3",
                        "dimensions": 1024,
                    },
                    vectors=[[0.1] * 1024, [0.2] * 1024],
                )
            # Second chunk returns drifted Gemini
            return FakeResponse(
                spec={
                    "identity": "gemini:text-embedding-004:768:float32:l2:document:default",
                    "provider": "gemini",
                    "model": "text-embedding-004",
                    "dimensions": 768,
                },
                vectors=[[0.3] * 768, [0.4] * 768],
            )

    monkeypatch.setattr(embedder, "_get_client", lambda: FakeClient())

    with pytest.raises(RuntimeError) as exc_info:
        embedder.encode_with_metadata(["a", "b", "c", "d"])

    assert "specification drift across chunks" in str(exc_info.value)


def test_encode_query_with_fallback_passes_acceptable_identities_and_selects_provider(monkeypatch):
    settings = BrainSettings(
        embedding_active_version="bge",
        embedding_version_order="bge,gemini,openai",
    )
    monkeypatch.setattr("config.get_settings", lambda: settings)

    fake_db_mod = types.ModuleType("infra.db")
    bge_identity, gemini_identity, _ = settings.resolved_embedding_query_identities
    fake_db_mod.vector_table_exists = (
        lambda table_name, project_id="default", embedding_version=None: embedding_version
        in (bge_identity, gemini_identity)
    )
    monkeypatch.setitem(sys.modules, "infra.db", fake_db_mod)

    class FakeEmbedder:
        def encode_with_metadata(self, texts, input_type="document", acceptable_identities=None, forced_identity=None):
            assert input_type == "query"
            assert acceptable_identities == [bge_identity, gemini_identity]
            return (
                [[0.4] * 768],
                {
                    "identity": gemini_identity,
                    "provider": "gemini",
                    "model": "text-embedding-004",
                    "dimensions": 768,
                },
                [
                    {"provider": "bge", "status": "error", "reason": "timeout"},
                    {"provider": "gemini", "status": "selected"},
                ],
            )

    monkeypatch.setattr("memory.embedder.get_embedder", lambda version=None: FakeEmbedder())

    route = encode_query_with_fallback("什麼是 ESG？", project_id="test-proj")
    assert route.version == gemini_identity
    assert len(route.vector) == 768
    assert len(route.attempted_versions) == 2
    assert route.attempted_versions[1]["status"] == "selected"


def test_encode_query_with_fallback_skips_versions_without_tables(monkeypatch):
    settings = BrainSettings(
        embedding_active_version="bge",
        embedding_version_order="bge,gemini,openai",
    )
    monkeypatch.setattr("config.get_settings", lambda: settings)

    fake_db_mod = types.ModuleType("infra.db")
    # Only openai table exists
    _, _, openai_identity = settings.resolved_embedding_query_identities
    fake_db_mod.vector_table_exists = (
        lambda table_name, project_id="default", embedding_version=None: embedding_version
        == openai_identity
    )
    monkeypatch.setitem(sys.modules, "infra.db", fake_db_mod)

    class FakeEmbedder:
        def encode_with_metadata(self, texts, input_type="document", acceptable_identities=None, forced_identity=None):
            assert input_type == "query"
            assert acceptable_identities == [openai_identity]
            return (
                [[0.8] * 1536],
                {
                    "identity": openai_identity,
                    "provider": "openai",
                    "model": "text-embedding-3-small",
                    "dimensions": 1536,
                },
                [
                    {"provider": "bge", "status": "error", "reason": "unavailable"},
                    {"provider": "openai", "status": "selected"},
                ],
            )

    monkeypatch.setattr("memory.embedder.get_embedder", lambda version=None: FakeEmbedder())

    route = encode_query_with_fallback("查詢文字", project_id="test-proj")
    assert route.version == openai_identity
    assert len(route.vector) == 1536
