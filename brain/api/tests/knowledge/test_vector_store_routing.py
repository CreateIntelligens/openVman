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
    fake_config_mod = types.ModuleType("config")
    fake_config_mod.get_settings = lambda: types.SimpleNamespace(
        resolved_embedding_active_version=active_version,
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
