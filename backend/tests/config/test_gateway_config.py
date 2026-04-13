"""Tests for gateway config extensions."""

from __future__ import annotations

import os
from unittest.mock import patch


def test_gateway_defaults():
    """Gateway config fields have correct defaults."""
    from app.config import TTSRouterConfig

    cfg = TTSRouterConfig()
    assert cfg.gateway_temp_dir == "/tmp/vman-gateway"
    assert cfg.gateway_temp_ttl_min == 30
    assert cfg.gateway_temp_dir_max_mb == 2048
    assert cfg.gateway_max_file_size_mb == 100
    assert cfg.media_processing_timeout_ms == 5000
    assert cfg.redis_url == "redis://redis:6379"
    assert cfg.queue_job_timeout_ms == 30000


def test_supported_mime_types_property():
    """supported_mime_types returns a frozenset parsed from CSV string."""
    from app.config import TTSRouterConfig

    cfg = TTSRouterConfig()
    mime_types = cfg.supported_mime_types
    assert isinstance(mime_types, frozenset)
    assert "image/jpeg" in mime_types
    assert "application/pdf" in mime_types
    assert "" not in mime_types


def test_gateway_env_override():
    """Gateway config fields can be overridden via environment variables."""
    env = {
        "GATEWAY_TEMP_DIR": "/custom/path",
        "GATEWAY_TEMP_TTL_MIN": "60",
        "GATEWAY_TEMP_DIR_MAX_MB": "512",
        "GATEWAY_MAX_FILE_SIZE_MB": "50",
        "REDIS_URL": "redis://custom:6380",
        "QUEUE_JOB_TIMEOUT_MS": "15000",
    }
    with patch.dict(os.environ, env, clear=False):
        from app.config import TTSRouterConfig

        cfg = TTSRouterConfig()
        assert cfg.gateway_temp_dir == "/custom/path"
        assert cfg.gateway_temp_ttl_min == 60
        assert cfg.gateway_temp_dir_max_mb == 512
        assert cfg.gateway_max_file_size_mb == 50
        assert cfg.redis_url == "redis://custom:6380"
        assert cfg.queue_job_timeout_ms == 15000


def test_custom_media_supported_types():
    """MEDIA_SUPPORTED_TYPES env var overrides default MIME list."""
    env = {"MEDIA_SUPPORTED_TYPES": "image/jpeg, application/pdf"}
    with patch.dict(os.environ, env, clear=False):
        from app.config import TTSRouterConfig

        cfg = TTSRouterConfig()
        assert cfg.supported_mime_types == frozenset({"image/jpeg", "application/pdf"})
