from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

from fastapi import FastAPI, Request
from fastapi.testclient import TestClient

from app.auth.dependencies import AuthTransport, CurrentAccount, get_current_account
from app.auth.models import AccountRole, AccountType, UserRecord
from app.auth.runtime import get_auth_runtime
from app.project_routes import router


def _portal_current() -> CurrentAccount:
    return CurrentAccount(
        user=UserRecord(
            id="portal-user",
            username="portal-user",
            username_normalized="portal-user",
            password_hash="hash",
            role=AccountRole.USER,
            account_type=AccountType.FORMAL,
            disabled=False,
            token_version=0,
            created_at="2026-09-01T00:00:00+00:00",
            updated_at="2026-09-01T00:00:00+00:00",
            created_by=None,
            admin_portal_access=True,
        ),
        transport=AuthTransport.BEARER,
    )


def test_portal_user_cannot_create_or_delete_projects() -> None:
    app = FastAPI()
    app.include_router(router)
    current = _portal_current()

    def current_account(request: Request) -> CurrentAccount:
        request.state.current_account = current
        return current

    app.dependency_overrides[get_current_account] = current_account
    app.dependency_overrides[get_auth_runtime] = MagicMock

    with (
        patch("app.project_routes.proxy_to_brain", new_callable=AsyncMock) as proxy,
        TestClient(app) as client,
    ):
        create_response = client.post("/api/projects", json={"label": "New"})
        delete_response = client.request(
            "DELETE",
            "/api/projects",
            json={"project_id": "project-a"},
        )

    assert create_response.status_code == 403
    assert delete_response.status_code == 403
    proxy.assert_not_awaited()
