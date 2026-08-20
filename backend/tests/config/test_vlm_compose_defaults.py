"""Regression tests for the local VLM compose defaults."""

from __future__ import annotations

from pathlib import Path


import pytest

pytestmark = pytest.mark.requires_repo_root

ROOT = Path(__file__).resolve().parents[3]


def test_vlm_compose_defaults_match_qwen3_fp8_runtime():
    compose = (ROOT / "docker-compose.yml").read_text(encoding="utf-8")

    assert "image: vllm/vllm-openai:v0.24.0" in compose
    assert "${VLM_MODEL:-Qwen/Qwen3-VL-4B-Instruct-FP8}" in compose
    assert "${VLM_GPU_MEMORY_UTILIZATION:-0.45}" in compose
    assert "- openvman-vlm" in compose
    assert "- \"1024\"" in compose
    assert "- \"1\"" in compose
    assert "- \"512\"" in compose


def test_vlm_healthcheck_uses_authenticated_models_endpoint():
    compose = (ROOT / "docker-compose.yml").read_text(encoding="utf-8")

    assert "- --disable-log-requests" not in compose
    assert 'exec vllm serve "$$@" --api-key "$${VLLM_API_KEY}"' in compose
    assert "VLLM_API_KEY=${GATEWAY_INTERNAL_TOKEN:-${VISION_LLM_API_KEY:-}}" in compose
    assert "VISION_LLM_API_KEY=${VISION_LLM_API_KEY:-${GATEWAY_INTERNAL_TOKEN:-}}" in compose
    assert "VLLM_API_KEY is required for the local VLM service" in compose
    assert "http://127.0.0.1:8000/v1/models" in compose
    assert "Authorization" in compose


def test_vlm_env_example_matches_qwen3_fp8_runtime():
    env_example = (ROOT / ".env.example").read_text(encoding="utf-8")

    assert "VLM_IMAGE=" not in env_example
    assert "VLM_SERVED_MODEL=" not in env_example
    assert "VLM_MAX_MODEL_LEN=" not in env_example
    assert "VLM_MAX_NUM_SEQS=" not in env_example
    assert "VLM_MAX_NUM_BATCHED_TOKENS=" not in env_example
    assert "# VLM_MODEL=Qwen/Qwen3-VL-4B-Instruct-FP8" in env_example
    assert "# VLM_GPU_MEMORY_UTILIZATION=0.45" in env_example
