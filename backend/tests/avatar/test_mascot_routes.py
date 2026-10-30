import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.routes import mascots as mascot_routes
from app.routes import static_assets


@pytest.fixture
def runtime():
    from app.auth.models import ResourceType
    from app.auth.runtime import get_auth_runtime

    runtime = get_auth_runtime()
    runtime.resources.upsert_system_resource(
        resource_type=ResourceType.AVATAR_MASCOT,
        resource_id="haru-live2d",
        metadata={"label": "Haru"},
    )
    return runtime


@pytest.fixture
def client(runtime):
    from app.auth.dependencies import (
        AuthTransport,
        CurrentAccount,
        get_current_account,
        require_admin,
    )
    from app.auth.models import AccountRole, AccountType, UserRecord

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
    app.include_router(static_assets.router)
    app.dependency_overrides[get_current_account] = lambda: admin_account
    app.dependency_overrides[require_admin] = lambda: admin_account
    return TestClient(app)


def test_list_returns_only_builtin_haru(client):
    response = client.get("/api/v1/avatar/mascots")

    assert response.status_code == 200
    mascots = response.json()["mascots"]
    assert [m["mascot_id"] for m in mascots] == ["haru-live2d"]
    assert mascots[0]["engine"] == "2d"
    assert mascots[0]["builtin"] is True
    assert mascots[0]["model_url"].endswith(".model3.json")


def test_list_ignores_other_registered_mascot_resources(client, runtime):
    from app.auth.models import ResourceType

    # 舊環境可能還留著上傳 VRM 或影片小助理的資源列；它們沒有檔案也沒有引擎，不能列出。
    runtime.resources.upsert_system_resource(
        resource_type=ResourceType.AVATAR_MASCOT,
        resource_id="custom-vrm",
        metadata={"label": "Custom"},
    )

    mascots = client.get("/api/v1/avatar/mascots").json()["mascots"]

    assert [m["mascot_id"] for m in mascots] == ["haru-live2d"]
    assert {m["engine"] for m in mascots} == {"2d"}


@pytest.mark.parametrize(
    ("method", "path"),
    [
        ("POST", "/api/v1/avatar/mascots/from-character"),
        ("PATCH", "/api/v1/avatar/mascots/haru-live2d"),
        ("DELETE", "/api/v1/avatar/mascots/haru-live2d"),
        ("POST", "/api/v1/avatar/mascots/haru-live2d/thumbnail"),
        ("GET", "/static/mascots/haru-live2d/thumbnail.png"),
        ("GET", "/static/mascots/video-0713/thumbnail.png"),
        ("GET", "/static/mascots/custom/model.vrm"),
    ],
)
def test_mascot_mutation_and_file_routes_are_gone(client, method, path):
    assert client.request(method, path).status_code == 404


def test_mascot_collection_no_longer_accepts_uploads(client):
    # 集合路徑只剩 GET，上傳會被當成不支援的方法。
    assert client.post("/api/v1/avatar/mascots").status_code == 405
