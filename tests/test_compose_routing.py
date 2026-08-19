"""Tests for Compose launcher profile resolution, URL injection, and docker compose config matrix."""

from __future__ import annotations

import os
from pathlib import Path
import subprocess
import sys

import pytest

_PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

from scripts.compose_launcher import resolve_routing, sanitize_url


def test_routing_fully_local():
    env = {"COMPOSE_PROFILES": ""}
    routing = resolve_routing(env)

    assert "embedding" in routing.final_profiles
    assert "Local" in routing.embedding_mode
    assert routing.injected_env.get("EMBEDDING_SERVICE_URL") == "http://embedding:8009"
    assert "Disabled" in routing.vlm_mode
    assert "Disabled" in routing.indextts_mode


def test_routing_fully_external():
    env = {
        "EMBEDDING_SERVICE_URL": "http://shared-gpu:8009",
        "VISION_LLM_BASE_URL": "http://shared-gpu:8000/v1",
        "TTS_INDEXTTS_URL": "http://shared-gpu:8011",
        "COMPOSE_PROFILES": "",
    }
    routing = resolve_routing(env)

    assert "embedding" not in routing.final_profiles
    assert "vlm" not in routing.final_profiles
    assert "indextts" not in routing.final_profiles
    assert "External" in routing.embedding_mode
    assert "External" in routing.vlm_mode
    assert "External" in routing.indextts_mode
    assert routing.final_profiles == []


def test_routing_profile_injects_consumer_urls():
    # When user enables 'vlm' and 'indextts' profiles, launcher must inject local consumer URLs
    env = {
        "COMPOSE_PROFILES": "vlm,indextts",
    }
    routing = resolve_routing(env)

    assert "embedding" in routing.final_profiles
    assert "vlm" in routing.final_profiles
    assert "indextts" in routing.final_profiles
    assert routing.injected_env.get("VISION_LLM_BASE_URL") == "http://vlm:8000/v1"
    assert routing.injected_env.get("VISION_LLM_MODEL") == "openvman-vlm"
    assert routing.injected_env.get("TTS_INDEXTTS_URL") == "http://index-tts-vllm:8011"


def test_sanitize_url_strips_query_and_credentials():
    url_with_secret = "http://user:secret123@shared-gpu:8009/embed?token=my-secret-token"
    sanitized = sanitize_url(url_with_secret)
    assert "secret123" not in sanitized
    assert "my-secret-token" not in sanitized
    assert "http://user:***@shared-gpu:8009/embed" == sanitized


def test_routing_warns_on_redundant_url_and_profile():
    env = {
        "EMBEDDING_SERVICE_URL": "http://shared:8009",
        "COMPOSE_PROFILES": "embedding",
    }
    routing = resolve_routing(env)

    assert len(routing.warnings) >= 1
    assert "external URL takes precedence" in routing.warnings[0]


def test_docker_compose_config_matrix():
    """Verify that docker compose config succeeds with resolved profiles and injected env."""
    root = Path(__file__).resolve().parents[1]
    compose_file = root / "docker-compose.yml"
    if not compose_file.is_file():
        pytest.skip("docker-compose.yml not found")

    matrix = [
        {"COMPOSE_PROFILES": ""},
        {"COMPOSE_PROFILES": "vlm"},
        {"COMPOSE_PROFILES": "embedding,vlm,indextts"},
        {"EMBEDDING_SERVICE_URL": "http://external:8009", "COMPOSE_PROFILES": ""},
    ]

    for test_env in matrix:
        routing = resolve_routing(test_env)
        exec_env = os.environ.copy()
        exec_env["COMPOSE_PROFILES"] = ",".join(routing.final_profiles)
        exec_env.update(routing.injected_env)

        proc = subprocess.run(
            ["docker", "compose", "config", "--quiet"],
            cwd=str(root),
            env=exec_env,
            capture_output=True,
            text=True,
        )
        assert proc.returncode == 0, f"docker compose config failed for env {test_env}: {proc.stderr}"
