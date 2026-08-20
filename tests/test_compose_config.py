"""Tests for direct Docker Compose GPU profile and consumer routing."""

from __future__ import annotations

import json
import os
from pathlib import Path
import subprocess


ROOT = Path(__file__).resolve().parents[1]


def compose_config(overrides: dict[str, str]) -> dict:
    env = os.environ.copy()
    env.update(overrides)
    result = subprocess.run(
        ["docker", "compose", "config", "--format", "json"],
        cwd=ROOT,
        env=env,
        check=True,
        capture_output=True,
        text=True,
    )
    return json.loads(result.stdout)


def test_direct_compose_routes_local_gpu_services():
    config = compose_config(
        {
            "COMPOSE_PROFILES": "embedding,vlm",
            "EMBEDDING_SERVICE_URL": "",
            "GATEWAY_INTERNAL_TOKEN": "test-internal-token",
            "TTS_INDEXTTS_URL": "",
            "VISION_LLM_API_KEY": "",
            "VISION_LLM_BASE_URL": "http://vlm:8000/v1",
        },
    )
    services = config["services"]

    assert "embedding" in services
    assert "vlm" in services
    assert "index-tts-vllm" not in services
    assert services["api"]["environment"]["EMBEDDING_SERVICE_URL"] == (
        "http://embedding:8009"
    )
    assert services["backend"]["environment"]["VISION_LLM_API_KEY"] == (
        "test-internal-token"
    )
    assert services["vlm"]["environment"]["VLLM_API_KEY"] == (
        "test-internal-token"
    )


def test_direct_compose_routes_external_gpu_services_without_local_profiles():
    config = compose_config(
        {
            "COMPOSE_PROFILES": "",
            "EMBEDDING_SERVICE_URL": "http://shared-gpu:8009",
            "GATEWAY_INTERNAL_TOKEN": "test-internal-token",
            "TTS_INDEXTTS_URL": "http://shared-gpu:8011",
            "VISION_LLM_API_KEY": "external-vlm-token",
            "VISION_LLM_BASE_URL": "http://shared-gpu:8000/v1",
        },
    )
    services = config["services"]

    assert "embedding" not in services
    assert "vlm" not in services
    assert "index-tts-vllm" not in services
    assert services["api"]["environment"]["EMBEDDING_SERVICE_URL"] == (
        "http://shared-gpu:8009"
    )
    assert services["backend"]["environment"]["TTS_INDEXTTS_URL"] == (
        "http://shared-gpu:8011"
    )
    assert services["backend"]["environment"]["VISION_LLM_API_KEY"] == (
        "external-vlm-token"
    )
