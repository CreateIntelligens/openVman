import io

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.routes import backgrounds as background_routes


PNG_BYTES = b"\x89PNG\r\n\x1a\nimage"


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setenv("AVATAR_BACKGROUNDS_DIR", str(tmp_path))
    from app.config import get_tts_config

    get_tts_config.cache_clear()
    background_routes.reset_store()
    app = FastAPI()
    app.include_router(background_routes.router)
    return TestClient(app)


def _upload(client, background_id="clinic", label="診間背景", image=PNG_BYTES):
    return client.post(
        "/api/backgrounds",
        data={"background_id": background_id, "label": label},
        files={"image": ("clinic.png", io.BytesIO(image), "image/png")},
    )


def test_list_empty(client):
    response = client.get("/api/backgrounds")

    assert response.status_code == 200
    assert response.json() == {"backgrounds": []}


def test_upload_then_list(client):
    response = _upload(client)

    assert response.status_code == 200
    assert response.json()["background"]["background_id"] == "clinic"
    backgrounds = client.get("/api/backgrounds").json()["backgrounds"]
    assert backgrounds[0]["url"] == "/backgrounds/clinic/image.png"


def test_upload_bad_extension(client):
    response = client.post(
        "/api/backgrounds",
        data={"background_id": "clinic", "label": "x"},
        files={"image": ("clinic.gif", io.BytesIO(PNG_BYTES), "image/gif")},
    )

    assert response.status_code == 400


def test_upload_bad_magic(client):
    response = client.post(
        "/api/backgrounds",
        data={"background_id": "clinic", "label": "x"},
        files={"image": ("clinic.png", io.BytesIO(b"NOTPNG"), "image/png")},
    )

    assert response.status_code == 400


def test_upload_duplicate_conflict(client):
    assert _upload(client).status_code == 200

    assert _upload(client).status_code == 409


def test_delete(client):
    _upload(client)

    assert client.delete("/api/backgrounds/clinic").status_code == 200
    assert client.get("/api/backgrounds").json()["backgrounds"] == []


def test_update_label(client):
    _upload(client)
    response = client.patch("/api/backgrounds/clinic", json={"label": "新的診間"})

    assert response.status_code == 200
    assert response.json()["background"]["background_id"] == "clinic"
    assert response.json()["background"]["label"] == "新的診間"
