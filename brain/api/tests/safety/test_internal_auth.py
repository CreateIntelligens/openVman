from types import SimpleNamespace

import pytest
from fastapi import HTTPException

from safety import internal_auth


@pytest.fixture(autouse=True)
def _settings(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        internal_auth,
        "get_settings",
        lambda: SimpleNamespace(gateway_internal_token="internal-secret"),
    )


def test_require_internal_token_accepts_configured_secret() -> None:
    internal_auth.require_internal_token("internal-secret")


def test_require_internal_token_rejects_missing_or_wrong_secret() -> None:
    for token in ("", "wrong"):
        with pytest.raises(HTTPException) as exc_info:
            internal_auth.require_internal_token(token)
        assert exc_info.value.status_code == 403


def test_trusted_context_requires_identity_headers() -> None:
    with pytest.raises(HTTPException) as exc_info:
        internal_auth.trusted_request_context("internal-secret", "", "user", "default")
    assert exc_info.value.status_code == 403


def test_trusted_context_returns_verified_identity() -> None:
    context = internal_auth.trusted_request_context(
        "internal-secret",
        "user-1",
        "user",
        "project-1",
    )

    # 未帶主體標頭時退回帳號主體，帳本欄位才不會是空字串。
    assert context == internal_auth.TrustedRequestContext(
        user_id="user-1",
        role="user",
        project_id="project-1",
        principal_type="user",
        principal_id="user-1",
    )


def test_trusted_context_keeps_an_embed_principal() -> None:
    context = internal_auth.trusted_request_context(
        "internal-secret",
        "embed:ovk_abc",
        "user",
        "project-1",
        "embed_key",
        "ovk_abc",
    )

    assert context.principal_type == "embed_key"
    assert context.principal_id == "ovk_abc"
