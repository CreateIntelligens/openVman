"""共用技能在後台唯讀，只有 ROOT 能啟用／停用。

正式環境的共用技能目錄是唯讀掛載，內容要改 repo 再部署；開關會影響每個專案，
專案編輯權不夠。
"""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from starlette.requests import Request

from app.auth.dependencies import AuthTransport, CurrentAccount, get_current_account
from app.auth.models import AccountRole, AccountType, UserRecord
from tests.api.test_brain_proxy import _make_response, _mock_cfg

_PROJECT = "project-a"
_READ_ONLY = {
    "detail": "共用技能套用到所有專案，內容要更新系統才能改，後台只能查看；最高管理員可以啟用或停用",
}
_TOGGLE_ROOT_ONLY = {"detail": "共用技能會套用到所有專案，只有最高管理員可以啟用或停用"}


def _account(role: AccountRole, *, embed_key: Any = None) -> CurrentAccount:
    return CurrentAccount(
        user=UserRecord(
            id=f"{role.value}-user",
            username=f"{role.value}-user",
            username_normalized=f"{role.value}-user",
            password_hash="hash",
            role=role,
            account_type=AccountType.FORMAL,
            disabled=False,
            token_version=0,
            created_at="2026-11-18T00:00:00+00:00",
            updated_at="2026-11-18T00:00:00+00:00",
            created_by=None,
            admin_portal_access=True,
        ),
        transport=AuthTransport.EMBED_KEY if embed_key else AuthTransport.BEARER,
        embed_key=embed_key,
    )


@contextmanager
def _proxy(current: CurrentAccount, *, granted: bool = True) -> Iterator[tuple[TestClient, MagicMock]]:
    from app.brain_proxy import _catchall_current_account, router

    app = FastAPI()
    app.include_router(router)

    def current_account(request: Request) -> CurrentAccount:
        request.state.current_account = current
        return current

    app.dependency_overrides[get_current_account] = current_account
    app.dependency_overrides[_catchall_current_account] = current_account
    runtime = MagicMock()
    # 專案由別人擁有，一般帳號靠授權取得編輯權。
    runtime.resources.get.return_value = MagicMock(owner_user_id="someone-else")
    runtime.resources.has_grant.return_value = granted
    upstream = MagicMock()
    upstream.build_request.return_value = "request"
    upstream.send = AsyncMock(side_effect=lambda *_a, **_k: _make_response())

    with (
        patch("app.auth.brain_project_access.get_auth_runtime", return_value=runtime),
        patch("app.brain_proxy.get_tts_config", return_value=_mock_cfg()),
        patch("app.brain_proxy._http.get", return_value=upstream),
        TestClient(app) as client,
    ):
        yield client, upstream


_FILES = {"files": {"skill.yaml": "name: joke"}}

# (method, url, request kwargs)。每一筆都會改到共用技能的內容，或在 Brain 端可能落到共用技能。
_SHARED_CONTENT_WRITES: dict[str, tuple[str, str, dict[str, Any]]] = {
    "update files": ("PUT", f"/api/v1/skills/joke/files?scope=shared&project_id={_PROJECT}", {"json": _FILES}),
    "delete": ("DELETE", f"/api/v1/skills/joke?scope=shared&project_id={_PROJECT}", {}),
    "create shared": (
        "POST",
        f"/api/v1/skills?project_id={_PROJECT}",
        {"json": {"skill_id": "new", "name": "New", "scope": "shared"}},
    ),
    # 沒帶 scope：Brain 在專案沒有同名技能時會改用共用技能。
    "update files without scope": ("PUT", f"/api/v1/skills/joke/files?project_id={_PROJECT}", {"json": _FILES}),
    "delete without scope": ("DELETE", f"/api/v1/skills/joke?project_id={_PROJECT}", {}),
    "empty scope": ("PUT", f"/api/v1/skills/joke/files?scope=&project_id={_PROJECT}", {"json": _FILES}),
    "differently cased scope": ("DELETE", f"/api/v1/skills/joke?scope=Project&project_id={_PROJECT}", {}),
    "project then shared scope": (
        "PUT",
        f"/api/v1/skills/joke/files?scope=project&scope=shared&project_id={_PROJECT}",
        {"json": _FILES},
    ),
    # 建立技能時 Brain 只看 body 的 scope，沒寫就是 shared。
    "create without scope": (
        "POST",
        f"/api/v1/skills?project_id={_PROJECT}",
        {"json": {"skill_id": "new", "name": "New"}},
    ),
    "create with project scope only in query": (
        "POST",
        f"/api/v1/skills?scope=project&project_id={_PROJECT}",
        {"json": {"skill_id": "new", "name": "New", "scope": "shared", "project_id": _PROJECT}},
    ),
    "create shared without content type": (
        "POST",
        f"/api/v1/skills?project_id={_PROJECT}",
        {"content": b'{"skill_id": "new", "name": "New", "scope": "shared"}'},
    ),
    "create with unparsable body": ("POST", f"/api/v1/skills?project_id={_PROJECT}", {"content": b"scope=project"}),
}

_SHARED_TOGGLES: dict[str, tuple[str, str, dict[str, Any]]] = {
    "toggle": ("PATCH", f"/api/v1/skills/joke/toggle?scope=shared&project_id={_PROJECT}", {}),
    "toggle without scope": ("PATCH", f"/api/v1/skills/joke/toggle?project_id={_PROJECT}", {}),
    "toggle with empty scope": ("PATCH", f"/api/v1/skills/joke/toggle?scope=&project_id={_PROJECT}", {}),
    "project then shared scope": (
        "PATCH",
        f"/api/v1/skills/joke/toggle?scope=project&scope=shared&project_id={_PROJECT}",
        {},
    ),
    "shared then project scope": (
        "PATCH",
        f"/api/v1/skills/joke/toggle?scope=shared&scope=project&project_id={_PROJECT}",
        {},
    ),
}


@pytest.mark.parametrize("case", sorted(_SHARED_CONTENT_WRITES))
@pytest.mark.parametrize("role", [AccountRole.ROOT, AccountRole.ADMIN, AccountRole.USER])
def test_nobody_can_change_shared_skill_content(case: str, role: AccountRole) -> None:
    method, url, kwargs = _SHARED_CONTENT_WRITES[case]
    with _proxy(_account(role)) as (client, upstream):
        response = client.request(method, url, **kwargs)

    assert response.status_code == 403
    assert response.json() == _READ_ONLY
    upstream.send.assert_not_awaited()


@pytest.mark.parametrize("case", sorted(_SHARED_TOGGLES))
@pytest.mark.parametrize("role", [AccountRole.ADMIN, AccountRole.USER])
def test_non_root_cannot_toggle_shared_skills(case: str, role: AccountRole) -> None:
    method, url, kwargs = _SHARED_TOGGLES[case]
    with _proxy(_account(role)) as (client, upstream):
        response = client.request(method, url, **kwargs)

    assert response.status_code == 403
    assert response.json() == _TOGGLE_ROOT_ONLY
    upstream.send.assert_not_awaited()


@pytest.mark.parametrize("case", sorted(_SHARED_TOGGLES))
def test_root_toggles_only_with_one_explicit_shared_scope(case: str) -> None:
    # 沒寫或重複的 scope 會被當成共用放行，但 Brain 會先找同名專案技能、或取最後一個值：
    # 放行的對象跟實際切換的可能不是同一個，所以 ROOT 也要明寫 scope=shared。
    method, url, kwargs = _SHARED_TOGGLES[case]
    with _proxy(_account(AccountRole.ROOT)) as (client, upstream):
        response = client.request(method, url, **kwargs)

    if case == "toggle":
        assert response.status_code == 200
        upstream.send.assert_awaited_once()
    else:
        assert response.status_code == 422
        upstream.send.assert_not_awaited()


def test_embed_key_cannot_write_shared_skills_even_for_a_root_owner() -> None:
    embed_key = MagicMock(project_id=_PROJECT, key_id="embed-1")
    method, url, kwargs = _SHARED_TOGGLES["toggle"]
    with (
        patch("app.auth.brain_project_access.enforce_project_binding"),
        _proxy(_account(AccountRole.ROOT, embed_key=embed_key)) as (client, upstream),
    ):
        response = client.request(method, url, **kwargs)

    assert response.status_code == 403
    upstream.send.assert_not_awaited()


def test_missing_account_cannot_write_shared_skills() -> None:
    from app.skill_write_guard import skill_request_refusal

    request = Request(
        {
            "type": "http",
            "method": "PATCH",
            "path": "/api/v1/skills/joke/toggle",
            "query_string": b"scope=shared",
            "headers": [],
        }
    )
    refusal = skill_request_refusal(request, "skills/joke/toggle", b"", None, None)

    assert refusal is not None
    assert refusal.status_code == 403


_PROJECT_WRITES: dict[str, tuple[str, str, dict[str, Any]]] = {
    "update files": ("PUT", f"/api/v1/skills/joke/files?scope=project&project_id={_PROJECT}", {"json": _FILES}),
    "toggle": ("PATCH", f"/api/v1/skills/joke/toggle?scope=project&project_id={_PROJECT}", {}),
    "delete": ("DELETE", f"/api/v1/skills/joke?scope=project&project_id={_PROJECT}", {}),
    "create": (
        "POST",
        "/api/v1/skills",
        {"json": {"skill_id": "new", "name": "New", "scope": "project", "project_id": _PROJECT}},
    ),
    "reload": ("POST", f"/api/v1/skills/reload?project_id={_PROJECT}", {"json": {}}),
}


@pytest.mark.parametrize("case", sorted(_PROJECT_WRITES))
@pytest.mark.parametrize(("granted", "expected_status"), [(True, 200), (False, 404)])
def test_project_skill_writes_keep_project_edit_rules(
    case: str, granted: bool, expected_status: int,
) -> None:
    method, url, kwargs = _PROJECT_WRITES[case]
    with _proxy(_account(AccountRole.USER), granted=granted) as (client, upstream):
        response = client.request(method, url, **kwargs)

    assert response.status_code == expected_status
    assert upstream.send.await_count == (1 if granted else 0)


def test_project_create_cannot_target_another_project_through_an_untyped_body() -> None:
    # 沒有 Content-Type 時授權只看得到 query 的專案，Brain 卻會照 body 的專案建立。
    with _proxy(_account(AccountRole.USER)) as (client, upstream):
        response = client.post(
            f"/api/v1/skills?project_id={_PROJECT}",
            content=b'{"skill_id": "new", "name": "New", "scope": "project", "project_id": "project-b"}',
        )

    assert response.status_code == 422
    upstream.send.assert_not_awaited()


def test_non_root_can_still_read_shared_skill_files() -> None:
    with _proxy(_account(AccountRole.USER)) as (client, upstream):
        response = client.get(f"/api/v1/skills/joke/files?scope=shared&project_id={_PROJECT}")

    assert response.status_code == 200
    upstream.send.assert_awaited_once()


def test_openapi_documents_the_shared_skill_refusals() -> None:
    from app.brain_proxy import router

    app = FastAPI()
    app.include_router(router)
    paths = app.openapi()["paths"]

    assert "403" in paths["/api/v1/skills/{skill_id}/files"]["put"]["responses"]
    assert "403" in paths["/api/v1/skills"]["post"]["responses"]
    assert "403" in paths["/api/v1/skills/{skill_id}/toggle"]["patch"]["responses"]
    assert "403" not in paths["/api/v1/skills/{skill_id}/files"]["get"]["responses"]
    assert "403" not in paths["/api/v1/skills/reload"]["post"]["responses"]


@pytest.mark.parametrize(
    ("url", "expected_target"),
    [
        # 解碼後的 ? 與 # 要以字面送到 Brain，不能在上游網址切出另一組 query
        # （授權看到 scope=project，Brain 卻收到 shared）。技能 ID 本身也不合法。
        (f"/api/v1/skills/joke%3Fscope=shared%23?scope=project&project_id={_PROJECT}", None),
        (f"/api/v1/skills/joke%23?scope=project&project_id={_PROJECT}", None),
        (
            f"/api/v1/knowledge/document%3Fproject_id=project-b%23?project_id={_PROJECT}",
            "http://brain:8100/brain/knowledge/document%3Fproject_id%3Dproject-b%23"
            f"?project_id={_PROJECT}",
        ),
    ],
)
def test_query_cannot_be_smuggled_through_an_encoded_path(
    url: str, expected_target: str | None,
) -> None:
    with _proxy(_account(AccountRole.ADMIN)) as (client, upstream):
        response = client.request("PUT", url, json={})

    if expected_target is None:
        assert response.status_code == 422
        upstream.send.assert_not_awaited()
    else:
        assert upstream.build_request.call_args.kwargs["url"] == expected_target


@pytest.mark.parametrize(
    ("method", "url", "kwargs"),
    [
        ("GET", f"/api/v1/skills/bad-id/files?scope=project&project_id={_PROJECT}", {}),
        ("DELETE", f"/api/v1/skills/9lives?scope=project&project_id={_PROJECT}", {}),
        (
            "POST",
            "/api/v1/skills",
            {"json": {"skill_id": "../../evil", "name": "x", "scope": "project", "project_id": _PROJECT}},
        ),
        (
            "POST",
            f"/api/v1/skills?project_id={_PROJECT}",
            {"content": b'{"skill_id": "a/b", "name": "x", "scope": "project"}'},
        ),
    ],
)
def test_skill_ids_must_be_safe_names(method: str, url: str, kwargs: dict[str, Any]) -> None:
    # 技能 ID 會變成 Brain 上的目錄與 Python 函式名稱。
    with _proxy(_account(AccountRole.ROOT)) as (client, upstream):
        response = client.request(method, url, **kwargs)

    assert response.status_code == 422
    upstream.send.assert_not_awaited()


def test_project_skill_write_reaches_brain_with_the_authorized_query() -> None:
    with _proxy(_account(AccountRole.USER)) as (client, upstream):
        client.delete(f"/api/v1/skills/joke?scope=project&project_id={_PROJECT}")

    target = upstream.build_request.call_args.kwargs["url"]
    assert target == f"http://brain:8100/brain/skills/joke?scope=project&project_id={_PROJECT}"


def test_shared_refusal_comes_before_the_skill_id_check() -> None:
    # 沒權限的人先知道「共用技能不能改」，不必先猜對 ID 格式。
    with _proxy(_account(AccountRole.ADMIN)) as (client, upstream):
        response = client.put(
            f"/api/v1/skills/bad-id/files?scope=shared&project_id={_PROJECT}", json=_FILES,
        )

    assert response.status_code == 403
    assert response.json() == _READ_ONLY
    upstream.send.assert_not_awaited()
