"""Centralized VLM route resolution, health probing, and pooled client management."""

from __future__ import annotations

from dataclasses import dataclass
import logging
from threading import Lock
from typing import Any
from urllib.parse import urlparse, urlunparse

import httpx
from openai import AsyncOpenAI

from app.config import get_tts_config

logger = logging.getLogger("gateway.vlm")

_client_cache: dict[tuple[str, str], AsyncOpenAI] = {}
_client_lock = Lock()


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


@dataclass(frozen=True, slots=True)
class VLMRoute:
    route: str  # "external" | "local" | "disabled"
    base_url: str
    api_key: str
    model: str
    is_enabled: bool


def resolve_vlm_route(cfg: Any = None) -> VLMRoute:
    if cfg is None:
        cfg = get_tts_config()

    raw_base_url = (cfg.vision_llm_base_url or "").strip()
    raw_api_key = (cfg.vision_llm_api_key or "").strip()
    raw_internal_key = (getattr(cfg, "gateway_internal_token", "") or "").strip()
    raw_model = (cfg.vision_llm_model or "").strip()

    if raw_base_url:
        is_local_container = any(
            host in raw_base_url
            for host in ("vlm:8000", "localhost:8000", "127.0.0.1:8000")
        )
        return VLMRoute(
            route="local" if is_local_container else "external",
            base_url=raw_base_url.rstrip("/"),
            api_key=(raw_internal_key or raw_api_key)
            if is_local_container
            else raw_api_key,
            model=raw_model or ("openvman-vlm" if is_local_container else "gpt-4o"),
            is_enabled=True,
        )

    # Local default when explicit model or key indicates local intent
    if raw_api_key or raw_model == "openvman-vlm":
        return VLMRoute(
            route="local",
            base_url="http://vlm:8000/v1",
            api_key=raw_internal_key or raw_api_key,
            model=raw_model or "openvman-vlm",
            is_enabled=True,
        )

    # Default to disabled if neither explicit URL nor local credentials are provided
    return VLMRoute(
        route="disabled",
        base_url="",
        api_key="",
        model=raw_model or "openvman-vlm",
        is_enabled=False,
    )


def get_vlm_client(cfg: Any = None) -> AsyncOpenAI | None:
    route = resolve_vlm_route(cfg)
    if not route.is_enabled:
        return None

    cache_key = (route.base_url, route.api_key)
    with _client_lock:
        if cache_key not in _client_cache:
            client_kwargs: dict[str, Any] = {"api_key": route.api_key or "local-vlm"}
            if route.base_url:
                client_kwargs["base_url"] = route.base_url
            _client_cache[cache_key] = AsyncOpenAI(**client_kwargs)
        return _client_cache[cache_key]


async def probe_vlm_health(
    client: httpx.AsyncClient | None = None,
    cfg: Any = None,
) -> dict[str, Any]:
    route = resolve_vlm_route(cfg)
    if not route.is_enabled:
        return {
            "status": "disabled",
            "route": "disabled",
            "model": route.model,
        }

    models_url = f"{route.base_url}/models"
    headers = {}
    if route.api_key:
        headers["Authorization"] = f"Bearer {route.api_key}"

    should_close = False
    if client is None:
        client = httpx.AsyncClient(timeout=3.0)
        should_close = True

    try:
        resp = await client.get(models_url, headers=headers)
        if resp.status_code == 200:
            data = resp.json()
            models_list = [m.get("id") for m in data.get("data", [])]
            # Verify expected model is served
            if route.model and models_list and route.model not in models_list:
                return {
                    "status": "incompatible",
                    "route": route.route,
                    "model": route.model,
                    "served_models": models_list,
                    "error": f"Expected model {route.model!r} not in served models {models_list!r}",
                    "url": _sanitize_url(route.base_url),
                }
            return {
                "status": "ready",
                "route": route.route,
                "model": route.model,
                "served_models": models_list,
                "url": _sanitize_url(route.base_url),
            }
        return {
            "status": "unreachable",
            "route": route.route,
            "error": f"HTTP {resp.status_code}",
            "model": route.model,
            "url": _sanitize_url(route.base_url),
        }
    except Exception as exc:
        return {
            "status": "unreachable",
            "route": route.route,
            "error": str(exc),
            "model": route.model,
            "url": _sanitize_url(route.base_url),
            "hint": "Ensure COMPOSE_PROFILES includes 'vlm' or set VISION_LLM_BASE_URL"
            if route.route == "local"
            else "",
        }
    finally:
        if should_close:
            await client.aclose()
