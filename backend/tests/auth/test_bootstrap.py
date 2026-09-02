"""First-administrator bootstrap command tests."""

from __future__ import annotations

from pathlib import Path

import pytest

from app.auth.models import AccountRole
from app.auth.passwords import hash_password, verify_password
from app.auth.repositories import (
    AdminAlreadyExistsError,
    UsernameConflictError,
)
from app.auth.runtime import AuthRuntime, build_auth_runtime
from app.config import TTSRouterConfig
from app.scripts.create_user import bootstrap_admin


@pytest.fixture()
def runtime(tmp_path: Path) -> AuthRuntime:
    return build_auth_runtime(
        TTSRouterConfig(
            _env_file=None,
            env="dev",
            session_jwt_secret="test-only-session-secret-for-tests-32",
            auth_database_path=str(tmp_path / "accounts.db"),
        )
    )


def test_bootstrap_creates_only_the_ai360_root(runtime: AuthRuntime):
    created = bootstrap_admin(
        username="ai360",
        password="admin-password",
        runtime=runtime,
    )

    assert created.username == "ai360"
    assert created.role is AccountRole.ROOT
    assert created.disabled is False
    assert created.password_hash != "admin-password"

    with pytest.raises(AdminAlreadyExistsError, match="ROOT already exists"):
        bootstrap_admin(
            username="ai360",
            password="other-password",
            runtime=runtime,
        )

    with pytest.raises(ValueError, match="ROOT username must be ai360"):
        bootstrap_admin(
            username="replacement-root",
            password="other-password",
            runtime=runtime,
        )

    assert [(user.username, user.role) for user in runtime.users.list()] == [
        ("ai360", AccountRole.ROOT)
    ]


def test_bootstrap_accepts_the_deployment_default_admin(runtime: AuthRuntime):
    created = bootstrap_admin(
        username="ai360",
        password="ai360",
        runtime=runtime,
    )

    assert created.username == "ai360"
    assert created.role is AccountRole.ROOT
    assert verify_password("ai360", created.password_hash) is True


def test_bootstrap_fails_closed_when_ai360_already_exists(runtime: AuthRuntime):
    existing = runtime.users.create(
        username="ＡＩ360",
        password_hash=hash_password("existing-password"),
        role=AccountRole.USER,
    )

    with pytest.raises(UsernameConflictError, match="ai360 already exists"):
        bootstrap_admin(
            username="ai360",
            password="replacement-password",
            runtime=runtime,
        )

    unchanged = runtime.users.get_by_id(existing.id)
    assert unchanged is not None
    assert unchanged.role is AccountRole.USER
    assert unchanged.password_hash == existing.password_hash
