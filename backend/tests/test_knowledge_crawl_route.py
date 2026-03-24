"""Tests for POST /api/knowledge/crawl."""

from __future__ import annotations

import os
import types
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi.testclient import TestClient


def _mock_cfg():
    return types.SimpleNamespace(brain_url="http://brain:8100", crawler_timeout_ms=5000)


def _mock_response(payload: dict):
    response = MagicMock()
    response.raise_for_status = MagicMock()
    response.json.return_value = payload
    return response


@pytest.fixture()
def client():
    env = {"BRAIN_URL": "http://brain:8100"}
    with patch.dict(os.environ, env, clear=False):
        from app.config import get_tts_config

        get_tts_config.cache_clear()
        from app.main import app

        with TestClient(app, raise_server_exceptions=False) as c:
            yield c


def test_crawl_route_syncs_web_metadata(client: TestClient):
    mock_client = MagicMock()
    mock_client.post = AsyncMock(
        return_value=_mock_response(
            {
                "status": "ok",
                "files": [
                    {
                        "path": "knowledge/ingested/example_com_article.md",
                        "size": 123,
                    }
                ],
            }
        )
    )
    mock_client.patch = AsyncMock(
        return_value=_mock_response(
            {
                "status": "ok",
                "path": "knowledge/ingested/example_com_article.md",
                "source_type": "web",
                "source_url": "https://example.com/article",
                "enabled": True,
            }
        )
    )

    with (
        patch(
            "app.gateway.routes.fetch_page",
            new_callable=AsyncMock,
            return_value=types.SimpleNamespace(
                title="Example Article",
                source_url="https://example.com/article",
                content="Hello world",
            ),
        ),
        patch("app.gateway.routes._get_brain_client", return_value=mock_client),
        patch("app.gateway.routes.get_tts_config", return_value=_mock_cfg()),
    ):
        response = client.post(
            "/api/knowledge/crawl",
            json={"url": "https://example.com/article", "project_id": "default"},
        )

    assert response.status_code == 200
    assert response.json()["path"] == "knowledge/ingested/example_com_article.md"
    mock_client.post.assert_awaited_once()
    mock_client.patch.assert_awaited_once()
    patch_call = mock_client.patch.await_args
    assert patch_call.args[0] == "http://brain:8100/brain/knowledge/document/meta"
    patch_kwargs = patch_call.kwargs
    assert patch_kwargs["json"] == {
        "path": "knowledge/ingested/example_com_article.md",
        "project_id": "default",
        "source_type": "web",
        "source_url": "https://example.com/article",
        "enabled": True,
    }
