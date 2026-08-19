import io

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.routes import mascots as mascot_routes


VRM_BYTES = b"glTFvrm"


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setenv("AVATAR_MASCOTS_DIR", str(tmp_path))
    from app.auth.dependencies import AuthTransport, CurrentAccount, get_current_account, require_admin
    from app.auth.models import AccountRole, AccountType, ResourceType, ResourceVisibility, UserRecord
    from app.auth.runtime import get_auth_runtime
    from app.config import get_tts_config

    get_tts_config.cache_clear()
    mascot_routes.reset_store()
    runtime = get_auth_runtime()
    for mid, label in [("haru-live2d", "Haru"), ("qqman", "Frieren"), ("vrm-sample", "VRM Sample")]:
        runtime.resources.upsert_system_resource(
            resource_type=ResourceType.AVATAR_MASCOT,
            resource_id=mid,
            metadata={"label": label},
        )

    admin_user = UserRecord(
        id="test-admin",
        username="admin",
        username_normalized="admin",
        password_hash="",
        role=AccountRole.ADMIN,
        account_type=AccountType.FORMAL,
        disabled=False,
        token_version=1,
        created_at="2026-01-01T00:00:00Z",
        updated_at="2026-01-01T00:00:00Z",
        created_by=None,
    )
    admin_account = CurrentAccount(user=admin_user, transport=AuthTransport.BEARER)

    app = FastAPI()
    app.include_router(mascot_routes.router)
    app.dependency_overrides[get_current_account] = lambda: admin_account
    app.dependency_overrides[require_admin] = lambda: admin_account
    return TestClient(app)


def _upload(client, mascot_id="custom", label="自訂小助理", model=VRM_BYTES):
    return client.post(
        "/api/avatar/mascots",
        data={"mascot_id": mascot_id, "label": label},
        files={"model": ("custom.vrm", io.BytesIO(model), "model/gltf-binary")},
    )


def test_list_builtin_mascots(client):
    response = client.get("/api/avatar/mascots")

    assert response.status_code == 200
    mascots = response.json()["mascots"]
    assert mascots[0]["mascot_id"] == "haru-live2d"
    assert mascots[1]["label"] == "Frieren"
    assert mascots[1]["builtin"] is True


def test_upload_then_list(client):
    response = _upload(client)

    assert response.status_code == 200
    assert response.json()["mascot"]["mascot_id"] == "custom"
    mascots = client.get("/api/avatar/mascots").json()["mascots"]
    assert mascots[-1]["vrm_url"] == "/mascots/custom/model.vrm"


def test_upload_bad_extension(client):
    response = client.post(
        "/api/avatar/mascots",
        data={"mascot_id": "custom", "label": "x"},
        files={"model": ("custom.glb", io.BytesIO(VRM_BYTES), "model/gltf-binary")},
    )

    assert response.status_code == 400


def test_upload_bad_magic(client):
    response = _upload(client, model=b"NOTVRM")

    assert response.status_code == 400


@pytest.mark.parametrize("mascot_id", [".", "..", ".hidden", "bad-", "_bad"])
def test_upload_bad_mascot_id(client, mascot_id):
    response = _upload(client, mascot_id=mascot_id)

    assert response.status_code == 400


def test_upload_duplicate_conflict(client):
    assert _upload(client).status_code == 200

    assert _upload(client).status_code == 409


def test_upload_duplicate_builtin_conflict(client):
    response = _upload(client, mascot_id="qqman")

    assert response.status_code == 409


def test_update_label(client):
    _upload(client)
    response = client.patch("/api/avatar/mascots/custom", json={"label": "新名稱"})

    assert response.status_code == 200
    assert response.json()["mascot"]["label"] == "新名稱"


def test_delete(client):
    _upload(client)

    assert client.delete("/api/avatar/mascots/custom").status_code == 200
    mascots = client.get("/api/avatar/mascots").json()["mascots"]
    assert [mascot["mascot_id"] for mascot in mascots] == [
        "haru-live2d",
        "qqman",
        "vrm-sample",
    ]


def test_delete_builtin_404(client):
    response = client.delete("/api/avatar/mascots/qqman")

    assert response.status_code == 404
