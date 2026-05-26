"""Tests for TTS router configuration loading."""

from __future__ import annotations

import os
from pathlib import Path

from app.config import TTSRouterConfig, get_tts_config

_ORIGINAL_ENV: dict[str, str] = {}
_ENV_KEYS_TO_CLEAR = (
    "ENV",
    "BACKEND_PORT",
    "TTS_INDEXTTS_URL",
    "TTS_AWS_ENABLED",
    "TTS_EDGE_SAMPLE_RATE",
    "MARKITDOWN_MAX_UPLOAD_BYTES",
    "DOCLING_SERVE_URL",
    "DOCLING_TIMEOUT_MS",
    "DOCLING_FALLBACK_TO_MARKITDOWN",
    "PDF_INSPECTOR_ENABLED",
    "PDF_INSPECTOR_MIN_CONFIDENCE",
    "PDF_INSPECTOR_MIN_MARKDOWN_CHARS",
    "PDF_REPAIR_ENABLED",
    "PDF_REPAIR_TIMEOUT_MS",
    "UVICORN_RELOAD",
)


def setup_function():
    get_tts_config.cache_clear()
    _ORIGINAL_ENV.clear()

    for key in _ENV_KEYS_TO_CLEAR:
        value = os.environ.pop(key, None)
        if value is not None:
            _ORIGINAL_ENV[key] = value


def teardown_function():
    get_tts_config.cache_clear()

    for key in _ENV_KEYS_TO_CLEAR:
        os.environ.pop(key, None)
    os.environ.update(_ORIGINAL_ENV)
    _ORIGINAL_ENV.clear()


def test_settings_can_load_from_env_file(tmp_path: Path):
    env_file = tmp_path / ".env"
    env_file.write_text(
        "\n".join(
            [
                "ENV=dev",
                "BACKEND_PORT=9999",
                "TTS_INDEXTTS_URL=http://mock-index:8001",
                "TTS_AWS_ENABLED=true",
                "TTS_EDGE_SAMPLE_RATE=16000",
                "MARKITDOWN_MAX_UPLOAD_BYTES=1234",
                "DOCLING_SERVE_URL=http://docling-serve:5001",
                "DOCLING_TIMEOUT_MS=9999",
                "DOCLING_FALLBACK_TO_MARKITDOWN=false",
                "PDF_INSPECTOR_ENABLED=false",
                "PDF_INSPECTOR_MIN_CONFIDENCE=0.9",
                "PDF_INSPECTOR_MIN_MARKDOWN_CHARS=25",
                "PDF_REPAIR_ENABLED=false",
                "PDF_REPAIR_TIMEOUT_MS=20000",
            ]
        ),
        encoding="utf-8",
    )

    config = TTSRouterConfig(_env_file=env_file)

    assert config.tts_indextts_url == "http://mock-index:8001"
    assert config.tts_aws_enabled is True
    assert config.edge_tts_sample_rate == 16000
    assert config.markitdown_max_upload_bytes == 1234
    assert config.docling_serve_url == "http://docling-serve:5001"
    assert config.docling_timeout_ms == 9999
    assert config.docling_fallback_to_markitdown is False
    assert config.pdf_inspector_enabled is False
    assert config.pdf_inspector_min_confidence == 0.9
    assert config.pdf_inspector_min_markdown_chars == 25
    assert config.pdf_repair_enabled is False
    assert config.pdf_repair_timeout_ms == 20000
    assert config.backend_port == 9999
    assert config.is_dev is True


def test_legacy_uvicorn_reload_env_no_longer_changes_mode(tmp_path: Path):
    env_file = tmp_path / ".env"
    env_file.write_text(
        "\n".join(
            [
                "ENV=prod",
                "UVICORN_RELOAD=true",
            ]
        ),
        encoding="utf-8",
    )

    config = TTSRouterConfig(_env_file=env_file)

    assert config.is_dev is False
