"""Password and session JWT security tests."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from app.auth.database import AuthDatabase
from app.auth.models import AccountRole, AccountType
from app.auth.passwords import (
    PasswordValidationError,
    hash_password,
    verify_password,
)
from app.auth.repositories import UserRepository
from app.auth.tokens import (
    AuthConfigurationError,
    InvalidSessionTokenError,
    SessionTokenService,
)


def _user(tmp_path: Path):
    database = AuthDatabase(tmp_path / "accounts.db")
    database.initialize()
    return UserRepository(database).create(
        username="alice",
        password_hash="unused",
        role=AccountRole.USER,
    )


def _tokens(**overrides) -> SessionTokenService:
    settings = {
        "secret": "test-only-secret",
        "issuer": "openvman",
        "audience": "openvman-web",
        "lifetime_seconds": 3600,
    }
    settings.update(overrides)
    return SessionTokenService(**settings)


def test_bcrypt_hashes_and_verifies_without_silent_truncation():
    password = "correct horse battery staple"
    password_hash = hash_password(password)

    assert password_hash != password
    assert verify_password(password, password_hash) is True
    assert verify_password("incorrect password", password_hash) is False

    with pytest.raises(PasswordValidationError, match="at least 8 UTF-8 bytes"):
        hash_password("1234567")
    with pytest.raises(PasswordValidationError):
        hash_password("a" * 73)
    with pytest.raises(PasswordValidationError):
        hash_password("密" * 25)
    assert verify_password("a" * 73, password_hash) is False


def test_jwt_round_trip_contains_the_required_contract(tmp_path: Path):
    user = _user(tmp_path)
    service = _tokens()

    claims = service.decode(service.issue(user))

    assert claims.subject == user.id
    assert claims.role is AccountRole.USER
    assert claims.account_type is AccountType.FORMAL
    assert claims.token_version == 0
    assert claims.expires_at > claims.issued_at


def test_jwt_rejects_expiry_wrong_audience_and_malformed_tokens(tmp_path: Path):
    user = _user(tmp_path)
    service = _tokens(lifetime_seconds=60)
    expired = service.issue(
        user,
        now=datetime.now(timezone.utc) - timedelta(minutes=2),
    )
    wrong_audience = _tokens(audience="other-client").issue(user)

    for token in (expired, wrong_audience, "not-a-jwt"):
        with pytest.raises(InvalidSessionTokenError, match="invalid session token"):
            service.decode(token)


def test_missing_dedicated_secret_fails_closed():
    with pytest.raises(AuthConfigurationError, match="SESSION_JWT_SECRET"):
        _tokens(secret="")
