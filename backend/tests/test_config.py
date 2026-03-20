"""Tests for TTS router configuration loading."""

from __future__ import annotations

from pathlib import Path

from app.config import TTSRouterConfig, get_tts_config


def setup_function():
    get_tts_config.cache_clear()


def teardown_function():
    get_tts_config.cache_clear()


def test_settings_can_load_from_env_file(tmp_path: Path):
    env_file = tmp_path / ".env"
    env_file.write_text(
        "\n".join(
            [
                "ENV=dev",
                "BACKEND_PORT=9999",
                "TTS_INDEX_URL=http://mock-index:8001",
                "TTS_AWS_ENABLED=true",
                "TTS_EDGE_SAMPLE_RATE=16000",
                "MARKITDOWN_MAX_UPLOAD_BYTES=1234",
            ]
        ),
        encoding="utf-8",
    )

    config = TTSRouterConfig(_env_file=env_file)

    assert config.tts_index_url == "http://mock-index:8001"
    assert config.tts_aws_enabled is True
    assert config.edge_tts_sample_rate == 16000
    assert config.markitdown_max_upload_bytes == 1234
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
