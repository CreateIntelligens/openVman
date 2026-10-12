"""Historical import surface for the account and registry repositories.

每個 repository 已各自成模組；呼叫端歷來從這裡 import，所以保留原入口並
re-export 同一批物件。__all__ 維持拆分前的公開介面，星號匯入結果不變。
"""

from __future__ import annotations

# _normalize_account_access 不在 __all__，但既有測試直接從這裡 import 它。
from ._account_access_rules import _normalize_account_access
from ._account_records import normalize_username
from ._repository_base import (
    AccountEnabledError,
    AdminAlreadyExistsError,
    InvalidResourceGrantError,
    LastAdminError,
    OwnedResourcesError,
    RepositoryError,
    ResourceConflictError,
    SelfProtectionError,
    UserNotFoundError,
    UsernameConflictError,
)
from .account_access_repository import AccountAccessRepository
from .admin_scopes_repository import AdminScopeRepository
from .auth_audit_repository import AuthAuditRepository
from .embed_keys_repository import (
    DEFAULT_DAILY_REQUEST_QUOTA,
    DEFAULT_RATE_LIMIT_PER_MINUTE,
    EMBED_KEY_PREFIX,
    EMBED_KEY_RANDOM_CHARS,
    EmbedKeyNotFoundError,
    EmbedKeyRepository,
    generate_embed_key_id,
    utc_day,
)
from .resource_repository import ResourceRepository
from .temporary_accounts_repository import (
    TemporaryAccountRepository,
    TemporaryBatch,
    TemporaryBatchAccount,
    TemporaryCredentialCreate,
    TemporaryCredentialExpiredError,
    TemporaryCredentialNotFoundError,
)
from .user_repository import UserRepository

__all__ = [
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
]
