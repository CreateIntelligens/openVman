"""Shared resources must close when a running Backend exits with an error."""

import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

from fastapi import FastAPI
import pytest

from app import lifecycle


@pytest.mark.asyncio
@pytest.mark.parametrize("a2a_enabled", [False, True])
async def test_lifespan_closes_resources_after_application_failure(
    monkeypatch, a2a_enabled,
):
    app = FastAPI()
    app.state.openapi_builder = SimpleNamespace(build=AsyncMock())
    runtime = object()
    start_gateway = AsyncMock()
    stop_gateway = AsyncMock()
    sync_asr = Mock()
    sync_voices = AsyncMock()
    close_admin = AsyncMock()
    daemon = SimpleNamespace(start=Mock(), stop=AsyncMock())
    monkeypatch.setattr(lifecycle, "get_auth_runtime", lambda: runtime)
    cfg = SimpleNamespace(
        a2a_enabled=a2a_enabled, edge_tts_enabled=True, edge_tts_probe_interval_seconds=60,
    )
    monkeypatch.setattr(lifecycle, "get_tts_config", lambda: cfg)
    probe_cancelled = asyncio.Event()

    async def probe_loop(interval):
        try:
            await asyncio.Event().wait()
        except asyncio.CancelledError:
            probe_cancelled.set()
            raise

    monkeypatch.setattr(lifecycle, "run_edge_tts_probe_loop", probe_loop)
    monkeypatch.setattr(lifecycle, "_startup_gateway_resources", start_gateway)
    monkeypatch.setattr(lifecycle, "_shutdown_gateway_resources", stop_gateway)
    monkeypatch.setattr(lifecycle, "get_a2a_bridge_daemon", lambda: daemon)
    monkeypatch.setattr(lifecycle, "sync_asr_engines", sync_asr)
    monkeypatch.setattr(lifecycle, "sync_system_resources", sync_voices)
    monkeypatch.setattr(lifecycle.admin_routes, "close_http", close_admin)
    clients = []
    for name in (
        "_brain_proxy_http", "_internal_http", "_forward_http", "_crawl_http",
        "_health_http", "_vision_http", "_asr_http", "_voice_catalog_http",
    ):
        client = SimpleNamespace(close=AsyncMock())
        clients.append(client)
        monkeypatch.setattr(lifecycle, name, client)

    with pytest.raises(RuntimeError, match="application failed"):
        async with lifecycle.lifespan(app):
            start_gateway.assert_awaited_once_with()
            app.state.openapi_builder.build.assert_awaited_once_with()
            sync_asr.assert_called_once_with(runtime)
            sync_voices.assert_awaited_once_with(runtime, cfg)
            await asyncio.sleep(0)  # 讓 Edge 偵測真的開始跑
            raise RuntimeError("application failed")

    stop_gateway.assert_awaited_once_with()
    await asyncio.sleep(0)
    # Edge 定時偵測要跟著關掉，不能在 backend 停止後還在背景打微軟。
    assert probe_cancelled.is_set()
    close_admin.assert_awaited_once_with()
    for client in clients:
        client.close.assert_awaited_once_with()
    if a2a_enabled:
        daemon.start.assert_called_once_with()
        daemon.stop.assert_awaited_once_with()
    else:
        daemon.start.assert_not_called()
        daemon.stop.assert_not_awaited()


def test_unreadable_model_keys_are_logged_without_blocking_startup(caplog):
    runtime = SimpleNamespace(model_providers=SimpleNamespace(
        unreadable_credentials=lambda: ["gemini", "openai"],
    ))

    lifecycle._warn_unreadable_model_keys(runtime)
    lifecycle._warn_unreadable_model_keys(object())

    errors = [record for record in caplog.records if record.levelname == "ERROR"]
    assert len(errors) == 1 and "gemini, openai" in errors[0].getMessage()
