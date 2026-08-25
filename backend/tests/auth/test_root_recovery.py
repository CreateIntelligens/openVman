"""Container-local ROOT password recovery safety tests."""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

from app.auth.models import AccountRole
from app.auth.passwords import hash_password, verify_password
from app.auth.runtime import AuthRuntime, build_auth_runtime
from app.config import TTSRouterConfig
from app.scripts import recover_root_password


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


def test_operator_recovery_updates_only_existing_root_and_prints_no_secret(
    runtime: AuthRuntime,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
):
    original = runtime.users.create_root(
        username="ai360",
        password_hash=hash_password("original-password"),
    )
    old_token = runtime.tokens.issue(original)
    replacement = "operator-replacement-password"
    monkeypatch.setattr(recover_root_password, "get_auth_runtime", lambda: runtime)
    monkeypatch.setattr(sys, "argv", ["recover-root-password"])
    monkeypatch.setenv("ROOT_RECOVERY_PASSWORD", replacement)

    result = recover_root_password.main()

    output = capsys.readouterr()
    assert result == 0
    assert replacement not in output.out
    assert replacement not in output.err
    assert "$2" not in output.out
    assert "$2" not in output.err
    recovered = runtime.users.get_by_id(original.id)
    assert recovered is not None
    assert recovered.id == original.id
    assert recovered.username == "ai360"
    assert recovered.role is AccountRole.ROOT
    assert recovered.token_version == original.token_version + 1
    assert verify_password(replacement, recovered.password_hash) is True
    assert runtime.users.list() == [recovered]
    assert runtime.tokens.decode(old_token).token_version == original.token_version
    event = runtime.auth_audit.list()[-1]
    assert event.action == "root_password_recovered"
    assert event.actor_user_id is None
    assert event.target_user_id == original.id
    assert event.metadata_json == "{}"


def test_operator_recovery_cannot_create_or_replace_missing_root(
    runtime: AuthRuntime,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
):
    monkeypatch.setattr(recover_root_password, "get_auth_runtime", lambda: runtime)
    monkeypatch.setattr(sys, "argv", ["recover-root-password"])
    monkeypatch.setenv("ROOT_RECOVERY_PASSWORD", "replacement-password")

    result = recover_root_password.main()

    output = capsys.readouterr()
    assert result == 1
    assert "exactly one ROOT account is required" in output.err
    assert runtime.users.list() == []
