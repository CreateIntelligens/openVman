"""API key usage preserves the key identity and the live owner separately."""

from types import SimpleNamespace

import pytest
from starlette.requests import Request

from app.auth.dependencies import AuthTransport, CurrentAccount
from app.auth.models import AccountRole
from app.brain_proxy import _trusted_upstream_headers
from app.usage_ledger_client import usage_scope_for


@pytest.mark.parametrize("key_id", ["key-a", "key-b"])
def test_api_key_proxy_and_media_scopes_preserve_owner(key_id):
    current = CurrentAccount(
        user=SimpleNamespace(id="owner-1", role=AccountRole.ADMIN),
        transport=AuthTransport.API_KEY,
        api_key=SimpleNamespace(key_id=key_id, user_id="owner-1"),
    )
    request = Request({
        "type": "http",
        "headers": [
            (b"x-principal-type", b"user"),
            (b"x-principal-id", b"root"),
            (b"x-openvman-user-id", b"root"),
            (b"authorization", b"Bearer never-forward-this"),
        ],
    })
    headers = _trusted_upstream_headers(
        request, current=current, project_id="project-1",
    )
    assert headers["X-Principal-Type"] == "api_key"
    assert headers["X-Principal-Id"] == key_id
    assert headers["X-OpenVMan-User-ID"] == "owner-1"
    assert headers["X-OpenVMan-Role"] == "admin"
    assert "authorization" not in {name.lower() for name in headers}

    scope = usage_scope_for(
        current, project_id="project-1", session_id="s1", channel="http",
    )
    assert scope == {
        "user_id": "owner-1",
        "role": "admin",
        "principal_type": "api_key",
        "principal_id": key_id,
        "project_id": "project-1",
        "session_id": "s1",
        "channel": "http",
    }


def test_session_usage_remains_an_account_principal():
    current = CurrentAccount(
        user=SimpleNamespace(id="owner-1", role=AccountRole.ADMIN),
        transport=AuthTransport.BEARER,
    )
    assert usage_scope_for(current)["principal_type"] == "user"
    assert usage_scope_for(current)["principal_id"] == "owner-1"
