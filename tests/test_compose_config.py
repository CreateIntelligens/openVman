"""Tests for direct Docker Compose GPU profile and consumer routing."""

from __future__ import annotations

import json
import os
from pathlib import Path
import subprocess


ROOT = Path(__file__).resolve().parents[1]


def compose_config(
    overrides: dict[str, str],
    compose_files: tuple[str, ...] = (),
) -> dict:
    env = os.environ.copy()
    env.update(overrides)
    command = ["docker", "compose"]
    for compose_file in compose_files:
        command.extend(["-f", compose_file])
    command.extend(["config", "--format", "json"])
    result = subprocess.run(
        command,
        cwd=ROOT,
        env=env,
        check=True,
        capture_output=True,
        text=True,
    )
    return json.loads(result.stdout)


def volume_targets(service: dict) -> set[str]:
    return {volume["target"] for volume in service.get("volumes") or []}


def test_default_compose_uses_public_images_and_starts_watchtower():
    config = compose_config(
        {
            "COMPOSE_PROFILES": "",
            "DOCKERHUB_USERNAME": "",
            "ENV": "prod",
        },
    )
    services = config["services"]

    assert services["backend"]["image"] == (
        "tbdavid2019/openvman-backend:latest"
    )
    assert services["admin"]["image"] == (
        "tbdavid2019/openvman-admin:latest"
    )
    assert services["admin"]["build"]["target"] == "runner"
    assert "watchtower" in services
    assert services["watchtower"]["command"] == [
        "--api-version",
        "1.44",
        "--label-enable",
        "--interval",
        "300",
        "--cleanup",
    ]
    assert "/app/app" not in volume_targets(services["backend"])
    assert "/app" not in volume_targets(services["api"])
    assert "/app" not in volume_targets(services["avatar"])
    assert "/app" not in volume_targets(services["admin"])


def test_dev_compose_restores_worktree_mounts_and_disables_watchtower():
    config = compose_config(
        {
            "COMPOSE_PROFILES": "embedding",
            "DOCKERHUB_USERNAME": "",
            "ENV": "prod",
            "PORT": "18786",
            "HTTPS_PORT": "18787",
        },
        ("docker-compose.yml", "docker-compose.dev.yml"),
    )
    services = config["services"]

    assert "watchtower" not in services
    assert services["admin"].get("image") is None
    assert services["admin"]["build"]["target"] == "dev"
    assert services["backend"]["environment"]["ENV"] == "dev"
    assert services["api"]["environment"]["ENV"] == "dev"
    assert services["gateway-worker"]["environment"]["ENV"] == "dev"
    assert "/app/app" in volume_targets(services["backend"])
    assert "/app" in volume_targets(services["api"])
    assert "/app" in volume_targets(services["avatar"])
    assert "/app/node_modules" in volume_targets(services["avatar"])
    assert "/app" in volume_targets(services["admin"])
    assert "/app/node_modules" in volume_targets(services["admin"])
    assert "/etc/nginx/http.d" in volume_targets(services["admin"])
    published_ports = {
        port["target"]: port["published"]
        for port in services["admin"]["ports"]
    }
    assert published_ports == {80: "18786", 443: "18787"}
    for service_name in (
        "admin",
        "api",
        "avatar",
        "backend",
        "embedding",
        "gateway-worker",
    ):
        assert services[service_name]["labels"][
            "com.centurylinklabs.watchtower.enable"
        ] == "false"


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
