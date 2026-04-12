"""Shared health payload helpers for backend routes."""

from __future__ import annotations

import asyncio
import logging
import time
from typing import Any

import httpx

from app.config import get_tts_config
from app.gateway.temp_storage import QuotaStatus

logger = logging.getLogger("backend")

_HEALTH_TIMEOUT_SECONDS = 3


def _temp_storage_payload(quota: QuotaStatus) -> dict[str, float | int | bool | str]:
    return {
        "status": "ok" if quota.ok else "error",
        "usage_mb": round(quota.usage_mb, 2),
        "limit_mb": quota.limit_mb,
        "ok": quota.ok,
    }


async def _probe_service(
    client: httpx.AsyncClient,
    name: str,
    url: str,
) -> dict[str, Any]:
    """Probe a downstream service health endpoint."""
    try:
        resp = await client.get(url, timeout=_HEALTH_TIMEOUT_SECONDS)
        body = resp.json()
        status = body.get("status", "unknown")
        return {"status": status, "http": resp.status_code, **body}
    except httpx.TimeoutException:
        return {"status": "unreachable", "error": "timeout"}
    except httpx.ConnectError:
        return {"status": "unreachable", "error": "connection_refused"}
    except Exception as exc:
        logger.warning("health probe %s failed: %s", name, exc)
        return {"status": "unreachable", "error": str(exc)}


async def _probe_downstream_services(
    client: httpx.AsyncClient,
) -> dict[str, dict[str, Any]]:
    """Probe all known downstream services in parallel."""
    cfg = get_tts_config()

    targets: dict[str, str] = {
        "brain": f"{cfg.brain_url}/brain/health",
    }
    if cfg.docling_serve_url:
        targets["docling-serve"] = f"{cfg.docling_serve_url.rstrip('/')}/health"
    if cfg.tts_indextts_url:
        targets["index-tts"] = f"{cfg.tts_indextts_url}/health"

    results = await asyncio.gather(
        *(
            _probe_service(client, name, url)
            for name, url in targets.items()
        ),
    )
    return dict(zip(targets.keys(), results))


def _overall_status(
    *,
    redis_ok: bool,
    quota_ok: bool,
    downstream: dict[str, dict[str, Any]],
) -> str:
    if not redis_ok or not quota_ok:
        return "degraded"
    for svc in downstream.values():
        status = svc.get("status", "unknown")
        if status in ("unreachable", "error", "unhealthy"):
            return "degraded"
    return "ok"


async def build_backend_health_payload(
    *,
    service: str,
    redis_available: bool,
    quota: QuotaStatus,
    client: httpx.AsyncClient | None = None,
) -> dict[str, object]:
    temp_storage = _temp_storage_payload(quota)
    dependencies: dict[str, Any] = {
        "redis": {
            "status": "ok" if redis_available else "error",
            "connection": "connected" if redis_available else "disconnected",
        },
        "temp_storage": temp_storage,
    }

    if client is not None:
        downstream = await _probe_downstream_services(client)
        dependencies.update(downstream)
    else:
        downstream = {}

    status = _overall_status(
        redis_ok=redis_available,
        quota_ok=quota.ok,
        downstream=downstream,
    )

    return {
        "status": status,
        "service": service,
        "timestamp": time.time(),
        "dependencies": dependencies,
    }
