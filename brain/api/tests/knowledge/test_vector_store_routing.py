"""Tests for active embedding version table routing."""

from __future__ import annotations

import importlib
import sys
import types
from pathlib import Path

API_ROOT = Path(__file__).resolve().parents[1]
if str(API_ROOT) not in sys.path:
    sys.path.insert(0, str(API_ROOT))

GEMMA_IDENTITY = "gemma:google/embeddinggemma-2:768:float32:l2:document:rev-one"


def _load_db(monkeypatch):
    def identity_with_semantics(identity, semantics):
        parts = identity.split(":")
        parts[5] = semantics
        return ":".join(parts)

    fake_config_mod = types.ModuleType("config")
    fake_config_mod.get_settings = lambda: types.SimpleNamespace(
        resolved_embedding_active_version="gemma",
        resolved_embedding_write_identity=GEMMA_IDENTITY,
        resolved_embedding_identity_aliases={"gemma": GEMMA_IDENTITY},
        _identity_with_semantics=identity_with_semantics,
    )
    monkeypatch.setitem(sys.modules, "config", fake_config_mod)

    fake_embedder_mod = types.ModuleType("memory.embedder")
    fake_embedder_mod.encode_text = lambda text, embedding_version=None: [0.1]
    monkeypatch.setitem(sys.modules, "memory.embedder", fake_embedder_mod)

    sys.modules.pop("infra.db", None)
    return importlib.import_module("infra.db")


class TestVectorTableNaming:
    def test_active_version_uses_namespaced_tables(self, monkeypatch):
        db = _load_db(monkeypatch)

        assert db.resolve_vector_table_name("knowledge") == "knowledge__gemma"
        assert db.resolve_vector_table_name("memories") == "memories__gemma"

    def test_alias_routes_to_its_namespaced_table(self, monkeypatch):
        db = _load_db(monkeypatch)

        assert db.resolve_vector_table_name("knowledge", "gemma") == "knowledge__gemma"

    def test_known_query_identity_routes_to_its_document_table(self, monkeypatch):
        db = _load_db(monkeypatch)
        query_identity = GEMMA_IDENTITY.replace(":document:", ":query:")

        assert db.resolve_vector_table_name("knowledge", query_identity) == "knowledge__gemma"

    def test_unknown_revision_gets_an_isolated_table(self, monkeypatch):
        db = _load_db(monkeypatch)
        new_identity = "gemma:google/embeddinggemma-2:768:float32:l2:document:rev-two"

        table_name = db.resolve_vector_table_name("knowledge", new_identity)
        assert table_name.startswith("knowledge__emb_")
        assert len(table_name) == len("knowledge__emb_") + 16
        assert table_name == db.resolve_vector_table_name("knowledge", new_identity)

    def test_removed_bge_identity_no_longer_maps_to_the_unsuffixed_table(self, monkeypatch):
        db = _load_db(monkeypatch)
        legacy_identity = "bge:BAAI/bge-m3:1024:float32:l2:document:default"

        assert db.resolve_vector_table_name("knowledge", legacy_identity).startswith(
            "knowledge__emb_"
        )
