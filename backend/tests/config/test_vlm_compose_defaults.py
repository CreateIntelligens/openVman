"""Regression tests for the local VLM compose defaults."""

from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[3]


def test_vlm_compose_defaults_match_qwen3_fp8_runtime():
    compose = (ROOT / "docker-compose.yml").read_text(encoding="utf-8")

    assert "${VLM_IMAGE:-vllm/vllm-openai:v0.11.0}" in compose
    assert "${VLM_MODEL:-Qwen/Qwen3-VL-4B-Instruct-FP8}" in compose
    assert "${VLM_GPU_MEMORY_UTILIZATION:-0.62}" in compose


def test_vlm_env_example_matches_qwen3_fp8_runtime():
    env_example = (ROOT / ".env.example").read_text(encoding="utf-8")

    assert "VLM_IMAGE=vllm/vllm-openai:v0.11.0" in env_example
    assert "VLM_MODEL=Qwen/Qwen3-VL-4B-Instruct-FP8" in env_example
    assert "VLM_GPU_MEMORY_UTILIZATION=0.62" in env_example
