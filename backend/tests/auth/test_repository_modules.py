"""Ownership contract for the account and registry repository modules."""

from __future__ import annotations

import inspect
import subprocess
import sys
import textwrap
from pathlib import Path

import pytest

from app import auth
from app.auth import (
    embed_keys_repository,
    repository_errors,
    settings_repository,
    temporary_accounts_repository,
)

_REPOSITORY_MODULES = [
    "_repository_base",
    "account_access_repository",
    "admin_scopes_repository",
    "auth_audit_repository",
    "embed_keys_repository",
    "repository_errors",
    "resource_repository",
    "temporary_accounts_repository",
    "user_repository",
]


def test_the_historical_reexport_shim_stays_deleted():
    # 呼叫端要直接從擁有者模組 import；shim 回來就又看不出誰擁有什麼。
    assert not Path(auth.__file__).with_name("repositories.py").exists()


def test_repository_errors_share_one_exception_hierarchy():
    assert issubclass(repository_errors.RepositoryError, RuntimeError)
    shared = [
        value
        for value in vars(repository_errors).values()
        if inspect.isclass(value) and issubclass(value, Exception)
    ]
    assert len(shared) == 10
    owned_elsewhere = [
        embed_keys_repository.EmbedKeyNotFoundError,
        settings_repository.UnknownSettingError,
        temporary_accounts_repository.TemporaryCredentialExpiredError,
        temporary_accounts_repository.TemporaryCredentialNotFoundError,
    ]
    for error in shared + owned_elsewhere:
        assert issubclass(error, repository_errors.RepositoryError), error
    with pytest.raises(repository_errors.RepositoryError):
        raise embed_keys_repository.EmbedKeyNotFoundError("missing")


@pytest.mark.parametrize("first_module", _REPOSITORY_MODULES)
def test_repository_modules_can_be_imported_first_in_a_fresh_process(
    first_module: str,
):
    result = subprocess.run(
        [
            sys.executable,
            "-c",
            textwrap.dedent(f"""\
                import app.auth.{first_module}
                from app.auth import embed_keys_repository as embed
                from app.auth import repository_errors as errors
                from app.auth import runtime

                assert runtime.EmbedKeyRepository is embed.EmbedKeyRepository
                assert issubclass(
                    embed.EmbedKeyNotFoundError, errors.RepositoryError,
                )
                """),
        ],
        cwd=Path(__file__).resolve().parents[2],
        capture_output=True,
        text=True,
        timeout=30,
        check=False,
    )
    assert result.returncode == 0, result.stderr
