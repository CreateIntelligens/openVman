import io

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.routes import avatar as avatar_routes


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setenv("AVATAR_ASSETS_DIR", str(tmp_path))
    from app.config import get_tts_config
    get_tts_config.cache_clear()
    avatar_routes.reset_store()
    monkeypatch.setattr(avatar_routes, "_personas_bound_to", lambda char_id: [])
    app = FastAPI()
    app.include_router(avatar_routes.router)
    return TestClient(app)


def _upload(client, char_id="008", label="角色八", video=b"\x1a\x45\xdf\xa3v", data=b"\x1f\x8bd"):
    return client.post(
        "/api/avatar",
        data={"char_id": char_id, "label": label},
        files={
            "video": ("01.webm", io.BytesIO(video), "video/webm"),
            "data": ("combined_data.json.gz", io.BytesIO(data), "application/gzip"),
        },
    )


def test_list_empty(client):
    r = client.get("/api/avatar")
    assert r.status_code == 200
    assert r.json() == {"characters": []}


def test_upload_then_list(client):
    assert _upload(client).status_code == 200
    chars = client.get("/api/avatar").json()["characters"]
    assert len(chars) == 1
    assert chars[0]["char_id"] == "008"


def test_upload_bad_extension(client):
    r = client.post(
        "/api/avatar",
        data={"char_id": "008", "label": "x"},
        files={
            "video": ("01.mp4", io.BytesIO(b"\x1a\x45\xdf\xa3"), "video/mp4"),
            "data": ("d.gz", io.BytesIO(b"\x1f\x8b"), "application/gzip"),
        },
    )
    assert r.status_code == 400


def test_upload_bad_magic(client):
    r = client.post(
        "/api/avatar",
        data={"char_id": "008", "label": "x"},
        files={
            "video": ("01.webm", io.BytesIO(b"NOTWEBM"), "video/webm"),
            "data": ("d.gz", io.BytesIO(b"\x1f\x8b"), "application/gzip"),
        },
    )
    assert r.status_code == 400


def test_upload_duplicate_conflict(client):
    assert _upload(client).status_code == 200
    assert _upload(client).status_code == 409


def test_upload_invalid_char_id(client):
    r = client.post(
        "/api/avatar",
        data={"char_id": "a/b", "label": "x"},
        files={
            "video": ("01.webm", io.BytesIO(b"\x1a\x45\xdf\xa3"), "video/webm"),
            "data": ("d.gz", io.BytesIO(b"\x1f\x8b"), "application/gzip"),
        },
    )
    assert r.status_code == 400


def test_delete(client):
    _upload(client)
    assert client.delete("/api/avatar/008").status_code == 200
    assert client.get("/api/avatar").json()["characters"] == []


def test_delete_missing_404(client):
    assert client.delete("/api/avatar/nope").status_code == 404


def test_delete_bound_conflict(client, monkeypatch):
    _upload(client)
    monkeypatch.setattr(avatar_routes, "_personas_bound_to", lambda char_id: ["doctor01"])
    r = client.delete("/api/avatar/008")
    assert r.status_code == 409
    assert "doctor01" in r.json()["detail"]


def test_rename(client):
    _upload(client, char_id="008")
    r = client.post("/api/avatar/008/rename", json={"new_char_id": "008b"})
    assert r.status_code == 200
    ids = [c["char_id"] for c in client.get("/api/avatar").json()["characters"]]
    assert ids == ["008b"]


def test_rename_conflict(client):
    _upload(client, char_id="008")
    _upload(client, char_id="009")
    r = client.post("/api/avatar/008/rename", json={"new_char_id": "009"})
    assert r.status_code == 409


def test_rename_bound_conflict(client, monkeypatch):
    _upload(client, char_id="008")
    monkeypatch.setattr(avatar_routes, "_personas_bound_to", lambda char_id: ["doctor01"])
    r = client.post("/api/avatar/008/rename", json={"new_char_id": "008b"})
    assert r.status_code == 409
