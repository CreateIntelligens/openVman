"""Dynamic Gemini model discovery service."""

from __future__ import annotations

import logging
import re
import time
from threading import Lock
from typing import Any

from google import genai

logger = logging.getLogger("brain.core.model_discovery")

# Thread-safe cache
_cache_lock = Lock()
_models_cache: dict[str, tuple[list[str], float]] = {}  # api_key -> (sorted_models, expiry_time)


def _extract_version(name: str) -> float:
    """Extract float-like version number from model name (e.g. 1.5, 2.0, 3.1)."""
    match = re.search(r"\b\d+(?:\.\d+)?\b", name)
    if match:
        try:
            return float(match.group(0))
        except ValueError:
            pass
    return 0.0


def model_sort_key(model_name: str) -> tuple[int, float, str]:
    """Sort key for models.

    Pro優先 -> Flash優先 -> Flash-Lite -> 其他
    Within categories, higher versions have priority.
    """
    name = model_name.lower()

    if "pro" in name:
        category = 0
    elif "flash-lite" in name or "lite" in name:
        category = 2
    elif "flash" in name:
        category = 1
    else:
        category = 3

    version = _extract_version(name)
    # Lower number = higher priority for ascending sort. So category 0 (Pro) is first.
    # Higher version number = higher priority, so we use negative version.
    return (category, -version, name)


def discover_gemini_models_with_client(client: genai.Client, ttl: float = 600.0) -> list[str]:
    """Retrieve and cache all available generateContent models for a given Gemini Client."""
    # Extract API key if possible, otherwise use id(client)
    api_key = getattr(getattr(client, "_api_client", None), "api_key", None)
    if api_key and isinstance(api_key, str):
        cache_key = api_key
    else:
        cache_key = str(id(client))

    now = time.time()
    with _cache_lock:
        if cache_key in _models_cache:
            models, expiry = _models_cache[cache_key]
            if now < expiry:
                return models

    # Query the client
    raw_models = client.models.list()
    discovered: list[str] = []
    for m in raw_models:
        # Filter models supporting generateContent
        if m.supported_actions and "generateContent" in m.supported_actions:
            name = m.name
            # Remove models/ prefix
            if name.startswith("models/"):
                name = name[len("models/"):]
            discovered.append(name)

    # Sort the models
    discovered.sort(key=model_sort_key)

    with _cache_lock:
        _models_cache[cache_key] = (discovered, now + ttl)

    logger.info("Successfully discovered %d Gemini models, cached for %s seconds", len(discovered), ttl)
    return discovered
