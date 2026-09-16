"""Compatibility contract for the historical repository import surface."""

from __future__ import annotations

import subprocess
import sys
import textwrap
from pathlib import Path

import pytest

from app.auth import _repository_base, embed_keys_repository, repositories

# Keep the compatibility contract independent of the implementation's __all__.
_EXPECTED_EXPORTS = {
    "DEFAULT_DAILY_REQUEST_QUOTA",
    "DEFAULT_RATE_LIMIT_PER_MINUTE",
    "EMBED_KEY_PREFIX",
    "EMBED_KEY_RANDOM_CHARS",
    "AccountAccessRepository",
    "AccountEnabledError",
    "AdminAlreadyExistsError",
    "AdminScopeRepository",
    "AuthAuditRepository",
    "EmbedKeyNotFoundError",
    "EmbedKeyRepository",
    "InvalidResourceGrantError",
    "LastAdminError",
    "OwnedResourcesError",
    "RepositoryError",
    "ResourceConflictError",
    "ResourceRepository",
    "SelfProtectionError",
    "TemporaryAccountRepository",
    "TemporaryBatch",
    "TemporaryBatchAccount",
    "TemporaryCredentialCreate",
    "TemporaryCredentialExpiredError",
    "TemporaryCredentialNotFoundError",
    "UserNotFoundError",
    "UserRepository",
    "UsernameConflictError",
    "generate_embed_key_id",
    "normalize_username",
    "utc_day",
}
_EMBED_EXPORTS = {
    "DEFAULT_DAILY_REQUEST_QUOTA",
    "DEFAULT_RATE_LIMIT_PER_MINUTE",
    "EMBED_KEY_PREFIX",
    "EMBED_KEY_RANDOM_CHARS",
    "EmbedKeyNotFoundError",
    "EmbedKeyRepository",
    "generate_embed_key_id",
    "utc_day",
}


def test_repository_exports_preserve_the_public_import_contract():
    assert set(repositories.__all__) == _EXPECTED_EXPORTS
    assert len(repositories.__all__) == len(_EXPECTED_EXPORTS)

    wildcard: dict[str, object] = {}
    exec("from app.auth.repositories import *", wildcard)  # noqa: S102
    assert set(wildcard) - {"__builtins__"} == _EXPECTED_EXPORTS
    for name in sorted(_EXPECTED_EXPORTS):
        explicit: dict[str, object] = {}
        # Names come only from the fixed compatibility contract above.
        exec(f"from app.auth.repositories import {name}", explicit)  # noqa: S102
        assert explicit[name] is getattr(repositories, name)
        assert wildcard[name] is explicit[name]


@pytest.mark.parametrize("name", sorted(_EMBED_EXPORTS))
def test_embed_reexports_preserve_identity(name: str):
    assert getattr(repositories, name) is getattr(embed_keys_repository, name)


def test_repository_errors_share_the_original_exception_hierarchy():
    assert repositories.RepositoryError is _repository_base.RepositoryError
    assert issubclass(repositories.RepositoryError, RuntimeError)
    for name in sorted(_EXPECTED_EXPORTS):
        if name.endswith("Error"):
            assert issubclass(
                getattr(repositories, name), _repository_base.RepositoryError,
            ), name
    error = embed_keys_repository.EmbedKeyNotFoundError("missing")
    with pytest.raises(repositories.RepositoryError):
        raise error


@pytest.mark.parametrize(
    "first_module",
    ["_repository_base", "embed_keys_repository", "repositories"],
)
def test_repository_modules_can_be_imported_first_in_a_fresh_process(
    first_module: str,
):
    result = subprocess.run(
        [
            sys.executable,
            "-c",
            textwrap.dedent(f"""\
                import app.auth.{first_module}
                from app.auth import _repository_base as base
                from app.auth import embed_keys_repository as embed
                from app.auth import repositories as public

                assert public.RepositoryError is base.RepositoryError
                assert public.EmbedKeyRepository is embed.EmbedKeyRepository
                assert public.EmbedKeyNotFoundError is embed.EmbedKeyNotFoundError
                assert issubclass(
                    embed.EmbedKeyNotFoundError, public.RepositoryError,
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
