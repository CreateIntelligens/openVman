"""ApiTool plugin — YAML registry + rate limiting + HTTP calls."""

from __future__ import annotations

import logging
import os
import re
import time
from collections import deque
from pathlib import Path
from typing import Any

import httpx

from app.config import get_tts_config

logger = logging.getLogger("gateway.plugin.api_tool")


def _resolve_env_vars(value: str) -> str:
    """Replace ${ENV_VAR} patterns with environment variable values."""
    def _replacer(match: re.Match) -> str:
        var_name = match.group(1)
        return os.environ.get(var_name, "")
    return re.sub(r"\$\{(\w+)}", _replacer, value)


class ApiToolPlugin:
    """Executes HTTP calls against a YAML-defined API registry with rate limiting."""

    id: str = "api_tool"

    def __init__(self) -> None:
        self._registry: dict[str, dict[str, Any]] = {}
        self._rate_windows: dict[str, deque[float]] = {}
        self._loaded = False

    def _load_registry(self) -> None:
        """Load API registry from YAML file."""
        if self._loaded:
            return

        import yaml

        cfg = get_tts_config()
        registry_path = Path(cfg.api_registry_path)

        if not registry_path.exists():
            logger.warning("api_registry not found: %s", registry_path)
            self._loaded = True
            return

        raw = registry_path.read_text(encoding="utf-8")
        data = yaml.safe_load(raw) or {}

        for api_id, api_def in data.get("apis", {}).items():
            # Resolve env vars in all string values
            resolved: dict[str, Any] = {}
            for k, v in api_def.items():
                resolved[k] = _resolve_env_vars(str(v)) if isinstance(v, str) else v
            self._registry[api_id] = resolved

        logger.info("api_registry loaded apis=%d", len(self._registry))
        self._loaded = True

    def _check_rate_limit(self, api_id: str, max_rpm: int) -> bool:
        """Sliding window rate limiter. Returns True if request is allowed."""
        now = time.monotonic()
        window = self._rate_windows.setdefault(api_id, deque())

        # Remove entries older than 60 seconds
        while window and window[0] < now - 60:
            window.popleft()

        if len(window) >= max_rpm:
            return False

        window.append(now)
        return True

    async def execute(self, params: dict[str, Any]) -> dict[str, Any]:
        """Execute an API call.

        params:
            api_id: str — which API from registry
            method: str — HTTP method override (default from registry)
            path: str — path to append to base URL
            body: dict — request body (optional)
            query: dict — query parameters (optional)
        """
        self._load_registry()

        api_id = params.get("api_id", "")
        if api_id not in self._registry:
            return {"error": f"unknown api_id: {api_id}", "available": list(self._registry.keys())}

        api_def = self._registry[api_id]
        max_rpm = api_def.get("rate_limit_rpm", 60)

        if not self._check_rate_limit(api_id, max_rpm):
            return {"error": "rate_limit_exceeded", "api_id": api_id}

        cfg = get_tts_config()
        timeout_sec = cfg.api_tool_timeout_ms / 1000.0

        base_url = api_def.get("base_url", "")
        path = params.get("path", api_def.get("default_path", ""))
        url = f"{base_url.rstrip('/')}/{path.lstrip('/')}" if path else base_url

        method = params.get("method", api_def.get("method", "GET")).upper()
        headers = self._build_headers(api_def)

        try:
            async with httpx.AsyncClient(timeout=timeout_sec) as client:
                response = await client.request(
                    method,
                    url,
                    headers=headers,
                    json=params.get("body") if method in ("POST", "PUT", "PATCH") else None,
                    params=params.get("query"),
                )
                return {
                    "status": response.status_code,
                    "body": response.text,
                    "api_id": api_id,
                }
        except Exception as exc:
            logger.error("api_tool_error api_id=%s err=%s", api_id, exc)
            return {"error": str(exc), "api_id": api_id}

    def _build_headers(self, api_def: dict[str, Any]) -> dict[str, str]:
        """Build auth headers based on API definition."""
        headers: dict[str, str] = {}
        auth_type = api_def.get("auth_type", "none")
        auth_value = api_def.get("auth_value", "")

        if auth_type == "bearer":
            headers["Authorization"] = f"Bearer {auth_value}"
        elif auth_type == "api_key":
            header_name = api_def.get("auth_header", "X-API-Key")
            headers[header_name] = auth_value
        elif auth_type == "basic":
            import base64
            encoded = base64.b64encode(auth_value.encode()).decode()
            headers["Authorization"] = f"Basic {encoded}"

        return headers

    async def health_check(self) -> bool:
        return True

    async def cleanup(self, session_id: str) -> None:
        pass
