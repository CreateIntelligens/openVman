"""Tests for embedding version/provider configuration."""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

API_ROOT = Path(__file__).resolve().parents[1]
if str(API_ROOT) not in sys.path:
    sys.path.insert(0, str(API_ROOT))

from config import BrainSettings


class TestEmbeddingSettings:
    def test_session_ttl_defaults_to_30_days(self):
        cfg = BrainSettings()

        assert cfg.max_session_ttl_minutes == 30 * 24 * 60

    def test_session_db_fallback_defaults_to_default_project_path(self):
        cfg = BrainSettings()

        assert cfg.session_db_resolved_path.endswith("/data/projects/default/sessions.db")

    def test_defaults_prefer_bge_chain(self):
        cfg = BrainSettings()

        assert cfg.resolved_embedding_active_version == "bge"
        assert cfg.resolved_embedding_version_order == [
            "bge",
            "gemini",
            "openai",
            "voyage",
        ]

        backend = cfg.resolve_embedding_backend()
        assert backend.version == "bge"
        assert backend.provider == "bge"
        assert backend.model == "BAAI/bge-m3"
        assert backend.api_key == cfg.embedding_service_token

    def test_active_version_is_prepended_once(self):
        cfg = BrainSettings(
            embedding_active_version="openai",
            embedding_version_order="gemini, openai, voyage",
        )

        assert cfg.resolved_embedding_version_order == [
            "openai",
            "gemini",
            "voyage",
        ]

    def test_provider_models_and_keys_resolve(self):
        cfg = BrainSettings(
            embedding_service_token="gateway-token",
            gemini_api_key="gk",
            openai_api_key="ok",
            voyage_api_key="vk",
            embedding_gemini_model="gemini-embedding-001",
            embedding_openai_model="text-embedding-3-small",
            embedding_voyage_model="voyage-3-large",
        )

        gemini = cfg.resolve_embedding_backend("gemini")
        assert gemini.provider == "gemini"
        assert gemini.model == "gemini-embedding-001"
        assert gemini.api_key == "gateway-token"

        openai = cfg.resolve_embedding_backend("openai")
        assert openai.provider == "openai"
        assert openai.model == "text-embedding-3-small"
        assert openai.api_key == "gateway-token"

        voyage = cfg.resolve_embedding_backend("voyage")
        assert voyage.provider == "voyage"
        assert voyage.model == "voyage-3-large"
        assert voyage.api_key == "gateway-token"

    def test_write_and_query_identities_are_canonical_and_explicit(self):
        cfg = BrainSettings(
            embedding_active_version="bge",
            embedding_version_order="bge,gemini",
        )

        assert cfg.resolved_embedding_write_identity.endswith(
            ":document:5617a9f61b028005a4858fdac845db406aefb181"
        )
        assert cfg.resolved_embedding_query_identities == [
            cfg.resolve_embedding_identity("bge", input_semantics="query"),
            cfg.resolve_embedding_identity("gemini", input_semantics="query"),
        ]

    def test_explicit_write_identity_is_not_reinterpreted_by_provider_alias(self):
        identity = "bge:BAAI/bge-m3:1024:float32:l2:document:rev-two"
        cfg = BrainSettings(embedding_write_identity=identity)

        assert cfg.resolved_embedding_write_identity == identity

    def test_pinned_bge_explicitly_accepts_the_parity_verified_legacy_identity(self):
        cfg = BrainSettings()

        assert cfg.resolved_embedding_compatible_legacy_identities == {
            "bge:BAAI/bge-m3:1024:float32:l2:document:default"
        }

    def test_unknown_embedding_version_raises(self):
        cfg = BrainSettings(
            embedding_active_version="mystery",
            embedding_version_order="mystery",
        )

        with pytest.raises(ValueError, match="embedding"):
            cfg.resolve_embedding_backend()
