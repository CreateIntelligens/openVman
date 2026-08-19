"""Shared health payload helpers for backend routes."""

from __future__ import annotations

import asyncio
import logging
import time
from typing import Any
from urllib.parse import urlparse, urlunparse

import httpx

from app.config import get_tts_config
from app.gateway.temp_storage import QuotaStatus

logger = logging.getLogger("backend")

_HEALTH_TIMEOUT_SECONDS = 3


def _sanitize_url(raw_url: str) -> str:
    if not raw_url:
        return ""
    try:
        parsed = urlparse(raw_url)
        netloc = parsed.netloc
        if "@" in netloc:
            auth, _, host = netloc.partition("@")
            user = auth.split(":")[0] if ":" in auth else auth
            netloc = f"{user}:***@{host}" if user else host
        return urlunparse((parsed.scheme, netloc, parsed.path, "", "", "")).rstrip("/")
    except Exception:
        return raw_url.split("?")[0]


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
    headers: dict[str, str] | None = None,
) -> dict[str, Any]:
    """Probe a downstream service health endpoint."""
    try:
        resp = await client.get(url, headers=headers or {}, timeout=_HEALTH_TIMEOUT_SECONDS)
        body = resp.json()
        status = body.get("status", "unknown")
        # Sanitize body if it has URL fields
        if "url" in body:
            body["url"] = _sanitize_url(str(body["url"]))
        return {"status": status, "http": resp.status_code, **body}
    except httpx.TimeoutException:
        return {"status": "unreachable", "error": "timeout"}
    except httpx.ConnectError:
        return {"status": "unreachable", "error": "connection_refused"}
    except Exception as exc:
        logger.warning("health probe %s failed: %s", name, exc)
        return {"status": "unreachable", "error": str(exc)}


async def probe_indextts_health(
    client: httpx.AsyncClient,
    cfg: Any = None,
) -> dict[str, Any]:
    if cfg is None:
        cfg = get_tts_config()

    tts_url = (cfg.tts_indextts_url or "").strip()
    if not tts_url:
        return {"status": "disabled", "route": "disabled"}

    is_local = "index-tts-vllm:8011" in tts_url or "localhost:8011" in tts_url or "127.0.0.1:8011" in tts_url
    route = "local" if is_local else "external"

    headers = {}
    if getattr(cfg, "gateway_internal_token", None):
        headers["Authorization"] = f"Bearer {cfg.gateway_internal_token}"

    ready_url = f"{tts_url.rstrip('/')}/health/ready"
    res = await _probe_service(client, "index-tts", ready_url, headers=headers)
    if res.get("status") in {"ready", "healthy"}:
        return {
            "status": "ready",
            "route": route,
            "model": res.get("model", "IndexTTS"),
            "revision": res.get("revision", "1.0.0"),
            "url": _sanitize_url(tts_url),
        }
    if res.get("status") == "unreachable":
        return {
            "status": "unreachable",
            "route": route,
            "error": res.get("error", "unreachable"),
            "url": _sanitize_url(tts_url),
        }
    return {
        "status": res.get("status", "unknown"),
        "route": route,
        "url": _sanitize_url(tts_url),
    }


async def _probe_downstream_services(
    client: httpx.AsyncClient,
) -> dict[str, dict[str, Any]]:
    """Probe all known downstream services in parallel."""
    from app.gateway.vlm_client import probe_vlm_health

    cfg = get_tts_config()

    targets: dict[str, str] = {
        "brain": f"{cfg.brain_url}/brain/health/ready",
    }
    if cfg.docling_serve_url:
        targets["docling-serve"] = f"{cfg.docling_serve_url.rstrip('/')}/health"

    results = await asyncio.gather(
        *(
            _probe_service(client, name, url)
            for name, url in targets.items()
        ),
    )
    probes = dict(zip(targets.keys(), results))

    vlm_probe = await probe_vlm_health(client=client, cfg=cfg)
    probes["vlm"] = vlm_probe

    indextts_probe = await probe_indextts_health(client, cfg)
    probes["index-tts"] = indextts_probe

    return probes


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
