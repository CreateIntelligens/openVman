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

    def test_defaults_use_gemma_only(self):
        cfg = BrainSettings()

        assert cfg.resolved_embedding_active_version == "gemma"
        assert cfg.resolved_embedding_version_order == ["gemma"]

        backend = cfg.resolve_embedding_backend()
        assert backend.version == "gemma"
        assert backend.provider == "gemma"
        assert backend.model == "google/embeddinggemma-2"
        assert backend.dimensions == 768
        assert backend.api_key == cfg.embedding_service_token

    def test_active_version_is_prepended_once(self):
        cfg = BrainSettings(
            embedding_active_version="gemma",
            embedding_version_order="gemma, GEMMA",
        )

        assert cfg.resolved_embedding_version_order == ["gemma"]

    def test_backend_uses_the_gateway_token(self):
        cfg = BrainSettings(embedding_service_token="gateway-token")

        backend = cfg.resolve_embedding_backend("gemma")
        assert backend.provider == "gemma"
        assert backend.api_key == "gateway-token"

    def test_write_and_query_identities_are_canonical_and_explicit(self):
        cfg = BrainSettings()

        assert cfg.resolved_embedding_write_identity == (
            "gemma:google/embeddinggemma-2:768:float32:l2:document:"
            "914f7f89142e33e77833254d9c9b90c3cef7303b"
        )
        assert cfg.resolved_embedding_query_identities == [
            cfg.resolve_embedding_identity("gemma", input_semantics="query"),
        ]
        assert cfg.resolved_embedding_query_identities[0].split(":")[5] == "query"

    def test_explicit_write_identity_is_not_reinterpreted_by_provider_alias(self):
        identity = "gemma:google/embeddinggemma-2:768:float32:l2:document:rev-two"
        cfg = BrainSettings(embedding_write_identity=identity)

        assert cfg.resolved_embedding_write_identity == identity

    def test_identity_alias_override_replaces_the_gemma_identity(self):
        identity = "gemma:google/embeddinggemma-2:768:float32:l2:document:rev-two"
        cfg = BrainSettings(embedding_identity_aliases=f'{{"gemma": "{identity}"}}')

        assert cfg.resolved_embedding_write_identity == identity

    def test_removed_versions_are_rejected(self):
        for version in ("bge", "gemini", "openai", "voyage"):
            with pytest.raises(ValueError, match="embedding"):
                BrainSettings(embedding_active_version=version).resolve_embedding_backend()

    def test_unknown_embedding_version_raises(self):
        cfg = BrainSettings(
            embedding_active_version="mystery",
            embedding_version_order="mystery",
        )

        with pytest.raises(ValueError, match="embedding"):
            cfg.resolve_embedding_backend()
