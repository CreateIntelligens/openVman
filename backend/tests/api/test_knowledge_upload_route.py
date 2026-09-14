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
        document_max_upload_bytes=10 * 1024 * 1024,
        docling_serve_url="http://docling-serve:5001",
        docling_timeout_ms=5000,
        docling_api_key="",
        docling_fallback_to_anydoc=True,
        gateway_internal_token="internal-secret",
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
        from app.auth.runtime import get_auth_runtime
        from app.auth.models import AccountRole, ResourceType, ResourceVisibility
        from app.auth.passwords import hash_password

        get_tts_config.cache_clear()
        get_auth_runtime.cache_clear()
        runtime = get_auth_runtime()
        admin = runtime.users.get_by_username("admin")
        if not admin:
            admin = runtime.users.create(
                username="admin",
                password_hash=hash_password("admin-password"),
                role=AccountRole.ADMIN,
            )
        try:
            runtime.resources.register(
                resource_type=ResourceType.PROJECT,
                resource_id="default",
                owner_user_id=admin.id,
                visibility=ResourceVisibility.PRIVATE,
            )
        except Exception:
            pass
        token = runtime.tokens.issue(admin)
        from app.main import app

        with TestClient(app, raise_server_exceptions=False) as c:
            c.headers["Authorization"] = f"Bearer {token}"
            c.headers["Origin"] = "http://testserver"
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
            "/api/v1/knowledge/upload",
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
    assert post_call.kwargs["data"] == {
        "target_dir": "knowledge/notes",
        "project_id": "default",
        "relative_paths": ["example.md"],
    }
    field_name, uploaded = post_call.kwargs["files"][0]
    assert field_name == "files"
    assert uploaded == ("example.md", b"# hello\n", "text/markdown")


def test_pdf_knowledge_upload_converts_to_markdown_before_forwarding(client: TestClient):
    route_client = MagicMock()
    route_client.post = AsyncMock(
        side_effect=[
            _mock_brain_response({"status": "ok", "files": [{"path": "raw/ingested/report.pdf", "size": 14}]}),
            _mock_brain_response(
                {
                    "status": "ok",
                    "files": [{"path": "knowledge/ingested/report.md", "size": 24}],
                }
            ),
        ]
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
            "/api/v1/knowledge/upload",
            data={"target_dir": "knowledge/ingested", "project_id": "default"},
            files={"files": ("report.pdf", BytesIO(b"%PDF-1.4 fake"), "application/pdf")},
        )

    assert response.status_code == 200
    assert response.json() == {
        "status": "ok",
        "files": [{"path": "knowledge/ingested/report.md", "size": 24}],
    }
    assert route_client.post.await_count == 2
    raw_call = route_client.post.await_args_list[0]
    assert raw_call.args[0] == "http://brain:8100/brain/knowledge/raw/upload"
    assert raw_call.kwargs["data"] == {"target_dir": "raw/ingested", "project_id": "default"}
    markdown_call = route_client.post.await_args_list[1]
    assert markdown_call.kwargs["data"] == {
        "target_dir": "knowledge/ingested",
        "project_id": "default",
        "relative_paths": ["report.md"],
    }
    raw_filename, raw_uploaded, raw_content_type = raw_call.kwargs["files"]["files"]
    assert raw_filename == "report.pdf"
    assert raw_uploaded == b"%PDF-1.4 fake"
    assert raw_content_type == "application/octet-stream"

    post_call = route_client.post.await_args_list[1]
    field_name, uploaded = post_call.kwargs["files"][0]
    assert field_name == "files"
    assert uploaded == ("report.md", b"# Converted Report\n", "text/markdown")


def test_document_upload_normalizes_markdown_target_dir_under_knowledge(client: TestClient):
    route_client = MagicMock()
    route_client.post = AsyncMock(
        side_effect=[
            _mock_brain_response({"status": "ok", "files": [{"path": "raw/custom/report.pdf", "size": 14}]}),
            _mock_brain_response(
                {
                    "status": "ok",
                    "files": [{"path": "knowledge/custom/report.md", "size": 24}],
                }
            ),
        ]
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
    ):
        response = client.post(
            "/api/v1/knowledge/upload",
            data={"target_dir": "custom", "project_id": "default"},
            files={"files": ("report.pdf", BytesIO(b"%PDF-1.4 fake"), "application/pdf")},
        )

    assert response.status_code == 200
    raw_call = route_client.post.await_args_list[0]
    assert raw_call.kwargs["data"] == {"target_dir": "raw/custom", "project_id": "default"}
    markdown_call = route_client.post.await_args_list[1]
    assert markdown_call.kwargs["data"] == {
        "target_dir": "knowledge/custom",
        "project_id": "default",
        "relative_paths": ["report.md"],
    }


def test_pptx_knowledge_upload_converts_to_markdown_before_forwarding(client: TestClient):
    route_client = MagicMock()
    route_client.post = AsyncMock(
        side_effect=[
            _mock_brain_response({"status": "ok", "files": [{"path": "raw/ingested/deck.pptx", "size": 11}]}),
            _mock_brain_response(
                {
                    "status": "ok",
                    "files": [{"path": "knowledge/ingested/deck.md", "size": 18}],
                }
            ),
        ]
    )

    with (
        patch("app.gateway.routes.get_tts_config", return_value=_mock_cfg()),
        patch("app.gateway.routes._brain_http.get", return_value=route_client),
        patch(
            "app.gateway.routes._persist_upload_to_tempfile",
            new_callable=AsyncMock,
            return_value=("/tmp/fake-deck.pptx", 11),
            create=True,
        ),
        patch(
            "app.gateway.routes.ingest_document",
            return_value=IngestionResult(
                content_type="document_content",
                content="# Converted Deck\n",
                page_count=None,
            ),
            create=True,
        ),
    ):
        response = client.post(
            "/api/v1/knowledge/upload",
            data={"target_dir": "knowledge/ingested", "project_id": "default"},
            files={
                "files": (
                    "deck.pptx",
                    BytesIO(b"pptx-bytes"),
                    "application/vnd.openxmlformats-officedocument.presentationml.presentation",
                )
            },
        )

    assert response.status_code == 200
    post_call = route_client.post.await_args_list[1]
    field_name, uploaded = post_call.kwargs["files"][0]
    assert field_name == "files"
    assert uploaded == ("deck.md", b"# Converted Deck\n", "text/markdown")


def test_html_knowledge_upload_converts_to_markdown_before_forwarding(client: TestClient):
    route_client = MagicMock()
    route_client.post = AsyncMock(
        side_effect=[
            _mock_brain_response({"status": "ok", "files": [{"path": "raw/ingested/page.html", "size": 27}]}),
            _mock_brain_response(
                {
                    "status": "ok",
                    "files": [{"path": "knowledge/ingested/page.md", "size": 42}],
                }
            ),
        ]
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
            "/api/v1/knowledge/upload",
            data={"target_dir": "knowledge/ingested", "project_id": "default"},
            files={"files": ("page.html", BytesIO(b"<h1>hello</h1>"), "text/html")},
        )

    assert response.status_code == 200
    post_call = route_client.post.await_args_list[1]
    field_name, uploaded = post_call.kwargs["files"][0]
    assert field_name == "files"
    assert uploaded == ("page.md", b"# Converted HTML\n\nbody\n", "text/markdown")


def test_knowledge_upload_is_not_documented_as_brain_proxy_mirror(client: TestClient):
    from app.brain_proxy import _BRAIN_ROUTE_DEFS

    assert "/api/v1/knowledge/upload" not in {route["path"] for route in _BRAIN_ROUTE_DEFS}

    response = client.get("/openapi.json")

    assert response.status_code == 200
    assert "/api/v1/knowledge/upload" in response.json()["paths"]


@pytest.mark.parametrize("limit", [8, 1024 * 1024])
def test_upload_limits_reports_configured_document_limit(client, limit):
    cfg = _mock_cfg()
    cfg.document_max_upload_bytes = limit
    with patch("app.gateway.routes.get_tts_config", return_value=cfg):
        response = client.get("/api/v1/uploads/limits")
    assert response.status_code == 200
    assert response.json() == {"document_max_upload_bytes": limit}


@pytest.mark.parametrize("path", ["upload", "raw/upload"])
@pytest.mark.parametrize("filename", ["report.md", "report.txt", "report.csv"])
def test_knowledge_upload_rejects_oversized_files_before_brain(
    client, path, filename,
):
    cfg = _mock_cfg()
    cfg.document_max_upload_bytes = 8
    route_client = MagicMock()
    route_client.post = AsyncMock()
    with (
        patch("app.gateway.routes.get_tts_config", return_value=cfg),
        patch("app.gateway.routes._brain_http.get", return_value=route_client),
    ):
        response = client.post(
            f"/api/v1/knowledge/{path}",
            data={"project_id": "default"},
            files={"files": (filename, b"123456789", "text/plain")},
        )
    assert response.status_code == 413
    route_client.post.assert_not_awaited()


def test_raw_upload_preserves_binary_and_form_fields_at_limit(client):
    cfg = _mock_cfg()
    cfg.document_max_upload_bytes = 8
    payload = {"status": "ok", "files": [{"path": "raw/folder/report.pdf"}]}
    route_client = MagicMock()
    route_client.post = AsyncMock(return_value=_mock_brain_response(payload))
    with (
        patch("app.gateway.routes.get_tts_config", return_value=cfg),
        patch("app.gateway.routes._brain_http.get", return_value=route_client),
    ):
        response = client.post(
            "/api/v1/knowledge/raw/upload",
            data={
                "project_id": "default",
                "target_dir": "raw/folder",
                "relative_paths": ["nested/report.pdf"],
            },
            files={"files": ("report.pdf", b"%PDF-123", "application/pdf")},
        )
    assert response.status_code == 200
    assert response.json() == payload
    call = route_client.post.await_args
    assert call.args[0] == "http://brain:8100/brain/knowledge/raw/upload"
    assert call.kwargs["data"] == {
        "project_id": "default",
        "target_dir": "raw/folder",
        "relative_paths": ["nested/report.pdf"],
    }
    assert call.kwargs["files"] == [
        ("files", ("report.pdf", b"%PDF-123", "application/pdf")),
    ]
    assert call.kwargs["headers"]["X-OpenVMan-Project-ID"] == "default"
    assert call.kwargs["headers"]["X-Internal-Token"] == "internal-secret"


def test_raw_upload_rejects_inaccessible_project_before_brain(client):
    route_client = MagicMock()
    route_client.post = AsyncMock()
    with patch("app.gateway.routes._brain_http.get", return_value=route_client):
        response = client.post(
            "/api/v1/knowledge/raw/upload",
            data={"project_id": "inaccessible"},
            files={"files": ("report.pdf", b"%PDF-123", "application/pdf")},
        )
    assert response.status_code == 404
    route_client.post.assert_not_awaited()


@pytest.mark.parametrize("path", ["uploads/limits", "knowledge/raw/upload"])
def test_upload_endpoints_require_authentication(client, path):
    client.headers.pop("Authorization")
    if path == "uploads/limits":
        response = client.get(f"/api/v1/{path}")
    else:
        response = client.post(
            f"/api/v1/{path}",
            files={"files": ("report.txt", b"hello", "text/plain")},
        )
    assert response.status_code == 401


@pytest.mark.parametrize(
    "path",
    [
        "upload/",
        "raw/upload/",
        "%2e/upload",
        "a/%2e%2e/upload",
        "raw/%2e/upload",
        "raw/a/%2e%2e/upload",
    ],
)
def test_upload_cannot_bypass_limits_through_catchall(client, path):
    route_client = MagicMock()
    route_client.send = AsyncMock()
    with patch("app.brain_proxy._http.get", return_value=route_client):
        response = client.post(
            f"/api/v1/knowledge/{path}?project_id=default",
            files={"files": ("report.txt", b"hello", "text/plain")},
        )
    assert response.status_code == 404
    route_client.send.assert_not_awaited()


@pytest.mark.parametrize(
    ("portal_access", "granted", "expected_status"),
    [(True, True, 200), (False, True, 404), (True, False, 404)],
)
def test_raw_upload_requires_portal_user_project_edit_access(
    client, portal_access, granted, expected_status,
):
    from app.auth.models import AccountRole
    from app.auth.runtime import get_auth_runtime

    runtime = get_auth_runtime()
    user = runtime.users.create(
        username="portal-user",
        password_hash="unused",
        role=AccountRole.USER,
        admin_portal_access=portal_access,
    )
    client.headers["Authorization"] = f"Bearer {runtime.tokens.issue(user)}"
    route_client = MagicMock()
    route_client.post = AsyncMock(
        return_value=_mock_brain_response({"status": "ok", "files": []}),
    )
    with (
        patch.object(runtime.resources, "has_grant", return_value=granted),
        patch("app.gateway.routes._brain_http.get", return_value=route_client),
    ):
        response = client.post(
            "/api/v1/knowledge/raw/upload",
            data={"project_id": "default"},
            files={"files": ("report.txt", b"hello", "text/plain")},
        )
    assert response.status_code == expected_status
    if expected_status == 200:
        route_client.post.assert_awaited_once()
    else:
        route_client.post.assert_not_awaited()
