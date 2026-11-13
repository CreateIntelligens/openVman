"""Construction and caching for the Backend authentication services."""

from __future__ import annotations

from dataclasses import dataclass, field
from functools import lru_cache

from app.config import TTSRouterConfig, get_tts_config

from .account_access_repository import AccountAccessRepository
from .admin_scopes_repository import AdminScopeRepository
from .api_keys_repository import ApiKeyRepository
from .attempt_limiter import FailedAttemptLimiter, RedisAttemptLimiter
from .auth_audit_repository import AuthAuditRepository
from .database import AuthDatabase
from .model_provider_repository import ModelProviderRepository
from .embed_keys_repository import EmbedKeyRepository
from .project_policy_repository import ProjectPolicyRepository
from .project_resource_assignment_repository import (
    ProjectResourceAssignmentRepository,
)
from .request_origins_repository import RequestOriginRepository
from .resource_repository import ResourceRepository
from .settings_repository import SystemSettingsRepository
from .temporary_accounts_repository import TemporaryAccountRepository
from .temporary_passwords import TemporaryPasswordCipher
from .tokens import SessionTokenService
from .user_repository import UserRepository


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
    api_keys: ApiKeyRepository
    tokens: SessionTokenService
    settings: SystemSettingsRepository
    model_providers: ModelProviderRepository
    project_policies: ProjectPolicyRepository
    project_resource_assignments: ProjectResourceAssignmentRepository
    request_origins: RequestOriginRepository
    temporary_passwords: TemporaryPasswordCipher
    # 每個 runtime 各自一份，測試與重建 runtime 時不會共用失敗次數。
    password_verify_attempts: FailedAttemptLimiter | RedisAttemptLimiter = field(
        default_factory=FailedAttemptLimiter,
    )
    # 開放 CORS 後 key 可能被放進瀏覽器，限流擋住失控的迴圈或被拿去濫用。
    # 單一 process 放記憶體；BACKEND_WORKERS 大於 1 時放 Redis。
    api_key_requests: FailedAttemptLimiter | RedisAttemptLimiter | None = None


def _limiter(
    config: TTSRouterConfig, namespace: str, **limits: float,
) -> FailedAttemptLimiter | RedisAttemptLimiter:
    if getattr(config, "backend_workers", 1) <= 1:
        return FailedAttemptLimiter(**limits)
    import redis

    client = redis.Redis.from_url(
        config.redis_url, socket_timeout=0.5, socket_connect_timeout=0.5,
    )
    return RedisAttemptLimiter(client, namespace, **limits)


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
        api_keys=ApiKeyRepository(database),
        settings=SystemSettingsRepository(database),
        model_providers=ModelProviderRepository(
            database,
            encryption_secret=config.model_provider_encryption_secret,
        ),
        project_policies=ProjectPolicyRepository(database),
        project_resource_assignments=ProjectResourceAssignmentRepository(
            database
        ),
        request_origins=RequestOriginRepository(database),
        password_verify_attempts=_limiter(config, "password"),
        api_key_requests=(
            _limiter(
                config, "api-key",
                max_failures=config.api_key_rate_limit_per_minute,
                window_seconds=60.0,
            )
            if config.api_key_rate_limit_per_minute > 0
            else None
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
