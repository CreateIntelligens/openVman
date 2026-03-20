"""Shared health payload helpers for backend routes."""

from __future__ import annotations

from app.gateway.temp_storage import QuotaStatus


def _temp_storage_payload(quota: QuotaStatus) -> dict[str, float | int | bool | str]:
    return {
        "status": "ok" if quota.ok else "error",
        "usage_mb": round(quota.usage_mb, 2),
        "limit_mb": quota.limit_mb,
        "ok": quota.ok,
    }


def build_backend_health_payload(
    *,
    service: str,
    redis_available: bool,
    quota: QuotaStatus,
) -> dict[str, object]:
    temp_storage = _temp_storage_payload(quota)
    dependencies = {
        "redis": {
            "status": "ok" if redis_available else "error",
            "connection": "connected" if redis_available else "disconnected",
        },
        "temp_storage": temp_storage,
    }
    return {
        "status": "ok" if redis_available and quota.ok else "degraded",
        "service": service,
        "redis": "connected" if redis_available else "disconnected",
        "temp_storage": {
            "usage_mb": temp_storage["usage_mb"],
            "limit_mb": temp_storage["limit_mb"],
            "ok": temp_storage["ok"],
        },
        "dependencies": dependencies,
    }
