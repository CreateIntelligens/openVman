"""由人物自動衍生的 video-<char_id> 小助理縮圖，照底下人物的權限提供。"""

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.auth.dependencies import AuthTransport, CurrentAccount, get_current_account
from app.auth.models import AccountRole, ResourceType, ResourceVisibility
from app.auth.passwords import hash_password
from app.auth.runtime import get_auth_runtime
from app.config import get_tts_config
from app.routes import static_assets as static_assets_routes

THUMBNAIL = b"\x89PNG-thumb"


@pytest.fixture
def setup(tmp_path, monkeypatch):
    monkeypatch.setenv("AVATAR_MASCOTS_DIR", str(tmp_path))
    get_tts_config.cache_clear()
    (tmp_path / "video-0616").mkdir()
    (tmp_path / "video-0616" / "thumbnail.png").write_bytes(THUMBNAIL)
    (tmp_path / "video-0616" / "notes.txt").write_bytes(b"x")

    runtime = get_auth_runtime()
    owner = runtime.users.create(
        username="derived-owner",
        password_hash=hash_password("owner-password"),
        role=AccountRole.USER,
    )
    stranger = runtime.users.create(
        username="derived-stranger",
        password_hash=hash_password("stranger-password"),
        role=AccountRole.USER,
    )
    runtime.resources.register(
        resource_type=ResourceType.AVATAR_CHARACTER,
        resource_id="0616",
        owner_user_id=owner.id,
        visibility=ResourceVisibility.PRIVATE,
    )

    holder = {"current": CurrentAccount(user=owner, transport=AuthTransport.BEARER)}
    app = FastAPI()
    app.dependency_overrides[get_current_account] = lambda: holder["current"]
    app.include_router(static_assets_routes.router)

    def act_as(user):
        holder["current"] = CurrentAccount(user=user, transport=AuthTransport.BEARER)

    yield TestClient(app), act_as, owner, stranger
    get_tts_config.cache_clear()


def test_character_reader_gets_derived_mascot_thumbnail(setup):
    client, act_as, owner, _ = setup
    act_as(owner)

    response = client.get("/static/mascots/video-0616/thumbnail.png")

    assert response.status_code == 200
    assert response.content == THUMBNAIL


def test_derived_mascot_thumbnail_is_404_without_character_access(setup):
    client, act_as, _, stranger = setup
    act_as(stranger)

    assert client.get("/static/mascots/video-0616/thumbnail.png").status_code == 404


def test_derived_mascot_only_serves_the_thumbnail(setup):
    client, act_as, owner, _ = setup
    act_as(owner)

    assert client.get("/static/mascots/video-0616/notes.txt").status_code == 404


def test_derived_mascot_for_unregistered_character_is_404(setup, tmp_path):
    client, act_as, owner, _ = setup
    (tmp_path / "video-ghost").mkdir()
    (tmp_path / "video-ghost" / "thumbnail.png").write_bytes(THUMBNAIL)
    act_as(owner)

    assert client.get("/static/mascots/video-ghost/thumbnail.png").status_code == 404


def test_registered_mascot_with_video_prefix_keeps_mascot_check(setup, tmp_path):
    # 用 from-character 建立、有登錄成小助理資源的項目，照小助理資源判斷。
    client, act_as, owner, stranger = setup
    (tmp_path / "video-kiosk").mkdir()
    (tmp_path / "video-kiosk" / "thumbnail.png").write_bytes(THUMBNAIL)
    get_auth_runtime().resources.register(
        resource_type=ResourceType.AVATAR_MASCOT,
        resource_id="video-kiosk",
        owner_user_id=owner.id,
        visibility=ResourceVisibility.PRIVATE,
    )

    act_as(owner)
    assert client.get("/static/mascots/video-kiosk/thumbnail.png").status_code == 200
    act_as(stranger)
    assert client.get("/static/mascots/video-kiosk/thumbnail.png").status_code == 403
