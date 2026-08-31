"""Compose and ARQ queue contract for gateway background jobs."""

from pathlib import Path

import pytest
import yaml

from app.gateway.queue import GATEWAY_QUEUE_NAME
from app.gateway.worker import WorkerSettings


ROOT = Path(__file__).parents[3]


def test_gateway_worker_uses_the_producer_queue():
    assert WorkerSettings.queue_name == GATEWAY_QUEUE_NAME
    assert WorkerSettings.redis_settings.host == "redis"


@pytest.mark.requires_repo_root
def test_compose_runs_gateway_worker_from_the_backend_image():
    compose = yaml.safe_load((ROOT / "docker-compose.yml").read_text("utf-8"))
    backend = compose["services"]["backend"]
    worker = compose["services"]["gateway-worker"]

    assert backend["image"] == worker["image"] == (
        "${DOCKERHUB_USERNAME:-tbdavid2019}/"
        "openvman-backend:${OPENVMAN_IMAGE_TAG:-latest}"
    )
    assert worker["entrypoint"] == [
        "arq",
        "app.gateway.worker.WorkerSettings",
    ]
    assert backend["environment"] == worker["environment"]
    assert "REDIS_URL=redis://redis:6379" in worker["environment"]
    assert "GATEWAY_TEMP_DIR=/data/gateway-temp" in worker["environment"]
    assert "GATEWAY_FORWARD_URL=http://backend:8200" in worker["environment"]
    assert (
        "MEDIA_PROCESSING_TIMEOUT_MS=${MEDIA_PROCESSING_TIMEOUT_MS:-60000}"
        in worker["environment"]
    )
    assert "ports" not in worker
