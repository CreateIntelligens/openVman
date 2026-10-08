"""Construction and caching for the Backend authentication services."""

from __future__ import annotations

from dataclasses import dataclass, field
from functools import lru_cache

from app.config import TTSRouterConfig, get_tts_config

from .attempt_limiter import FailedAttemptLimiter
from .database import AuthDatabase
from .decision_provider_repository import DecisionProviderRepository
from .repositories import (
    AccountAccessRepository,
    AdminScopeRepository,
    AuthAuditRepository,
    EmbedKeyRepository,
    ResourceRepository,
    TemporaryAccountRepository,
    UserRepository,
)
from .settings_repository import SystemSettingsRepository
from .temporary_passwords import TemporaryPasswordCipher
from .tokens import SessionTokenService


@dataclass(frozen=True, slots=True)
class AuthRuntime:
    config: TTSRouterConfig
    database: AuthDatabase
    users: UserRepository
    resources: ResourceRepository
    account_access: AccountAccessRepository
    admin_scopes: AdminScopeRepository
    auth_audit: AuthAuditRepository
    temporary_accounts: TemporaryAccountRepository
    embed_keys: EmbedKeyRepository
    tokens: SessionTokenService
    settings: SystemSettingsRepository
    decision_providers: DecisionProviderRepository
    temporary_passwords: TemporaryPasswordCipher
    # 每個 runtime 各自一份，測試與重建 runtime 時不會共用失敗次數。
    password_verify_attempts: FailedAttemptLimiter = field(
        default_factory=FailedAttemptLimiter,
    )


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
        admin_scopes=AdminScopeRepository(database),
        auth_audit=AuthAuditRepository(database),
        temporary_accounts=TemporaryAccountRepository(database),
        embed_keys=EmbedKeyRepository(database),
        settings=SystemSettingsRepository(database),
        decision_providers=DecisionProviderRepository(
            database,
            encryption_secret=config.decision_provider_encryption_secret,
        ),
        tokens=tokens,
        temporary_passwords=TemporaryPasswordCipher(
            config.auth_temporary_password_secret or config.session_jwt_secret,
        ),
    )


@lru_cache(maxsize=1)
def get_auth_runtime() -> AuthRuntime:
    """Initialize auth once; a missing dedicated secret raises immediately."""
    return build_auth_runtime(get_tts_config())
