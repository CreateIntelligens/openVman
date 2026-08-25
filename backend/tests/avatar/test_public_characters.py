import io

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.auth.dependencies import (
    AuthTransport,
    CurrentAccount,
    get_current_account,
    require_admin,
)
from app.auth.middleware import is_public_path
from app.auth.models import AccountRole, ResourceType, ResourceVisibility
from app.auth.passwords import hash_password
from app.auth.runtime import get_auth_runtime
from app.config import get_tts_config
from app.routes import avatar as avatar_routes
from app.routes import public_characters as public_characters_routes
from app.routes import static_assets as static_assets_routes


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setenv("AVATAR_ASSETS_DIR", str(tmp_path))

    get_tts_config.cache_clear()
    avatar_routes.reset_store()
    public_characters_routes.reset_store()
    monkeypatch.setattr(avatar_routes, "_personas_bound_to", lambda char_id: [])

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
    app.include_router(public_characters_routes.router)
    app.include_router(static_assets_routes.router)
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
    asset_response = client.get("/assets/008/01.webm")

    assert response.status_code == 200
    assert response.json() == {
        "characters": [{"char_id": "008", "label": "角色八"}]
    }
    assert asset_response.status_code == 200
    assert asset_response.content == b"\x1a\x45\xdf\xa3v"
    assert asset_response.headers["cache-control"] == "public, max-age=3600"


def test_list_excludes_incomplete_characters(tmp_path, client):
    (tmp_path / "001").mkdir()
    (tmp_path / "001" / "01.webm").write_bytes(b"x")
    get_auth_runtime().resources.register(
        resource_type=ResourceType.AVATAR_CHARACTER,
        resource_id="001",
        owner_user_id=None,
        visibility=ResourceVisibility.SYSTEM_PUBLIC,
    )

    response = client.get("/characters")

    assert response.json() == {"characters": []}


def test_private_character_is_not_public_but_owner_and_grantee_can_read(
    client,
):
    store = public_characters_routes.get_store()
    store.create_character(
        char_id="private",
        label="私有角色",
        video_bytes=b"private-video",
        data_bytes=b"private-data",
    )

    runtime = get_auth_runtime()
    owner = runtime.users.create(
        username="owner",
        password_hash=hash_password("owner-password"),
        role=AccountRole.USER,
    )
    grantee = runtime.users.create(
        username="grantee",
        password_hash=hash_password("grantee-password"),
        role=AccountRole.USER,
    )
    runtime.resources.register(
        resource_type=ResourceType.AVATAR_CHARACTER,
        resource_id="private",
        owner_user_id=owner.id,
        visibility=ResourceVisibility.PRIVATE,
    )
    with runtime.database.transaction(write=True) as connection:
        connection.execute(
            """
            INSERT INTO resource_grants(
                grantee_user_id, resource_type, resource_id,
                granted_by, created_at
            ) VALUES (?, ?, ?, ?, ?)
            """,
            (
                grantee.id,
                ResourceType.AVATAR_CHARACTER.value,
                "private",
                owner.id,
                "2026-08-24T00:00:00+00:00",
            ),
        )

    assert client.get("/characters").json() == {"characters": []}
    assert client.get("/assets/private/01.webm").status_code == 404

    for account in (owner, grantee):
        response = client.get(
            "/assets/private/01.webm",
            headers={"Authorization": f"Bearer {runtime.tokens.issue(account)}"},
        )
        assert response.status_code == 200
        assert response.content == b"private-video"
        assert response.headers["cache-control"] == "private, no-store"


def test_unregistered_character_is_not_listed_or_publicly_readable(client):
    public_characters_routes.get_store().create_character(
        char_id="unregistered",
        label="未登記角色",
        video_bytes=b"unregistered-video",
        data_bytes=b"unregistered-data",
    )

    assert client.get("/characters").json() == {"characters": []}
    assert client.get("/assets/unregistered/01.webm").status_code == 404

    runtime = get_auth_runtime()
    admin = runtime.users.get_by_username("admin")
    assert admin is not None
    authenticated_response = client.get(
        "/assets/unregistered/01.webm",
        headers={"Authorization": f"Bearer {runtime.tokens.issue(admin)}"},
    )
    assert authenticated_response.status_code == 404


def test_character_asset_path_bypasses_middleware_for_route_level_policy():
    assert is_public_path("/assets/008/01.webm") is True


def test_list_excludes_in_progress_upload_tempdirs(tmp_path, client):
    (tmp_path / ".002.tmp.abc").mkdir()

    response = client.get("/characters")

    assert response.json() == {"characters": []}
