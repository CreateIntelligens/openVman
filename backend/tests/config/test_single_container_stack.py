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


def _entrypoint_command(env: dict[str, str]) -> str:
    """Run the entrypoint with uvicorn stubbed out and return the uvicorn argv."""
    import os
    import shutil
    import subprocess
    import tempfile

    with tempfile.TemporaryDirectory() as tmp:
        stub = os.path.join(tmp, "uvicorn")
        with open(stub, "w", encoding="utf-8") as fh:
            fh.write('#!/bin/sh\necho "$@"\n')
        os.chmod(stub, 0o700)
        script = BACKEND_ROOT / "docker/start-backend-container.sh"
        # 腳本會 mkdir /app/logs；換成暫存目錄跑，不碰真實路徑。
        body = script.read_text(encoding="utf-8").replace("/app/logs", f"{tmp}/logs")
        body = body.replace("/tmp/vman-", f"{tmp}/vman-")
        runner = os.path.join(tmp, "start.sh")
        with open(runner, "w", encoding="utf-8") as fh:
            fh.write(body)
        result = subprocess.run(
            [shutil.which("bash") or "bash", runner],
            env={"PATH": f"{tmp}:{os.environ['PATH']}", **env},
            capture_output=True, text=True, check=True,
        )
    return result.stdout.strip().splitlines()[-1]


def test_dev_with_one_worker_reloads():
    cmd = _entrypoint_command({"ENV": "dev", "BACKEND_WORKERS": "1"})
    assert "--reload" in cmd
    assert "--workers" not in cmd


def test_dev_with_many_workers_runs_them_like_prod():
    cmd = _entrypoint_command({"ENV": "dev", "BACKEND_WORKERS": "4"})
    assert "--workers 4" in cmd
    assert "--reload" not in cmd


def test_prod_runs_configured_workers():
    cmd = _entrypoint_command({"ENV": "prod", "BACKEND_WORKERS": "4"})
    assert "--workers 4" in cmd
    assert "--reload" not in cmd
