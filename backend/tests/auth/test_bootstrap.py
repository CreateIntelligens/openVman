"""First-administrator bootstrap command tests."""

from __future__ import annotations

from pathlib import Path

import pytest

from app.auth.repositories import AdminAlreadyExistsError
from app.auth.runtime import AuthRuntime, build_auth_runtime
from app.config import TTSRouterConfig
from app.scripts.create_user import bootstrap_admin


@pytest.fixture()
def runtime(tmp_path: Path) -> AuthRuntime:
    return build_auth_runtime(
        TTSRouterConfig(
            _env_file=None,
            env="dev",
            session_jwt_secret="test-only-session-secret",
            auth_database_path=str(tmp_path / "accounts.db"),
        )
    )


def test_bootstrap_creates_only_the_first_admin(runtime: AuthRuntime):
    created = bootstrap_admin(
        username="first-admin",
        password="admin-password",
        runtime=runtime,
    )

    assert created.role.value == "admin"
    assert created.disabled is False
    assert created.password_hash != "admin-password"

    with pytest.raises(AdminAlreadyExistsError, match="administrator already exists"):
        bootstrap_admin(
            username="replacement-admin",
            password="other-password",
            runtime=runtime,
        )

    assert [user.username for user in runtime.users.list()] == ["first-admin"]
