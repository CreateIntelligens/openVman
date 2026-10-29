"""Video-to-bundle job routes with an in-memory Redis and arq pool."""

from __future__ import annotations

import io
import json
from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.avatar import jobs as avatar_jobs
from app.routes import avatar as avatar_routes
from app.utils.media import MediaProbe

MP4_BYTES = b"\x00\x00\x00\x18ftypisom" + b"\x00" * 16
WEBM_BYTES = b"\x1a\x45\xdf\xa3" + b"v" * 8


class FakeRedis:
    def __init__(self) -> None:
        self.store: dict[str, str] = {}

    async def get(self, key):
        value = self.store.get(key)
        return value.encode("utf-8") if value is not None else None

    async def set(self, key, value, ex=None):
        self.store[key] = value

    async def delete(self, key):
        self.store.pop(key, None)

    async def scan_iter(self, match=None):
        prefix = match.rstrip("*") if match else ""
        for key in list(self.store):
            if key.startswith(prefix):
                yield key.encode("utf-8")


class FakePool:
    def __init__(self, fail: bool = False) -> None:
        self.calls: list[tuple] = []
        self.fail = fail

    async def enqueue_job(self, function, payload, **kwargs):
        if self.fail:
            raise RuntimeError("redis gone")
        self.calls.append((function, payload, kwargs))


@pytest.fixture
def env(tmp_path, monkeypatch):
    monkeypatch.setenv("AVATAR_ASSETS_DIR", str(tmp_path / "avatar"))
    monkeypatch.setenv("AVATAR_JOBS_DIR", str(tmp_path / "jobs"))
    from app.config import get_tts_config
    get_tts_config.cache_clear()
    avatar_routes.reset_store()

    redis = FakeRedis()
    pool = FakePool()

    async def _redis():
        return redis

    async def _pool():
        return pool

    monkeypatch.setattr(avatar_jobs, "get_redis", _redis)
    monkeypatch.setattr(avatar_jobs, "get_arq_pool", _pool)
    # 測試用的影片 bytes 只有檔頭；時長檢查另有測試，這裡當成 10 秒的影片。
    monkeypatch.setattr(
        avatar_jobs.media_mod, "probe_media",
        lambda path: MediaProbe("mov,mp4", 10.0, has_audio=False, has_video=True),
    )

    from app.auth.dependencies import AuthTransport, CurrentAccount, get_current_account, require_admin
    from app.auth.models import AccountRole
    from app.auth.passwords import hash_password
    from app.auth.runtime import get_auth_runtime

    runtime = get_auth_runtime()
    admin = runtime.users.get_by_username("admin")
    if not admin:
        admin = runtime.users.create(
            username="admin",
            password_hash=hash_password("admin-password"),
            role=AccountRole.ADMIN,
        )
    current = CurrentAccount(user=admin, transport=AuthTransport.BEARER)

    app = FastAPI()
    app.dependency_overrides[get_current_account] = lambda: current
    app.dependency_overrides[require_admin] = lambda: current
    app.include_router(avatar_routes.router)
    return TestClient(app), redis, pool, tmp_path


def _submit(client, char_id="hero", filename="clip.mp4", payload=MP4_BYTES, label="主角"):
    return client.post(
        "/api/v1/avatar/jobs",
        data={"char_id": char_id, "label": label},
        files={"video": (filename, io.BytesIO(payload), "video/mp4")},
    )


def test_submit_writes_source_and_enqueues(env):
    client, redis, pool, tmp_path = env
    r = _submit(client)
    assert r.status_code == 200, r.text
    job = r.json()["job"]
    assert job["state"] == "queued"
    assert job["char_id"] == "hero"
    assert "input_path" not in job

    (function, payload, kwargs) = pool.calls[0]
    assert function == "build_avatar_bundle"
    assert kwargs["_queue_name"] == "vman:avatar-pipeline"
    source = Path(payload["input_path"])
    assert source.read_bytes() == MP4_BYTES
    assert source.parent == tmp_path / "jobs" / job["job_id"]
    assert Path(payload["output_dir"]).is_dir()


def test_submit_accepts_webm_source(env):
    client, _, pool, _ = env
    r = _submit(client, filename="clip.webm", payload=WEBM_BYTES)
    assert r.status_code == 200, r.text
    assert Path(pool.calls[0][1]["input_path"]).suffix == ".webm"


@pytest.mark.parametrize(
    ("filename", "payload"),
    [("clip.avi", MP4_BYTES), ("clip.mp4", b"not a video"), ("clip.webm", MP4_BYTES)],
)
def test_submit_rejects_bad_sources(env, filename, payload):
    client, _, pool, tmp_path = env
    r = _submit(client, filename=filename, payload=payload)
    assert r.status_code == 415
    assert r.json()["detail"]
    assert pool.calls == []
    # 驗不過的暫存檔不能留在工作目錄。
    assert not list((tmp_path / "jobs").glob("*.upload"))


def _png(width: int = 4, height: int = 4) -> bytes:
    from PIL import Image

    buffer = io.BytesIO()
    Image.new("RGBA", (width, height)).save(buffer, format="PNG")
    return buffer.getvalue()


@pytest.mark.parametrize("filename", ["face.png", "face.jpg", "face"])
def test_submit_accepts_a_portrait_image_and_keeps_its_real_suffix(env, filename):
    client, _, pool, _ = env
    r = _submit(client, filename=filename, payload=_png())
    assert r.status_code == 200, r.text
    source = Path(pool.calls[0][1]["input_path"])
    # 素材管線靠副檔名判斷是圖片；副檔名跟著實際內容走。
    assert source.suffix == ".png"
    assert source.read_bytes()[:8] == b"\x89PNG\r\n\x1a\n"


def test_submit_rejects_an_image_whose_magic_does_not_match(env):
    client, _, pool, _ = env
    r = _submit(client, filename="face.png", payload=b"GIF89a" + b"\0" * 32)
    assert r.status_code == 415
    assert pool.calls == []


def test_submit_rejects_an_image_over_the_size_limit(env, monkeypatch):
    client, _, pool, _ = env
    monkeypatch.setenv("AVATAR_SOURCE_IMAGE_MAX_UPLOAD_BYTES", "64")
    from app.config import get_tts_config

    get_tts_config.cache_clear()
    r = _submit(client, filename="face.png", payload=_png() + b"\0" * 128)
    assert r.status_code == 413
    assert "圖片超過大小上限" in r.json()["detail"]
    assert pool.calls == []


def test_submit_rejects_an_image_over_the_max_side(env):
    client, _, pool, _ = env
    r = _submit(client, filename="wide.png", payload=_png(8193, 1))
    assert r.status_code == 413
    assert pool.calls == []


def test_submit_rejects_a_video_over_the_size_limit(env, monkeypatch):
    client, _, pool, _ = env
    monkeypatch.setenv("AVATAR_SOURCE_MAX_UPLOAD_BYTES", "16")
    from app.config import get_tts_config

    get_tts_config.cache_clear()
    r = _submit(client, payload=MP4_BYTES)
    assert r.status_code == 413
    assert pool.calls == []


def test_submit_rejects_a_video_longer_than_the_limit(env, monkeypatch):
    client, _, pool, _ = env
    monkeypatch.setattr(
        avatar_jobs.media_mod, "probe_media",
        lambda path: MediaProbe("mov,mp4", 61.0, has_audio=False, has_video=True),
    )
    r = _submit(client)
    assert r.status_code == 413
    assert "影片長度超過上限" in r.json()["detail"]
    assert pool.calls == []


def test_default_source_limits():
    from app.config import TTSRouterConfig

    cfg = TTSRouterConfig()
    assert cfg.avatar_source_max_upload_bytes == 200 * 1024 * 1024
    assert cfg.avatar_source_image_max_upload_bytes == 25 * 1024 * 1024
    assert cfg.avatar_source_max_duration_seconds == 60


def test_submit_conflicts_with_existing_character(env):
    client, _, _, _ = env
    avatar_routes.get_store().create_character(
        char_id="hero", label="x", video_bytes=WEBM_BYTES, data_bytes=b"\x1f\x8bd",
    )
    assert _submit(client).status_code == 409


def test_submit_cleans_up_when_enqueue_fails(env):
    client, redis, pool, tmp_path = env
    pool.fail = True
    r = _submit(client)
    assert r.status_code == 503
    assert redis.store == {}
    assert list((tmp_path / "jobs").iterdir()) == []


def test_get_finalizes_done_job_into_a_character(env):
    client, redis, pool, tmp_path = env
    job_id = _submit(client).json()["job"]["job_id"]
    out = Path(pool.calls[0][1]["output_dir"])
    (out / "01.webm").write_bytes(WEBM_BYTES)
    (out / "combined_data.json.gz").write_bytes(b"\x1f\x8bdata")
    record = json.loads(redis.store[f"vman:avatar-pipeline:job:{job_id}"])
    record.update({"state": "done", "stage": "done", "frame_count": 150})
    redis.store[f"vman:avatar-pipeline:job:{job_id}"] = json.dumps(record)

    r = client.get(f"/api/v1/avatar/jobs/{job_id}")
    assert r.status_code == 200
    job = r.json()["job"]
    assert job["state"] == "done"
    assert job["character"]["char_id"] == "hero"
    assert job["character"]["label"] == "主角"
    assert not (tmp_path / "jobs" / job_id).exists()

    chars = client.get("/api/v1/avatar").json()["characters"]
    assert [c["char_id"] for c in chars] == ["hero"]

    # Reading again must not try to create the character a second time.
    assert client.get(f"/api/v1/avatar/jobs/{job_id}").json()["job"]["state"] == "done"


def test_get_marks_done_job_failed_when_outputs_missing(env):
    client, redis, _, _ = env
    job_id = _submit(client).json()["job"]["job_id"]
    key = f"vman:avatar-pipeline:job:{job_id}"
    record = json.loads(redis.store[key])
    record["state"] = "done"
    redis.store[key] = json.dumps(record)
    job = client.get(f"/api/v1/avatar/jobs/{job_id}").json()["job"]
    assert job["state"] == "failed"
    assert "找不到輸出檔" in job["error"]


def test_list_orders_newest_first_and_delete_removes_files(env):
    client, redis, pool, tmp_path = env
    first = _submit(client, char_id="a").json()["job"]["job_id"]
    second = _submit(client, char_id="b").json()["job"]["job_id"]
    key = f"vman:avatar-pipeline:job:{second}"
    record = json.loads(redis.store[key])
    record["created_at"] += 10
    redis.store[key] = json.dumps(record)

    jobs = client.get("/api/v1/avatar/jobs").json()["jobs"]
    assert [j["job_id"] for j in jobs] == [second, first]

    # Still queued: the worker will pick it up, so its files must stay.
    assert client.delete(f"/api/v1/avatar/jobs/{first}").status_code == 409
    first_key = f"vman:avatar-pipeline:job:{first}"
    record = json.loads(redis.store[first_key])
    record["state"] = "failed"
    redis.store[first_key] = json.dumps(record)
    assert client.delete(f"/api/v1/avatar/jobs/{first}").status_code == 200
    assert not (tmp_path / "jobs" / first).exists()
    assert client.get(f"/api/v1/avatar/jobs/{first}").status_code == 404

    record = json.loads(redis.store[key])
    record["state"] = "running"
    redis.store[key] = json.dumps(record)
    assert client.delete(f"/api/v1/avatar/jobs/{second}").status_code == 409


def test_queue_unavailable_returns_503(env, monkeypatch):
    client, _, _, _ = env

    async def _none():
        return None

    monkeypatch.setattr(avatar_jobs, "get_redis", _none)
    assert _submit(client).status_code == 503
    assert client.get("/api/v1/avatar/jobs").status_code == 503
