"""Tests for TempStorageService."""

from __future__ import annotations

import os
import time
from unittest.mock import patch

import pytest

from app.gateway.temp_storage import TempStorageService


@pytest.fixture()
def storage(tmp_path):
    """Create a TempStorageService rooted in a pytest tmp dir."""
    env = {
        "GATEWAY_TEMP_DIR": str(tmp_path),
        "GATEWAY_TEMP_DIR_MAX_MB": "1",
        "GATEWAY_MAX_FILE_SIZE_MB": "1",
        "GATEWAY_TEMP_TTL_MIN": "0",  # 0 min TTL for testing cleanup
    }
    from app.config import get_tts_config

    get_tts_config.cache_clear()
    with patch.dict(os.environ, env, clear=False):
        get_tts_config.cache_clear()
        svc = TempStorageService(base_dir=str(tmp_path))
        yield svc
    get_tts_config.cache_clear()


class TestWriteFile:
    def test_write_returns_path(self, storage: TempStorageService):
        path = storage.write_file("sess1", b"hello", "application/pdf")
        assert os.path.exists(path)
        assert path.endswith(".pdf")
        with open(path, "rb") as f:
            assert f.read() == b"hello"

    def test_write_jpeg_extension(self, storage: TempStorageService):
        path = storage.write_file("sess1", b"\xff\xd8", "image/jpeg")
        assert path.endswith(".jpg")

    def test_write_unknown_mime(self, storage: TempStorageService):
        path = storage.write_file("sess1", b"data", "application/x-unknown")
        assert path.endswith(".bin")


class TestPathTraversal:
    def test_dotdot_rejected(self, storage: TempStorageService):
        with pytest.raises(ValueError, match="path traversal"):
            storage.write_file("../etc", b"bad", "image/png")

    def test_slash_rejected(self, storage: TempStorageService):
        with pytest.raises(ValueError, match="path traversal"):
            storage.write_file("a/b", b"bad", "image/png")

    def test_encoded_slash_rejected(self, storage: TempStorageService):
        with pytest.raises(ValueError, match="path traversal"):
            storage.write_file("a%2Fb", b"bad", "image/png")


class TestQuota:
    def test_quota_ok_when_under_limit(self, storage: TempStorageService):
        storage.write_file("s1", b"x" * 100, "image/png")
        quota = storage.check_quota()
        assert quota.ok is True
        assert quota.usage_mb < quota.limit_mb

    def test_quota_exceeded(self, storage: TempStorageService, tmp_path):
        # Write > 1 MB (limit is 1 MB in fixture)
        big = b"x" * (1024 * 1024 + 1)
        storage.write_file("s1", big, "image/png")
        quota = storage.check_quota()
        assert quota.ok is False


class TestFileSize:
    def test_valid_size(self, storage: TempStorageService):
        assert storage.validate_file_size(100) is True

    def test_over_limit(self, storage: TempStorageService):
        # limit is 1 MB
        assert storage.validate_file_size(2 * 1024 * 1024) is False

    def test_exact_limit(self, storage: TempStorageService):
        assert storage.validate_file_size(1 * 1024 * 1024) is True


class TestTTLCleanup:
    def test_cleanup_removes_old_files(self, storage: TempStorageService, tmp_path):
        path = storage.write_file("s1", b"old", "image/png")
        # Set mtime to past (TTL is 0 min in fixture, so anything >0 sec is expired)
        old_time = time.time() - 120
        os.utime(path, (old_time, old_time))
        storage.run_ttl_cleanup()
        assert not os.path.exists(path)

    def test_cleanup_keeps_fresh_files(self, storage: TempStorageService):
        env = {
            "GATEWAY_TEMP_TTL_MIN": "999",
        }
        from app.config import get_tts_config
        get_tts_config.cache_clear()
        with patch.dict(os.environ, env, clear=False):
            get_tts_config.cache_clear()
            path = storage.write_file("s2", b"fresh", "image/png")
            storage.run_ttl_cleanup()
            assert os.path.exists(path)
        get_tts_config.cache_clear()


class TestCleanupSession:
    def test_cleanup_session_removes_dir(self, storage: TempStorageService, tmp_path):
        storage.write_file("sess_cleanup", b"data", "image/png")
        session_dir = os.path.join(str(tmp_path), "sess_cleanup")
        assert os.path.isdir(session_dir)
        storage.cleanup_session("sess_cleanup")
        assert not os.path.exists(session_dir)

    def test_cleanup_session_ignores_traversal(self, storage: TempStorageService):
        # Should silently do nothing
        storage.cleanup_session("../bad")
