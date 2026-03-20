"""Regression tests for the single-container backend stack."""

from __future__ import annotations

from pathlib import Path

import yaml

REPO_ROOT = Path(__file__).resolve().parents[2]
BACKEND_ROOT = REPO_ROOT / "backend"


def _read_text(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def test_backend_env_example_prefers_local_index_tts_and_redis():
    env_example = _read_text(BACKEND_ROOT / ".env.example")

    assert "TTS_INDEX_URL=http://127.0.0.1:8011" in env_example
    assert "REDIS_URL=redis://127.0.0.1:6379" in env_example


def test_root_compose_uses_single_backend_container():
    compose = yaml.safe_load(_read_text(REPO_ROOT / "docker-compose.yml"))

    services = compose["services"]
    assert "backend" in services
    assert "redis" not in services

    backend = services["backend"]
    assert "depends_on" not in backend
    assert "./backend/index-tts-vllm:/app/index-tts-vllm" in backend["volumes"]
    assert "./backend/logs:/app/logs" in backend["volumes"]

    devices = backend["deploy"]["resources"]["reservations"]["devices"]
    assert devices[0]["capabilities"] == ["gpu"]


def test_backend_compose_uses_env_file_instead_of_inline_defaults():
    compose = yaml.safe_load(_read_text(BACKEND_ROOT / "docker-compose.yml"))

    backend = compose["services"]["backend"]
    assert backend["env_file"] == ["./.env"]
    assert "environment" not in backend


def test_backend_image_starts_local_redis_and_index_tts():
    dockerfile = _read_text(BACKEND_ROOT / "Dockerfile")
    entrypoint = _read_text(BACKEND_ROOT / "docker/start-backend-container.sh")

    assert "FROM vllm/vllm-openai:v0.9.0" in dockerfile
    assert "redis-server" in dockerfile
    assert "COPY docker /app/docker" in dockerfile

    assert "redis-server" in entrypoint
    assert "/app/index-tts-vllm/entrypoint.sh" in entrypoint
    assert "uvicorn app.main:app" in entrypoint
