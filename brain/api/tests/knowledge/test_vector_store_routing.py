"""Tests for active embedding version table routing."""

from __future__ import annotations

import importlib
import sys
import types
from pathlib import Path

API_ROOT = Path(__file__).resolve().parents[1]
if str(API_ROOT) not in sys.path:
    sys.path.insert(0, str(API_ROOT))


def _load_db(monkeypatch, *, active_version: str):
    bge_identity = "bge:BAAI/bge-m3:1024:float32:l2:document:rev-one"
    gemini_identity = (
        "gemini:gemini-embedding-001:768:float32:l2:document:provider-managed"
    )

    def identity_with_semantics(identity, semantics):
        parts = identity.split(":")
        parts[5] = semantics
        return ":".join(parts)

    fake_config_mod = types.ModuleType("config")
    fake_config_mod.get_settings = lambda: types.SimpleNamespace(
        resolved_embedding_active_version=active_version,
        resolved_embedding_write_identity=(
            bge_identity if active_version == "bge" else gemini_identity
        ),
        resolved_embedding_identity_aliases={
            "bge": bge_identity,
            "gemini": gemini_identity,
        },
        resolved_embedding_compatible_legacy_identities={
            "bge:BAAI/bge-m3:1024:float32:l2:document:default"
        },
        _identity_with_semantics=identity_with_semantics,
    )
    monkeypatch.setitem(sys.modules, "config", fake_config_mod)

    fake_embedder_mod = types.ModuleType("memory.embedder")
    fake_embedder_mod.encode_text = lambda text, embedding_version=None: [0.1]
    monkeypatch.setitem(sys.modules, "memory.embedder", fake_embedder_mod)

    sys.modules.pop("infra.db", None)
    return importlib.import_module("infra.db")


class TestVectorTableNaming:
    def test_bge_uses_legacy_table_names(self, monkeypatch):
        db = _load_db(monkeypatch, active_version="bge")

        assert db.resolve_vector_table_name("knowledge") == "knowledge"
        assert db.resolve_vector_table_name("memories") == "memories"

    def test_non_bge_versions_use_namespaced_tables(self, monkeypatch):
        db = _load_db(monkeypatch, active_version="gemini")

        assert db.resolve_vector_table_name("knowledge") == "knowledge__gemini"
        assert db.resolve_vector_table_name("memories") == "memories__gemini"

    def test_known_query_identity_routes_to_its_document_table(self, monkeypatch):
        db = _load_db(monkeypatch, active_version="bge")
        query_identity = (
            "bge:BAAI/bge-m3:1024:float32:l2:query:rev-one"
        )

        assert db.resolve_vector_table_name("knowledge", query_identity) == "knowledge"

    def test_unknown_revision_gets_an_isolated_table(self, monkeypatch):
        db = _load_db(monkeypatch, active_version="bge")
        new_identity = (
            "bge:BAAI/bge-m3:1024:float32:l2:document:rev-two"
        )

        table_name = db.resolve_vector_table_name("knowledge", new_identity)
        assert table_name.startswith("knowledge__emb_")
        assert table_name != "knowledge"

    def test_parity_verified_legacy_identity_keeps_the_legacy_table(self, monkeypatch):
        db = _load_db(monkeypatch, active_version="bge")
        legacy_identity = (
            "bge:BAAI/bge-m3:1024:float32:l2:document:default"
        )

        assert db.resolve_vector_table_name(
            "knowledge",
            legacy_identity,
        ) == "knowledge"
