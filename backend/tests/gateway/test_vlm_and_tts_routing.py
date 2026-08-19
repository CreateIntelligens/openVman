"""Behavior tests for centralized VLM and IndexTTS routing, health probes, and token redaction."""

from __future__ import annotations

import httpx
import pytest

from app.config import TTSRouterConfig
from app.gateway.vlm_client import (
    get_vlm_client,
    probe_vlm_health,
    resolve_vlm_route,
)
from app.health_payloads import probe_indextts_health


def test_vlm_external_selection():
    cfg = TTSRouterConfig(
        vision_llm_base_url="https://api.openai.com/v1",
        vision_llm_api_key="sk-external-12345",
        vision_llm_model="gpt-4o",
        gateway_internal_token="shared-internal-token",
    )
    route = resolve_vlm_route(cfg)
    assert route.route == "external"
    assert route.base_url == "https://api.openai.com/v1"
    assert route.api_key == "sk-external-12345"
    assert route.model == "gpt-4o"
    assert route.is_enabled is True


def test_vlm_local_selection():
    cfg = TTSRouterConfig(
        vision_llm_base_url="http://vlm:8000/v1",
        vision_llm_api_key="external-key",
        vision_llm_model="openvman-vlm",
        gateway_internal_token="shared-internal-token",
    )
    route = resolve_vlm_route(cfg)
    assert route.route == "local"
    assert route.base_url == "http://vlm:8000/v1"
    assert route.model == "openvman-vlm"
    assert route.api_key == "shared-internal-token"
    assert route.is_enabled is True


def test_vlm_disabled_when_unconfigured():
    cfg = TTSRouterConfig(
        vision_llm_base_url="",
        vision_llm_api_key="",
        vision_llm_model="",
    )
    route = resolve_vlm_route(cfg)
    assert route.route == "disabled"
    assert route.is_enabled is False


@pytest.mark.asyncio
async def test_vlm_health_probing_and_redaction(monkeypatch):
    secret_key = "sk-super-secret-key-999"

    async def mock_get(self, url, headers=None, **kwargs):
        req = httpx.Request("GET", url, headers=headers)
        if headers and headers.get("Authorization") == f"Bearer {secret_key}":
            return httpx.Response(
                200,
                json={"data": [{"id": "gpt-4o"}]},
                request=req,
            )
        return httpx.Response(401, json={"error": "Unauthorized"}, request=req)

    monkeypatch.setattr(httpx.AsyncClient, "get", mock_get)

    cfg = TTSRouterConfig(
        vision_llm_base_url="https://api.openai.com/v1?secret_query=123",
        vision_llm_api_key=secret_key,
        vision_llm_model="gpt-4o",
    )

    async with httpx.AsyncClient() as client:
        health = await probe_vlm_health(client=client, cfg=cfg)

    assert health["status"] == "ready"
    assert health["model"] == "gpt-4o"
    assert health["served_models"] == ["gpt-4o"]
    assert secret_key not in str(health)
    assert "secret_query" not in health["url"]


@pytest.mark.asyncio
async def test_vlm_health_incompatible_model(monkeypatch):
    async def mock_get(self, url, headers=None, **kwargs):
        req = httpx.Request("GET", url, headers=headers)
        return httpx.Response(
            200,
            json={"data": [{"id": "some-other-model-v2"}]},
            request=req,
        )

    monkeypatch.setattr(httpx.AsyncClient, "get", mock_get)

    cfg = TTSRouterConfig(
        vision_llm_base_url="http://vlm:8000/v1",
        vision_llm_model="openvman-vlm",
    )

    async with httpx.AsyncClient() as client:
        health = await probe_vlm_health(client=client, cfg=cfg)

    assert health["status"] == "incompatible"
    assert "Expected model" in health["error"]


@pytest.mark.asyncio
async def test_indextts_routing_and_health_probing(monkeypatch):
    observed_headers = []

    async def mock_get(self, url, headers=None, **kwargs):
        observed_headers.append(headers or {})
        req = httpx.Request("GET", url, headers=headers)
        if "ready" in url:
            return httpx.Response(
                200,
                json={"status": "ready", "model": "IndexTeam/IndexTTS-1.5", "revision": "1.0.0"},
                request=req,
            )
        return httpx.Response(200, json={"status": "healthy"}, request=req)

    monkeypatch.setattr(httpx.AsyncClient, "get", mock_get)

    # 1. Disabled IndexTTS
    cfg_disabled = TTSRouterConfig(tts_indextts_url="")
    async with httpx.AsyncClient() as client:
        h_dis = await probe_indextts_health(client, cfg_disabled)
    assert h_dis["status"] == "disabled"
    assert h_dis["route"] == "disabled"

    # 2. Local IndexTTS
    cfg_local = TTSRouterConfig(
        tts_indextts_url="http://index-tts-vllm:8011",
        gateway_internal_token="shared-token",
    )
    async with httpx.AsyncClient() as client:
        h_loc = await probe_indextts_health(client, cfg_local)
    assert h_loc["status"] == "ready"
    assert h_loc["route"] == "local"
    assert h_loc["model"] == "IndexTeam/IndexTTS-1.5"
    assert observed_headers[-1] == {"X-Internal-Token": "shared-token"}

    # 3. External IndexTTS with sanitized URL
    cfg_ext = TTSRouterConfig(tts_indextts_url="http://user:pass@shared-indextts:8011/v1?token=xyz")
    async with httpx.AsyncClient() as client:
        h_ext = await probe_indextts_health(client, cfg_ext)
    assert h_ext["status"] == "ready"
    assert h_ext["route"] == "external"
    assert "pass" not in h_ext["url"]
    assert "token=xyz" not in h_ext["url"]
