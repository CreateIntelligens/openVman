"""Regression tests for the backend container stack."""

from __future__ import annotations

from pathlib import Path

import yaml

import pytest

pytestmark = pytest.mark.requires_repo_root

REPO_ROOT = Path(__file__).resolve().parents[3]
BACKEND_ROOT = REPO_ROOT / "backend"


def _read_text(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def test_backend_env_example_uses_production_mode_by_default():
    env_example = _read_text(REPO_ROOT / ".env.example")
    dev_compose = _read_text(REPO_ROOT / "docker-compose.dev.yml")

    assert "ENV=prod" in env_example
    assert "COMPOSE_FILE=docker-compose.yml:docker-compose.dev.yml" in (
        env_example
    )
    assert "ENV=dev" in dev_compose


def test_root_compose_has_separate_redis_service():
    compose = yaml.safe_load(_read_text(REPO_ROOT / "docker-compose.yml"))
    services = compose["services"]
    assert "backend" in services
    assert "redis" in services


def test_backend_image_uses_slim_base():
    dockerfile = _read_text(BACKEND_ROOT / "Dockerfile")
    assert "python:3.11-slim" in dockerfile


def test_backend_entrypoint_starts_uvicorn():
    entrypoint = _read_text(BACKEND_ROOT / "docker/start-backend-container.sh")
    assert "uvicorn app.main:app" in entrypoint
