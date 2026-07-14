import io

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.config import get_tts_config
from app.routes import avatar as avatar_routes
from app.routes import public_characters as public_characters_routes


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setenv("AVATAR_ASSETS_DIR", str(tmp_path))

    get_tts_config.cache_clear()
    avatar_routes.reset_store()
    public_characters_routes.reset_store()
    monkeypatch.setattr(avatar_routes, "_personas_bound_to", lambda char_id: [])
    app = FastAPI()
    app.include_router(avatar_routes.router)
    app.include_router(public_characters_routes.router)
    return TestClient(app)


def _upload(
    client,
    char_id="008",
    label="角色八",
    video=b"\x1a\x45\xdf\xa3v",
    data=b"\x1f\x8bd",
):
    return client.post(
        "/api/avatar",
        data={"char_id": char_id, "label": label},
        files={
            "video": ("01.webm", io.BytesIO(video), "video/webm"),
            "data": ("combined_data.json.gz", io.BytesIO(data), "application/gzip"),
        },
    )


def test_list_empty(client):
    response = client.get("/characters")

    assert response.status_code == 200
    assert response.json() == {"characters": []}


def test_list_only_returns_char_id_and_label(client):
    assert _upload(client).status_code == 200

    response = client.get("/characters")

    assert response.status_code == 200
    assert response.json() == {
        "characters": [{"char_id": "008", "label": "角色八"}]
    }


def test_list_excludes_incomplete_characters(tmp_path, client):
    (tmp_path / "001").mkdir()
    (tmp_path / "001" / "01.webm").write_bytes(b"x")

    response = client.get("/characters")

    assert response.json() == {"characters": []}


def test_list_excludes_in_progress_upload_tempdirs(tmp_path, client):
    (tmp_path / ".002.tmp.abc").mkdir()

    response = client.get("/characters")

    assert response.json() == {"characters": []}
