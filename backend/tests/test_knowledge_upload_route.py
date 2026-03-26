"""Tests for dedicated POST /api/knowledge/upload handling."""

from __future__ import annotations

import os
import types
from io import BytesIO
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi.responses import JSONResponse
from fastapi.testclient import TestClient

from app.gateway.ingestion import IngestionResult


def _mock_cfg():
    return types.SimpleNamespace(
        brain_url="http://brain:8100",
        markitdown_max_upload_bytes=10 * 1024 * 1024,
    )


def _mock_brain_response(payload: dict):
    response = MagicMock()
    response.status_code = 200
    response.headers = {"content-type": "application/json"}
    response.content = b'{"status":"ok"}'
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


def test_text_knowledge_upload_passthroughs_utf8_files_to_brain(client: TestClient):
    route_client = MagicMock()
    route_client.post = AsyncMock(
        return_value=_mock_brain_response(
            {
                "status": "ok",
                "files": [{"path": "knowledge/notes/example.md", "size": 12}],
            }
        )
    )

    with (
        patch("app.gateway.routes.get_tts_config", return_value=_mock_cfg()),
        patch("app.gateway.routes._brain_http.get", return_value=route_client),
        patch(
            "app.brain_proxy._proxy_to_brain",
            new_callable=AsyncMock,
            return_value=JSONResponse(content={"status": "proxied"}),
        ),
    ):
        response = client.post(
            "/api/knowledge/upload",
            data={"target_dir": "knowledge/notes", "project_id": "default"},
            files={"files": ("example.md", BytesIO(b"# hello\n"), "text/markdown")},
        )

    assert response.status_code == 200
    assert response.json() == {
        "status": "ok",
        "files": [{"path": "knowledge/notes/example.md", "size": 12}],
    }
    route_client.post.assert_awaited_once()
    post_call = route_client.post.await_args
    assert post_call.args[0] == "http://brain:8100/brain/knowledge/upload"
    assert post_call.kwargs["data"] == {"target_dir": "knowledge/notes", "project_id": "default"}
    field_name, uploaded = post_call.kwargs["files"][0]
    assert field_name == "files"
    assert uploaded == ("example.md", b"# hello\n", "text/markdown")


def test_pdf_knowledge_upload_converts_to_markdown_before_forwarding(client: TestClient):
    route_client = MagicMock()
    route_client.post = AsyncMock(
        return_value=_mock_brain_response(
            {
                "status": "ok",
                "files": [{"path": "knowledge/ingested/report.md", "size": 24}],
            }
        )
    )

    with (
        patch("app.gateway.routes.get_tts_config", return_value=_mock_cfg()),
        patch("app.gateway.routes._brain_http.get", return_value=route_client),
        patch(
            "app.gateway.routes._persist_upload_to_tempfile",
            new_callable=AsyncMock,
            return_value=("/tmp/fake-report.pdf", 14),
            create=True,
        ),
        patch(
            "app.gateway.routes.ingest_document",
            return_value=IngestionResult(
                content_type="document_content",
                content="# Converted Report\n",
                page_count=None,
            ),
            create=True,
        ),
        patch("app.gateway.routes._cleanup_temp_path", create=True),
        patch(
            "app.brain_proxy._proxy_to_brain",
            new_callable=AsyncMock,
            return_value=JSONResponse(content={"status": "proxied"}),
        ),
    ):
        response = client.post(
            "/api/knowledge/upload",
            data={"target_dir": "knowledge/ingested", "project_id": "default"},
            files={"files": ("report.pdf", BytesIO(b"%PDF-1.4 fake"), "application/pdf")},
        )

    assert response.status_code == 200
    assert response.json() == {
        "status": "ok",
        "files": [{"path": "knowledge/ingested/report.md", "size": 24}],
    }
    route_client.post.assert_awaited_once()
    post_call = route_client.post.await_args
    field_name, uploaded = post_call.kwargs["files"][0]
    assert field_name == "files"
    assert uploaded == ("report.md", b"# Converted Report\n", "text/markdown")


def test_html_knowledge_upload_converts_to_markdown_before_forwarding(client: TestClient):
    route_client = MagicMock()
    route_client.post = AsyncMock(
        return_value=_mock_brain_response(
            {
                "status": "ok",
                "files": [{"path": "knowledge/ingested/page.md", "size": 42}],
            }
        )
    )

    with (
        patch("app.gateway.routes.get_tts_config", return_value=_mock_cfg()),
        patch("app.gateway.routes._brain_http.get", return_value=route_client),
        patch(
            "app.gateway.routes._persist_upload_to_tempfile",
            new_callable=AsyncMock,
            return_value=("/tmp/fake-page.html", 27),
            create=True,
        ),
        patch(
            "app.gateway.routes.ingest_document",
            return_value=IngestionResult(
                content_type="document_content",
                content="# Converted HTML\n\nbody\n",
                page_count=None,
            ),
            create=True,
        ),
        patch("app.gateway.routes._cleanup_temp_path", create=True),
    ):
        response = client.post(
            "/api/knowledge/upload",
            data={"target_dir": "knowledge/ingested", "project_id": "default"},
            files={"files": ("page.html", BytesIO(b"<h1>hello</h1>"), "text/html")},
        )

    assert response.status_code == 200
    post_call = route_client.post.await_args
    field_name, uploaded = post_call.kwargs["files"][0]
    assert field_name == "files"
    assert uploaded == ("page.md", b"# Converted HTML\n\nbody\n", "text/markdown")


def test_knowledge_upload_is_not_documented_as_brain_proxy_mirror(client: TestClient):
    from app.brain_proxy import _BRAIN_ROUTE_DEFS

    assert "/api/knowledge/upload" not in {route["path"] for route in _BRAIN_ROUTE_DEFS}

    response = client.get("/openapi.json")

    assert response.status_code == 200
    assert "/api/knowledge/upload" in response.json()["paths"]
