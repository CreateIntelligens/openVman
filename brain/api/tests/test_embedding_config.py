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
        assert backend.api_key == ""
        assert backend.multimodal is False

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
        assert gemini.api_key == "gk"

        openai = cfg.resolve_embedding_backend("openai")
        assert openai.provider == "openai"
        assert openai.model == "text-embedding-3-small"
        assert openai.api_key == "ok"

        voyage = cfg.resolve_embedding_backend("voyage")
        assert voyage.provider == "voyage"
        assert voyage.model == "voyage-3-large"
        assert voyage.api_key == "vk"

    def test_unknown_embedding_version_raises(self):
        cfg = BrainSettings(
            embedding_active_version="mystery",
            embedding_version_order="mystery",
        )

        with pytest.raises(ValueError, match="embedding"):
            cfg.resolve_embedding_backend()
