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

    # 列表會自動把 avatar 角色衍生成小助理；預設給一個空的角色庫，避免碰到 /data/avatar
    monkeypatch.setattr(mascot_routes, "get_character_store", lambda: _FakeCharacterStore([]))

    app = FastAPI()
    app.include_router(mascot_routes.router)
    app.dependency_overrides[get_current_account] = lambda: admin_account
    app.dependency_overrides[require_admin] = lambda: admin_account
    return TestClient(app)


def _upload(client, mascot_id="custom", label="自訂小助理", model=VRM_BYTES):
    return client.post(
        "/api/v1/avatar/mascots",
        data={"mascot_id": mascot_id, "label": label},
        files={"model": ("custom.vrm", io.BytesIO(model), "model/gltf-binary")},
    )


def test_list_builtin_mascots(client):
    response = client.get("/api/v1/avatar/mascots")

    assert response.status_code == 200
    mascots = response.json()["mascots"]
    assert mascots[0]["mascot_id"] == "haru-live2d"
    assert mascots[1]["label"] == "Frieren"
    assert mascots[1]["builtin"] is True


def test_upload_then_list(client):
    response = _upload(client)

    assert response.status_code == 200
    assert response.json()["mascot"]["mascot_id"] == "custom"
    mascots = client.get("/api/v1/avatar/mascots").json()["mascots"]
    assert mascots[-1]["vrm_url"] == "/static/mascots/custom/model.vrm"


def test_upload_bad_extension(client):
    response = client.post(
        "/api/v1/avatar/mascots",
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
    response = client.patch("/api/v1/avatar/mascots/custom", json={"label": "新名稱"})

    assert response.status_code == 200
    assert response.json()["mascot"]["label"] == "新名稱"


def test_delete(client):
    _upload(client)

    assert client.delete("/api/v1/avatar/mascots/custom").status_code == 200
    mascots = client.get("/api/v1/avatar/mascots").json()["mascots"]
    assert [mascot["mascot_id"] for mascot in mascots] == [
        "haru-live2d",
        "qqman",
        "vrm-sample",
    ]


def test_delete_builtin_404(client):
    response = client.delete("/api/v1/avatar/mascots/qqman")

    assert response.status_code == 404


class _FakeCharacterStore:
    def __init__(self, characters):
        self._characters = characters

    def list_characters(self):
        return list(self._characters)


@pytest.fixture
def character_store(monkeypatch):
    store = _FakeCharacterStore(
        [
            {
                "char_id": "000",
                "label": "預設角色",
                "has_video": True,
                "has_data": True,
            },
            {
                "char_id": "broken",
                "label": "缺資料",
                "has_video": True,
                "has_data": False,
            },
        ]
    )
    monkeypatch.setattr(mascot_routes, "get_character_store", lambda: store)
    return store


def test_create_video_mascot_from_character(client, character_store):
    from app.auth.models import ResourceType
    from app.auth.runtime import get_auth_runtime

    # 列表同時要求角色授權，測試先把角色資源登記為系統資源
    get_auth_runtime().resources.upsert_system_resource(
        resource_type=ResourceType.AVATAR_CHARACTER,
        resource_id="000",
        metadata={"label": "預設角色"},
    )
    response = client.post(
        "/api/v1/avatar/mascots/from-character",
        json={"mascot_id": "matex-000", "label": "", "character_id": "000"},
    )

    assert response.status_code == 200
    mascot = response.json()["mascot"]
    assert mascot["engine"] == "video"
    assert mascot["character_id"] == "000"
    # 未填 label 時沿用角色名稱
    assert mascot["label"] == "預設角色"

    mascots = client.get("/api/v1/avatar/mascots").json()["mascots"]
    assert mascots[-1]["mascot_id"] == "matex-000"


def test_create_video_mascot_unknown_character(client, character_store):
    response = client.post(
        "/api/v1/avatar/mascots/from-character",
        json={"mascot_id": "matex-x", "character_id": "nope"},
    )

    assert response.status_code == 404


def test_create_video_mascot_incomplete_character(client, character_store):
    response = client.post(
        "/api/v1/avatar/mascots/from-character",
        json={"mascot_id": "matex-broken", "character_id": "broken"},
    )

    assert response.status_code == 400


def test_create_video_mascot_duplicate(client, character_store):
    _upload(client)

    response = client.post(
        "/api/v1/avatar/mascots/from-character",
        json={"mascot_id": "custom", "character_id": "000"},
    )

    assert response.status_code == 409


def test_video_mascot_hidden_without_character_access(client, character_store):
    from app.auth.models import ResourceType
    from app.auth.runtime import get_auth_runtime

    client.post(
        "/api/v1/avatar/mascots/from-character",
        json={"mascot_id": "matex-000", "character_id": "000"},
    )
    runtime = get_auth_runtime()
    # 角色資源尚未登記時，即使小助理資源存在也不該列出
    mascots = client.get("/api/v1/avatar/mascots").json()["mascots"]
    assert all(m["mascot_id"] != "matex-000" for m in mascots)

    runtime.resources.upsert_system_resource(
        resource_type=ResourceType.AVATAR_CHARACTER,
        resource_id="000",
        metadata={"label": "預設角色"},
    )
    mascots = client.get("/api/v1/avatar/mascots").json()["mascots"]
    assert any(m["mascot_id"] == "matex-000" for m in mascots)


def test_video_characters_are_listed_automatically(client, character_store):
    from app.auth.models import ResourceType
    from app.auth.runtime import get_auth_runtime

    runtime = get_auth_runtime()
    for cid in ("000", "broken"):
        runtime.resources.upsert_system_resource(
            resource_type=ResourceType.AVATAR_CHARACTER,
            resource_id=cid,
            metadata={"label": cid},
        )

    mascots = client.get("/api/v1/avatar/mascots").json()["mascots"]
    derived = [m for m in mascots if m["engine"] == "video"]

    # 素材齊全的 000 自動出現，缺嘴型資料的 broken 不出現
    assert [m["mascot_id"] for m in derived] == ["video-000"]
    assert derived[0]["character_id"] == "000"
    assert derived[0]["label"] == "預設角色"
    assert derived[0]["builtin"] is True


def test_explicit_video_mascot_suppresses_the_derived_entry(client, character_store):
    from app.auth.models import ResourceType
    from app.auth.runtime import get_auth_runtime

    get_auth_runtime().resources.upsert_system_resource(
        resource_type=ResourceType.AVATAR_CHARACTER,
        resource_id="000",
        metadata={"label": "預設角色"},
    )
    client.post(
        "/api/v1/avatar/mascots/from-character",
        json={"mascot_id": "matex-000", "character_id": "000"},
    )

    mascots = client.get("/api/v1/avatar/mascots").json()["mascots"]
    video_ids = [m["mascot_id"] for m in mascots if m["engine"] == "video"]
    assert video_ids == ["matex-000"]
