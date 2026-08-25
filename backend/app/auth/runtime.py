"""Construction and caching for the Backend authentication services."""

from __future__ import annotations

from dataclasses import dataclass
from functools import lru_cache

from app.config import TTSRouterConfig, get_tts_config

from .database import AuthDatabase
from .repositories import (
    AccountAccessRepository,
    AuthAuditRepository,
    ResourceRepository,
    TemporaryAccountRepository,
    UserRepository,
)
from .tokens import SessionTokenService


@dataclass(frozen=True, slots=True)
class AuthRuntime:
    config: TTSRouterConfig
    database: AuthDatabase
    users: UserRepository
    resources: ResourceRepository
    account_access: AccountAccessRepository
    auth_audit: AuthAuditRepository
    temporary_accounts: TemporaryAccountRepository
    tokens: SessionTokenService


def build_auth_runtime(config: TTSRouterConfig) -> AuthRuntime:
    tokens = SessionTokenService(
        secret=config.session_jwt_secret,
        issuer=config.auth_jwt_issuer,
        audience=config.auth_jwt_audience,
        lifetime_seconds=config.auth_session_lifetime_seconds,
    )
    database = AuthDatabase(config.auth_database_path)
    database.initialize()
    return AuthRuntime(
        config=config,
        database=database,
        users=UserRepository(database),
        resources=ResourceRepository(database),
        account_access=AccountAccessRepository(database),
        auth_audit=AuthAuditRepository(database),
        temporary_accounts=TemporaryAccountRepository(database),
        tokens=tokens,
    )


@lru_cache(maxsize=1)
def get_auth_runtime() -> AuthRuntime:
    """Initialize auth once; a missing dedicated secret raises immediately."""
    return build_auth_runtime(get_tts_config())
