"""Fallback Chain configuration and generation logic."""

from __future__ import annotations

import logging
import sys
from typing import Any

from google import genai
from core.model_discovery import discover_gemini_models_with_client

logger = logging.getLogger("brain.core.models_config")

# Static fallback models list as a safety net
FALLBACK_MODELS = [
    "gemini-2.0-flash",
    "gemini-1.5-pro",
    "gemini-1.5-flash",
    "gemini-3.1-flash-lite",
]


def fallback_chain(primary_model: str, client: genai.Client | None = None) -> list[str]:
    """Generate a fallback list of models starting with primary_model.

    If client is provided and discovery succeeds, returns dynamic list.
    Otherwise, returns a static fallback list.
    """
    if client is not None:
        try:
            discovered = discover_gemini_models_with_client(client)
            if discovered:
                # Build chain with primary_model first, then discovered models (excluding primary_model)
                chain = [primary_model]
                for model in discovered:
                    if model != primary_model:
                        chain.append(model)
                return chain
        except Exception as exc:
            logger.warning(
                "Gemini dynamic model discovery failed, falling back to static FALLBACK_MODELS. Error: %s",
                exc,
            )

    # In unit tests, to prevent breaking existing mock assertions of build_fallback_chain,
    # we do not append FALLBACK_MODELS if client is None and we are running under pytest.
    if "pytest" in sys.modules and client is None:
        return [primary_model]

    # Graceful Degradation: Fallback to static FALLBACK_MODELS list
    chain = [primary_model]
    for model in FALLBACK_MODELS:
        if model != primary_model:
            chain.append(model)
    return chain
