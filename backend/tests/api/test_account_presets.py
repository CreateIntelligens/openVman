"""Account preset and web-search settings through authenticated API routes."""

import pytest

from app.auth.models import ResourceType
from tests.api.test_vendor_access import (
    _OTHER,
    _PROJECT,
    _UNGRANTED,
    _assign_vendors,
)
from tests.api.test_vendor_access import env as env


@pytest.mark.parametrize(
    ("preset", "projects", "vendor", "role", "manager", "web_search"),
    [
        ("rd", [], None, "admin", True, True),
        ("bd", [_PROJECT], None, "user", False, True),
        ("bd", [], None, "user", False, True),
        ("vendor_editor", [_PROJECT], "甲商", "user", False, False),
    ],
)
def test_presets_create_expected_accounts_and_project_grants(
    env, preset, projects, vendor, role, manager, web_search,
):
    _assign_vendors(env)
    created = env.create(
        "preset-account", preset=preset, project_ids=projects, vendor_name=vendor,
    )
    assert created.status_code == 201, created.text
    account = created.json()
    assert account["preset"] == preset
    assert account["role"] == role
    assert account["admin_portal_access"] is True
    assert account.get("account_management_access", False) is manager
    assert account["vendor_name"] == vendor
    assert account["web_search_access"] is web_search
    assert account["ai_cleanup_access"] is manager
    assert account["defaults"] is None
    assert (account["grants"] or {}).get("project_permissions", {}) == {
        project: {"edit_knowledge": True, "edit_settings": False} for project in projects
    }
    reply = env.client.get("/api/v1/users", headers=env.headers(env.root.id))
    assert reply.status_code == 200
    assert next(item for item in reply.json() if item["id"] == account["id"]) == account
    if vendor:
        headers = env.headers(account["id"])
        assert env.client.get("/api/v1/auth/admin-me", headers=headers).status_code == 200
        assert env.client.put(
            "/api/v1/knowledge/settings", headers=headers,
            json={"project_id": _PROJECT, "reply_seconds": 20},
        ).status_code == 200


@pytest.mark.parametrize(
    ("fields", "expected", "message"),
    [
        ({"preset": "vendor_editor", "project_ids": [_PROJECT]}, 400, "必須填寫所屬廠商"),
        ({"preset": "vendor_editor", "vendor_name": "  ", "project_ids": [_PROJECT]},
         400, "必須填寫所屬廠商"),
        ({"preset": "vendor_editor", "vendor_name": "甲商"}, 400, "至少選擇一個知識庫"),
        ({"preset": "bd", "vendor_name": "甲商"}, 400, "不可填寫所屬廠商"),
        ({"preset": "rd", "vendor_name": "甲商"}, 400, "不可填寫所屬廠商"),
        ({"preset": "vendor_editor", "vendor_name": "甲商", "project_ids": [_PROJECT, _OTHER]},
         422, "帳號與專案的所屬廠商必須相同"),
    ],
)
def test_invalid_presets_leave_no_account_or_grants(env, fields, expected, message):
    _assign_vendors(env)
    created = env.create("invalid-preset-account", **fields)
    assert created.status_code == expected, created.text
    assert message in created.json()["detail"]
    assert env.runtime.users.get_by_username("invalid-preset-account") is None


def test_preset_creation_respects_account_management_and_grant_scope(env):
    manager_path = f"/api/v1/users/{env.admin.id}/account-management"
    root_headers = env.headers(env.root.id)
    assert env.create("no-manager", actor_id=env.admin.id, preset="bd").status_code == 403
    assert env.client.patch(
        manager_path, headers=root_headers, json={"enabled": True},
    ).status_code == 200
    assert env.create("no-root", actor_id=env.admin.id, preset="rd").status_code == 403
    # BD 會開網路搜尋，建立者自己要有。
    no_web = env.create("no-web-search", actor_id=env.admin.id, preset="bd")
    assert no_web.status_code == 403, no_web.text
    assert env.runtime.users.get_by_username("no-web-search") is None
    assert env.client.put(
        f"/api/v1/users/{env.admin.id}/access", headers=root_headers,
        json={"web_search_access": True},
    ).status_code == 200
    env.runtime.admin_scopes.replace(
        admin_user_id=env.admin.id, updated_by=env.root.id, scoped=True,
        resources=[(ResourceType.PROJECT, _PROJECT)],
    )
    blocked = env.create(
        "outside-scope", actor_id=env.admin.id, preset="bd", project_ids=[_PROJECT, _UNGRANTED],
    )
    assert blocked.status_code == 422, blocked.text
    assert env.runtime.users.get_by_username("outside-scope") is None
    created = env.create(
        "within-scope", actor_id=env.admin.id, preset="bd", project_ids=[_PROJECT],
    )
    assert created.status_code == 201, created.text


def test_account_preset_catalog_requires_account_management(env):
    vendor = env.create("vendor", vendor_name="甲商").json()
    path = "/api/v1/admin/account-presets"
    for user_id in (vendor["id"], env.admin.id):
        assert env.client.get(path, headers=env.headers(user_id)).status_code == 403
    reply = env.client.get(path, headers=env.headers(env.root.id))
    assert reply.status_code == 200, reply.text
    assert [(item["key"], item["label"]) for item in reply.json()] == [
        ("rd", "創智研發"), ("bd", "BD"), ("vendor_editor", "廠商編輯"),
    ]
    assert env.client.patch(
        f"/api/v1/users/{env.admin.id}/account-management",
        headers=env.headers(env.root.id), json={"enabled": True},
    ).status_code == 200
    assert env.client.get(path, headers=env.headers(env.admin.id)).json() == reply.json()


def test_account_preset_is_rederived_after_web_search_change(env):
    _assign_vendors(env)
    account = env.create(
        "vendor-with-web-search", preset="vendor_editor", vendor_name="甲商", project_ids=[_PROJECT],
    ).json()
    updated = env.client.put(
        f"/api/v1/users/{account['id']}/access",
        headers=env.headers(env.root.id),
        json={"web_search_access": True},
    )
    assert updated.status_code == 200, updated.text
    assert updated.json()["preset"] is None
    assert updated.json()["preset_label"] is None
    assert updated.json()["web_search_access"] is True
    assert updated.json()["grants"] == account["grants"]
    assert updated.json()["admin_portal_access"] is True
    for profile_path in ("me", "admin-me"):
        profile = env.client.get(
            f"/api/v1/auth/{profile_path}", headers=env.headers(account["id"]),
        )
        assert profile.status_code == 200, profile.text
        assert "web_search_access" not in profile.json()


@pytest.mark.parametrize(
    ("principal", "expected"),
    [("vendor-session", "0"), ("embed-key", "0"), ("api-key", "0"), ("internal-session", "1")],
)
def test_chat_proxies_web_search_access_from_authenticated_principal(env, principal, expected):
    _assign_vendors(env)
    root_headers = env.headers(env.root.id)
    if principal == "embed-key":
        key = env.runtime.embed_keys.create(
            label="embed", project_id=_PROJECT, allowed_origins=["https://partner.example"],
        )
        headers = {"X-Embed-Key": key.key_id, "Origin": "https://partner.example"}
    else:
        if principal == "internal-session":
            created = env.create("chat-account", preset="bd", project_ids=[_PROJECT])
        else:
            created = env.create(
                "chat-account", preset="vendor_editor", vendor_name="甲商", project_ids=[_PROJECT],
            )
        assert created.status_code == 201, created.text
        account = created.json()
        if principal == "api-key":
            issued = env.client.post(
                "/api/v1/api-keys", headers=root_headers,
                json={"label": "chat", "user_id": account["id"]},
            )
            assert issued.status_code == 201, issued.text
            headers = {"Authorization": f"Bearer {issued.json()['key']}"}
        else:
            headers = env.headers(account["id"])

    response = env.client.post(
        "/api/v1/chat",
        headers={**headers, "X-OpenVMan-Web-Search": "1" if expected == "0" else "0"},
        json={"message": "今天天氣如何？", "project_id": _PROJECT},
    )
    assert response.status_code == 200, response.text
    assert env.received[-1].headers.get_list("X-OpenVMan-Web-Search") == [expected]


def test_web_search_cannot_be_delegated_by_an_admin_without_it(env):
    root_headers = env.headers(env.root.id)
    admin_headers = env.headers(env.admin.id)

    blocked = env.create(
        "child-admin", actor_id=env.admin.id, role="admin",
        access={"web_search_access": True},
    )
    assert blocked.status_code == 403, blocked.text
    assert env.runtime.users.get_by_username("child-admin") is None

    child = env.create("child-user", actor_id=env.admin.id).json()
    updated = env.client.put(
        f"/api/v1/users/{child['id']}/access", headers=admin_headers,
        json={"web_search_access": True},
    )
    assert updated.status_code == 403, updated.text
    assert env.runtime.users.get_by_id(child["id"]).web_search_access is False

    assert env.client.put(
        f"/api/v1/users/{env.admin.id}/access", headers=root_headers,
        json={"web_search_access": True},
    ).status_code == 200
    allowed = env.client.put(
        f"/api/v1/users/{child['id']}/access", headers=env.headers(env.admin.id),
        json={"web_search_access": True},
    )
    assert allowed.status_code == 200, allowed.text


def test_root_can_always_search_the_web_on_a_fresh_install(env):
    from app.auth.models import has_web_search_access

    root = env.runtime.users.get_by_id(env.root.id)
    assert root.web_search_access is True
    assert has_web_search_access(root)


def test_becoming_a_vendor_account_turns_web_search_off(env):
    _assign_vendors(env)
    account = env.create("internal-bd", preset="bd", project_ids=[_PROJECT]).json()
    assert account["web_search_access"] is True

    moved = env.client.patch(
        f"/api/v1/users/{account['id']}/vendor", headers=env.headers(env.root.id),
        json={"vendor_name": "甲商"},
    )
    assert moved.status_code == 200, moved.text
    assert moved.json()["web_search_access"] is False


def test_an_admin_without_web_search_can_resave_an_account_that_has_it(env):
    root_headers = env.headers(env.root.id)
    assert env.client.put(
        f"/api/v1/users/{env.admin.id}/access", headers=root_headers,
        json={"web_search_access": True},
    ).status_code == 200
    child = env.create(
        "child-with-web", actor_id=env.admin.id, access={"web_search_access": True},
    ).json()
    assert child["web_search_access"] is True
    assert env.client.put(
        f"/api/v1/users/{env.admin.id}/access", headers=root_headers,
        json={"web_search_access": False},
    ).status_code == 200

    resaved = env.client.put(
        f"/api/v1/users/{child['id']}/access", headers=env.headers(env.admin.id),
        json={"web_search_access": True},
    )
    assert resaved.status_code == 200, resaved.text
