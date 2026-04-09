"""Tests for POST /uploads and GET /jobs routes."""

from __future__ import annotations

import os
from io import BytesIO
from unittest.mock import AsyncMock, patch

import pytest
from fastapi.testclient import TestClient


@pytest.fixture(autouse=True)
def _reset_singletons():
    """Reset config cache and temp storage singleton between tests."""
    from app.config import get_tts_config
    from app.gateway.temp_storage import reset_temp_storage

    get_tts_config.cache_clear()
    reset_temp_storage()
    yield
    get_tts_config.cache_clear()
    reset_temp_storage()


@pytest.fixture()
def client(tmp_path):
    env = {
        "GATEWAY_TEMP_DIR": str(tmp_path),
        "GATEWAY_TEMP_DIR_MAX_MB": "100",
        "GATEWAY_MAX_FILE_SIZE_MB": "1",
    }
    with patch.dict(os.environ, env, clear=False):
        from app.config import get_tts_config

        get_tts_config.cache_clear()
        from app.gateway.queue import EnqueueResult
        from app.main import app

        # Patch enqueue_job at the module where it's imported
        with (
            patch(
                "app.gateway.routes.enqueue_job",
                new_callable=AsyncMock,
                return_value=EnqueueResult(job_id="test-job-id", mode="sync"),
            ),
            patch("app.gateway.routes.set_job_status", new_callable=AsyncMock),
        ):
            with TestClient(app, raise_server_exceptions=False) as c:
                yield c


class TestUploadSuccess:
    def test_gateway_upload_returns_202(self, client: TestClient):
        data = b"fake pdf content"
        resp = client.post(
            "/uploads?session_id=test-session",
            files={"file": ("test.pdf", BytesIO(data), "application/pdf")},
        )
        assert resp.status_code == 202
        body = resp.json()
        assert body["status"] == "accepted"
        assert body["status_url"] == "/jobs/test-job-id"


class TestUploadMIME:
    def test_unsupported_mime_returns_400(self, client: TestClient):
        resp = client.post(
            "/uploads?session_id=test-session",
            files={"file": ("test.xyz", BytesIO(b"data"), "application/x-unknown")},
        )
        assert resp.status_code == 400
        assert "unsupported_mime_type" in resp.json()["error"]
        assert resp.json()["error_code"] == "UPLOAD_FAILED"
        assert resp.json()["message"] == "檔案上傳失敗"


class TestUploadSize:
    def test_oversized_file_returns_413(self, client: TestClient):
        # Max is 1 MB in fixture env
        big = b"x" * (2 * 1024 * 1024)
        resp = client.post(
            "/uploads?session_id=test-session",
            files={"file": ("big.pdf", BytesIO(big), "application/pdf")},
        )
        assert resp.status_code == 413
        assert "file_too_large" in resp.json()["error"]
        assert resp.json()["error_code"] == "UPLOAD_FAILED"
        assert resp.json()["message"] == "檔案上傳失敗"


class TestUploadQuota:
    def test_quota_exceeded_returns_413(self, client: TestClient, tmp_path):
        # Override to a tiny quota
        env = {"GATEWAY_TEMP_DIR_MAX_MB": "0"}
        from app.config import get_tts_config

        get_tts_config.cache_clear()
        with patch.dict(os.environ, env, clear=False):
            get_tts_config.cache_clear()
            # Write a file to push usage above 0 MB quota
            fpath = tmp_path / "dummy"
            fpath.write_bytes(b"x" * 1024)

            resp = client.post(
                "/uploads?session_id=test-session",
                files={"file": ("test.pdf", BytesIO(b"pdf"), "application/pdf")},
            )
            assert resp.status_code == 413
            assert "quota" in resp.json()["error"]
            assert resp.json()["error_code"] == "UPLOAD_FAILED"
            assert resp.json()["message"] == "檔案上傳失敗"


class TestJobStatusRoute:
    def test_gateway_job_status_returns_payload_when_found(self, client: TestClient):
        payload = {
            "job_id": "test-job-id",
            "status": "processing",
        }

        with patch("app.gateway.routes.get_job_status", new_callable=AsyncMock, return_value=payload):
            resp = client.get("/jobs/test-job-id")

        assert resp.status_code == 200
        assert resp.json() == payload

    def test_job_status_returns_404_when_missing(self, client: TestClient):
        with patch("app.gateway.routes.get_job_status", new_callable=AsyncMock, return_value=None):
            resp = client.get("/jobs/missing-job")

        assert resp.status_code == 404
        assert resp.json()["error"] == "job_not_found"
