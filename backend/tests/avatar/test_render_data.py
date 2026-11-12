"""Render sidecar acceptance, legacy conversion and asset-access boundaries."""

import base64
import gzip
import json
import math
from concurrent.futures import ThreadPoolExecutor
from types import SimpleNamespace

import pytest
from cryptography.hazmat.primitives import padding
from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes
from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient

from app.auth.dependencies import AuthTransport, CurrentAccount, require_admin
from app.auth.models import AccountRole, ResourceType, ResourceVisibility
from app.auth.passwords import hash_password
from app.auth.runtime import get_auth_runtime
from app.avatar import render_data
from app.avatar.store import AvatarStore
from app.config import get_tts_config
from app.routes import avatar, static_assets

KEY = "test-bundle-key1"
LIMIT = 1024 * 1024
MATRIX = [2, 0, 0, 0, 0, 3, 0, 0, 0, 0, 1, 0, 10, 20, 0, 1]


def _gzip(payload):
    return gzip.compress(json.dumps(payload).encode(), mtime=0)


def _legacy():
    template = [float(value) for value in range(1395)]
    inner = {"face3D_obj": template, "rect": [[1, 2, 181, 182]], "frame_num": 1}
    padder = padding.PKCS7(128).padder()
    raw = json.dumps(inner).encode()
    padded = padder.update(raw) + padder.finalize()
    iv = b"0" * 16
    encryptor = Cipher(algorithms.AES(KEY.encode()), modes.CBC(iv)).encryptor()
    encrypted = encryptor.update(padded) + encryptor.finalize()
    return {
        "combined_data": base64.b64encode(iv + encrypted).decode(),
        "json_data": [MATRIX + [1, 2] * 209],
    }


def _modern():
    return {
        "schema": "openvman.render.v1", "frameRate": 25,
        "frameSize": [320, 240], "template": [0.0] * 1395,
        "frames": [MATRIX + [1, 2] * 209 + [1, 2, 181, 182] + [0.0] * 512],
        "denseReference": "affine-rest",
    }


def _ring(width, height):
    return [coordinate for index in range(20) for coordinate in (
        90 - width * math.cos(index * math.pi / 10),
        90 - height * math.sin(index * math.pi / 10),
    )]


def _video_geometry():
    return {
        "schema": "openvman.render.v2", "frameRate": 25,
        "frameSize": [320, 240], "geometrySource": "mediapipe-video",
        "frames": [{"region": [10, 20, 190, 200],
                    "outer": _ring(30, 8), "inner": _ring(25, 1)}],
        "provenance": {"videoSha256": "a" * 64, "generator": "video-lips-v1"},
    }


def test_video_geometry_upload_does_not_restore_legacy_template(env):
    payload = _video_geometry()
    payload["template"] = [999] * 1395
    payload["frames"][0]["legacy"] = "discard"
    path = env.create("video-geometry", data={"render_data": payload})
    response = env.client.get("/static/characters/video-geometry/render_data.json.gz")
    assert response.status_code == 200
    result = json.loads(gzip.decompress(response.content))
    assert result["schema"] == "openvman.render.v2"
    assert "template" not in result and "legacy" not in result["frames"][0]
    assert result["provenance"] == payload["provenance"]
    assert (path / "01.webm").is_file()


@pytest.mark.parametrize("mutation", [
    lambda data: data.update(geometrySource="runtime-dump"),
    lambda data: data.update(frameRate=24),
    lambda data: data.update(frames=[]),
    lambda data: data["frames"][0].update(region=[0, 0, 321, 200]),
    lambda data: data["frames"][0].update(region=[0, 0, 0, 200]),
    lambda data: data["frames"][0].update(outer=[90] * 39),
    lambda data: data["frames"][0].update(inner=[float("nan")] * 40),
    lambda data: data["frames"][0].update(inner=[True] * 40),
    lambda data: data["frames"][0].update(inner=[181] * 40),
    lambda data: data["frames"][0].update(outer=[90] * 40),
    lambda data: data["frames"][0]["outer"].__setitem__(slice(10, 12), [90, 90]),
])
def test_video_geometry_rejects_invalid_or_out_of_frame_data(mutation):
    payload = _video_geometry()
    mutation(payload)
    with pytest.raises(render_data.RenderDataError):
        render_data.validate_render_data(payload)


@pytest.fixture
def env(tmp_path, monkeypatch):
    monkeypatch.setenv("AVATAR_ASSETS_DIR", str(tmp_path))
    monkeypatch.setenv("AVATAR_BUNDLE_KEY", KEY)
    get_tts_config.cache_clear()
    avatar.reset_store()
    runtime = get_auth_runtime()
    admin = runtime.users.create(
        username="render-admin", password_hash=hash_password("test-password"),
        role=AccountRole.ADMIN,
    )
    current = CurrentAccount(user=admin, transport=AuthTransport.BEARER)
    state = {"current": None}
    app = FastAPI()
    app.dependency_overrides[require_admin] = lambda: current
    app.dependency_overrides[static_assets._get_optional_current_account] = lambda: state["current"]
    app.include_router(static_assets.router)
    app.include_router(avatar.router)
    store = AvatarStore(tmp_path)

    def create(char_id="legacy", public=True, data=None):
        original = _gzip(_legacy() if data is None else data)
        store.create_character(
            char_id=char_id, label=char_id,
            video_bytes=b"\x1a\x45\xdf\xa3video", data_bytes=original,
        )
        runtime.resources.register(
            resource_type=ResourceType.AVATAR_CHARACTER, resource_id=char_id,
            owner_user_id=None if public else admin.id,
            visibility=ResourceVisibility.SYSTEM_PUBLIC if public else ResourceVisibility.PRIVATE,
        )
        return tmp_path / char_id

    def probe(command, **kwargs):
        assert command[0] == "ffprobe" and kwargs["timeout"] == 15
        return SimpleNamespace(stdout=b'{"streams":[{"width":320,"height":240}]}')

    monkeypatch.setattr(render_data.subprocess, "run", probe)
    return SimpleNamespace(
        client=TestClient(app), store=store, create=create, state=state,
        current=current, root=tmp_path,
    )


def test_server_conversion_preserves_sources_and_affine_row_contract(env):
    path = env.create()
    originals = {name: ((path / name).read_bytes(), (path / name).stat().st_mtime_ns)
                 for name in ("01.webm", "combined_data.json.gz")}
    response = env.client.get("/static/characters/legacy/render_data.json.gz")
    assert response.status_code == 200
    payload = json.loads(gzip.decompress(response.content))
    assert payload["frameSize"] == [320, 240]
    assert len(payload["frames"][0]) == 950
    assert payload["frames"][0][434:438] == [1, 2, 181, 182]
    assert payload["frames"][0][438:440] == [627 * 2 + 10, 628 * 3 + 20]
    for name, (original, modified) in originals.items():
        assert (path / name).read_bytes() == original
        assert (path / name).stat().st_mtime_ns == modified
    assert response.headers["cache-control"] == "public, max-age=3600"
    assert env.client.get("/static/characters/legacy/render_data.json.gz").content == response.content


def test_unauthorized_request_never_attempts_conversion(env, monkeypatch):
    path = env.create(public=False)
    monkeypatch.setattr(static_assets, "build_legacy_render_data", lambda *a, **k: pytest.fail("unauthorized conversion"))
    assert env.client.get("/static/characters/legacy/render_data.json.gz").status_code == 404
    assert not (path / render_data.RENDER_FILENAME).exists()


def test_authorized_private_conversion_keeps_private_cache_policy(env):
    env.create(public=False)
    env.state["current"] = env.current
    response = env.client.get("/static/characters/legacy/render_data.json.gz")
    assert response.status_code == 200
    assert response.headers["cache-control"] == "private, no-store"


def test_missing_key_is_an_explicit_conflict_and_does_not_write_sidecar(env, monkeypatch):
    path = env.create()
    monkeypatch.delenv("AVATAR_BUNDLE_KEY")
    response = env.client.get("/static/characters/legacy/render_data.json.gz")
    assert response.status_code == 409
    assert "重新產製" in response.json()["detail"]
    assert KEY not in response.text
    assert not (path / render_data.RENDER_FILENAME).exists()


def test_new_upload_has_sidecar_before_atomic_directory_publish(env, monkeypatch):
    import app.avatar.store as store_module

    rename = store_module.os.rename
    checked = []

    def inspect(source, target):
        assert not target.exists()
        assert (source / render_data.RENDER_FILENAME).is_file()
        checked.append(True)
        return rename(source, target)

    monkeypatch.setattr(store_module.os, "rename", inspect)
    original = _gzip({"render_data": _modern()})
    env.store.create_character(char_id="new", label="new", video_bytes=b"video", data_bytes=original)
    assert checked == [True]
    assert (env.root / "new" / "combined_data.json.gz").read_bytes() == original
    payload = json.loads(gzip.decompress((env.root / "new" / render_data.RENDER_FILENAME).read_bytes()))
    assert payload == _modern()


@pytest.mark.parametrize("mutate", [
    lambda p: p.update(frames=[]),
    lambda p: p.update(template=[0] * 1394),
    lambda p: p.update(frameSize=[0, 240]),
    lambda p: p.update(frameSize=[True, 240]),
    lambda p: p["frames"][0].pop(),
    lambda p: p["frames"][0].__setitem__(0, float("nan")),
    lambda p: p["frames"][0].__setitem__(0, float("inf")),
    lambda p: p["frames"][0].__setitem__(0, True),
])
def test_invalid_upload_is_rejected_without_publishing_character(env, mutate):
    payload = _modern()
    mutate(payload)
    response = env.client.post(
        "/api/v1/avatar", data={"char_id": "broken"},
        files={"video": ("01.webm", b"\x1a\x45\xdf\xa3video"),
               "data": ("combined_data.json.gz", _gzip({"render_data": payload}))},
    )
    assert response.status_code == 422
    assert not (env.root / "broken").exists()
    assert list(env.root.glob(".broken.tmp.*")) == []


def test_bounded_decompression_rejects_gzip_bombs():
    with pytest.raises(render_data.RenderDataError):
        render_data.extract_uploaded_render_data(gzip.compress(b" " * 2000), limit=1000)


def test_legacy_conversion_rejects_invalid_row_dimensions(env):
    source = _legacy()
    source["json_data"][0].pop()
    path = env.create(data=source)
    response = env.client.get("/static/characters/legacy/render_data.json.gz")
    assert response.status_code == 409
    assert not (path / render_data.RENDER_FILENAME).exists()


def test_modern_embedded_data_can_rebuild_missing_sidecar_without_key(env, monkeypatch):
    path = env.create(data={"render_data": _modern()})
    (path / render_data.RENDER_FILENAME).unlink()
    monkeypatch.delenv("AVATAR_BUNDLE_KEY")
    assert env.client.get("/static/characters/legacy/render_data.json.gz").status_code == 200


@pytest.mark.parametrize("relative", ["../private/01.webm", "../private/render_data.json.gz"])
def test_resolver_cannot_cross_from_public_to_private_character(env, relative):
    env.create("public")
    env.create("private", public=False)
    with pytest.raises(HTTPException) as caught:
        static_assets._resolve_asset_file(str(env.root), "public", relative)
    assert caught.value.status_code == 404
    response = env.client.get(f"/static/characters/public/{relative.replace('../', '%2E%2E%2F')}")
    assert response.status_code == 404


def test_symlink_alias_cannot_expose_another_character(env):
    public = env.create("public")
    private = env.create("private", public=False)
    (public / "alias.webm").symlink_to(private / "01.webm")
    assert env.client.get("/static/characters/public/alias.webm").status_code == 404
    (env.root / "alias").symlink_to(private, target_is_directory=True)
    with pytest.raises(HTTPException):
        static_assets._resolve_asset_file(str(env.root), "alias", "01.webm")


def test_concurrent_sidecar_writers_publish_only_complete_files(tmp_path):
    candidates = [_gzip({"writer": index, "content": "x" * 5000}) for index in range(8)]
    with ThreadPoolExecutor(max_workers=4) as pool:
        list(pool.map(lambda data: render_data.write_render_sidecar(tmp_path, data), candidates))
    actual = (tmp_path / render_data.RENDER_FILENAME).read_bytes()
    assert actual in candidates
    assert json.loads(gzip.decompress(actual))["content"] == "x" * 5000
    assert list(tmp_path.glob(".render-data-*")) == []


def test_missing_original_files_returns_regeneration_conflict(env):
    path = env.create()
    (path / "01.webm").unlink()
    response = env.client.get("/static/characters/legacy/render_data.json.gz")
    assert response.status_code == 409
    assert "重新產製" in response.json()["detail"]


def test_probe_failure_is_a_sanitized_conflict(env, monkeypatch):
    env.create()

    def fail(*args, **kwargs):
        raise OSError("private source path must not reach HTTP details")

    monkeypatch.setattr(render_data.subprocess, "run", fail)
    response = env.client.get("/static/characters/legacy/render_data.json.gz")
    assert response.status_code == 409
    assert "private source" not in response.text


def test_malformed_gzip_upload_is_rejected_without_partial_character(env):
    with pytest.raises(render_data.RenderDataError):
        env.store.create_character(
            char_id="bad-gzip", label="bad", video_bytes=b"video",
            data_bytes=b"\x1f\x8bincomplete",
        )
    assert not (env.root / "bad-gzip").exists()
    assert list(env.root.glob(".bad-gzip.tmp.*")) == []


def test_eye_span_face_scale_is_kept_when_valid_and_optional():
    payload = _video_geometry()
    payload["frames"][0]["eyeSpan"] = 150.5
    clean = render_data.validate_render_data(payload)
    assert clean["frames"][0]["eyeSpan"] == 150.5
    assert "eyeSpan" not in render_data.validate_render_data(_video_geometry())["frames"][0]
    for bad in (0, -3, 1e6, float("nan"), "150"):
        payload["frames"][0]["eyeSpan"] = bad
        with pytest.raises(render_data.RenderDataError):
            render_data.validate_render_data(payload)
