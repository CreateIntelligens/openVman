"""Tests for POST /upload route."""

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
        with patch(
            "app.gateway.routes.enqueue_job",
            new_callable=AsyncMock,
            return_value=EnqueueResult(job_id="test-job-id", mode="sync"),
        ):
            with TestClient(app, raise_server_exceptions=False) as c:
                yield c


class TestUploadSuccess:
    def test_upload_returns_202(self, client: TestClient):
        data = b"fake pdf content"
        resp = client.post(
            "/upload?session_id=test-session",
            files={"file": ("test.pdf", BytesIO(data), "application/pdf")},
        )
        assert resp.status_code == 202
        body = resp.json()
        assert body["status"] == "accepted"
        assert body["session_id"] == "test-session"
        assert "job_id" in body
        assert "trace_id" in body


class TestUploadMIME:
    def test_unsupported_mime_returns_400(self, client: TestClient):
        resp = client.post(
            "/upload?session_id=test-session",
            files={"file": ("test.xyz", BytesIO(b"data"), "application/x-unknown")},
        )
        assert resp.status_code == 400
        assert "unsupported_mime_type" in resp.json()["error"]


class TestUploadSize:
    def test_oversized_file_returns_413(self, client: TestClient):
        # Max is 1 MB in fixture env
        big = b"x" * (2 * 1024 * 1024)
        resp = client.post(
            "/upload?session_id=test-session",
            files={"file": ("big.pdf", BytesIO(big), "application/pdf")},
        )
        assert resp.status_code == 413
        assert "file_too_large" in resp.json()["error"]


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
                "/upload?session_id=test-session",
                files={"file": ("test.pdf", BytesIO(b"pdf"), "application/pdf")},
            )
            assert resp.status_code == 413
            assert "quota" in resp.json()["error"]
