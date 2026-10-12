"""視覺事件改問 Clef：請求格式、機率門檻、失敗退回 VLM、健康檢查。"""

from __future__ import annotations

import json
from unittest.mock import AsyncMock, patch

import httpx
import pytest

from app.config import TTSRouterConfig, get_tts_config
from app.gateway.plugins.camera_live import CameraLivePlugin
from app.gateway.plugins.vision_events import EVENT_DEFINITIONS
from app.gateway.vision_clef import detect_events_with_clef, probe_clef_health

_CLEF_URL = "https://clef.example.test/v1/systemone"


def _cfg(**overrides) -> TTSRouterConfig:
    return TTSRouterConfig(vision_clef_url=_CLEF_URL, **overrides)


def _client(handler) -> httpx.AsyncClient:
    return httpx.AsyncClient(transport=httpx.MockTransport(handler))


def _answers(**probabilities: float) -> dict:
    return {"answers": {k: {"type": "noul", "noul": v} for k, v in probabilities.items()}}


@pytest.mark.asyncio
async def test_sends_frame_as_data_url_and_one_yes_no_question_per_event():
    seen: list[dict] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append({"url": str(request.url), "auth": request.headers.get("authorization"),
                     "body": json.loads(request.content)})
        return httpx.Response(200, json=_answers(person=0.97, fire=0.01))

    async with _client(handler) as client:
        result = await detect_events_with_clef("QUJD", "image/jpeg", client=client, cfg=_cfg())

    assert result == {"person": True, "fire": False}
    body = seen[0]["body"]
    assert seen[0]["url"] == _CLEF_URL
    assert seen[0]["auth"] is None  # 自架端點不帶金鑰
    assert body["images"] == ["data:image/jpeg;base64,QUJD"]
    assert body["model"] == "clef-flash"
    assert body["questions"] == {
        e.key: {"type": "noul", "instructions": e.question} for e in EVENT_DEFINITIONS
    }


@pytest.mark.asyncio
async def test_threshold_is_half_and_key_is_sent_when_configured():
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.headers["authorization"] == "Bearer clef-key"
        return httpx.Response(200, json=_answers(person=0.5, fire=0.49))

    async with _client(handler) as client:
        result = await detect_events_with_clef(
            "QUJD", "image/jpeg", client=client, cfg=_cfg(clef_api_key="clef-key"),
        )
    assert result == {"person": True, "fire": False}


@pytest.mark.asyncio
@pytest.mark.parametrize("body", [{}, {"answers": {"person": {"noul": 0.9}}},
                                  _answers(person=True, fire=0.1)])
async def test_malformed_answers_raise_so_caller_can_fall_back(body):
    async with _client(lambda request: httpx.Response(200, json=body)) as client:
        with pytest.raises(ValueError):
            await detect_events_with_clef("QUJD", "image/jpeg", client=client, cfg=_cfg())


@pytest.mark.asyncio
async def test_camera_uses_clef_without_touching_vlm(monkeypatch):
    monkeypatch.setenv("VISION_CLEF_URL", _CLEF_URL)
    get_tts_config.cache_clear()
    plugin = CameraLivePlugin()
    with patch("app.gateway.vision_clef.detect_events_with_clef", new_callable=AsyncMock,
               return_value={"person": True, "fire": False}) as clef, \
            patch.object(plugin, "_complete_vision", new_callable=AsyncMock) as vlm:
        result = await plugin._detect_events("b64", "image/jpeg")
    assert result == {"person": True, "fire": False}
    clef.assert_awaited_once_with("b64", "image/jpeg")
    vlm.assert_not_awaited()


@pytest.mark.asyncio
async def test_camera_falls_back_to_vlm_when_clef_fails(monkeypatch):
    monkeypatch.setenv("VISION_CLEF_URL", _CLEF_URL)
    monkeypatch.setenv("VISION_LLM_BASE_URL", "https://vlm.example.test/v1")
    get_tts_config.cache_clear()
    plugin = CameraLivePlugin()
    with patch("app.gateway.vision_clef.detect_events_with_clef",
               side_effect=httpx.ReadTimeout("slow")), \
            patch.object(plugin, "_complete_vision", new_callable=AsyncMock,
                         return_value='{"person": false, "fire": true}') as vlm:
        result = await plugin._detect_events("b64", "image/jpeg")
    assert result == {"person": False, "fire": True}
    vlm.assert_awaited_once()


@pytest.mark.asyncio
async def test_camera_reports_nothing_when_clef_fails_and_vlm_is_off(monkeypatch):
    monkeypatch.setenv("VISION_CLEF_URL", _CLEF_URL)
    get_tts_config.cache_clear()
    plugin = CameraLivePlugin()
    with patch("app.gateway.vision_clef.detect_events_with_clef",
               side_effect=httpx.ConnectError("down")), \
            patch.object(plugin, "_complete_vision", new_callable=AsyncMock) as vlm:
        result = await plugin._detect_events("b64", "image/jpeg")
    assert result == {}
    vlm.assert_not_awaited()


@pytest.mark.asyncio
async def test_health_probes_origin_health_endpoint():
    seen: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(str(request.url))
        return httpx.Response(200, json={"status": "ok"})

    async with _client(handler) as client:
        health = await probe_clef_health(client=client, cfg=_cfg())
    assert seen == ["https://clef.example.test/health"]
    assert health == {"status": "ready", "route": "clef", "model": "clef-flash"}


@pytest.mark.asyncio
async def test_health_disabled_and_unreachable():
    async with _client(lambda request: httpx.Response(503)) as client:
        assert (await probe_clef_health(client=client, cfg=TTSRouterConfig(vision_clef_url="")))["status"] == "disabled"
        down = await probe_clef_health(client=client, cfg=_cfg())
    assert down["status"] == "unreachable"
    assert down["error"] == "HTTP 503"


@pytest.mark.parametrize(
    ("clef", "vlm", "expected"),
    [
        ({"status": "ready", "route": "clef", "model": "clef-flash"},
         {"status": "disabled", "route": "disabled", "model": "x"}, (True, "clef")),
        ({"status": "unreachable", "route": "clef", "model": "clef-flash"},
         {"status": "ready", "route": "external", "model": "gpt-4o"}, (True, "external")),
        ({"status": "unreachable", "route": "clef", "model": "clef-flash"},
         {"status": "disabled", "route": "disabled", "model": "x"}, (False, "clef")),
        ({"status": "disabled", "route": "disabled", "model": "clef-flash"},
         {"status": "disabled", "route": "disabled", "model": "x"}, (False, "disabled")),
    ],
)
def test_vision_health_prefers_clef_then_vlm(clef, vlm, expected):
    from fastapi import FastAPI
    from fastapi.testclient import TestClient

    from app.gateway.routes_vision import router

    app = FastAPI()
    app.include_router(router)
    with patch("app.gateway.routes_vision.probe_clef_health", new_callable=AsyncMock, return_value=clef), \
            patch("app.gateway.routes_vision.probe_vlm_health", new_callable=AsyncMock, return_value=vlm):
        data = TestClient(app).get("/api/v1/vision/health").json()
    assert (data["available"], data["route"]) == expected
