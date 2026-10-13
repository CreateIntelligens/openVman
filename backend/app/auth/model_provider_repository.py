"""Stored provider order per model category and encrypted vendor credentials."""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import re
import sqlite3
from dataclasses import dataclass, field
from typing import Mapping
from uuid import uuid4

from cryptography.fernet import Fernet, InvalidToken

from ._repository_base import now_iso
from .database import AuthDatabase
from .model_provider_catalog import CATEGORIES, CREDENTIAL_IDS, ModelCategory

_MODEL_NAME = re.compile(r"[A-Za-z0-9][A-Za-z0-9._:/@-]{0,127}")


class InvalidModelProviderSettings(ValueError):
    """Category, hop, model or credential IDs do not match this build's catalog."""


class ModelProviderEncryptionUnavailable(RuntimeError):
    """The deployment encryption secret is missing or invalid."""


@dataclass(frozen=True, slots=True)
class CategorySettings:
    order: tuple[str, ...]
    enabled: tuple[str, ...]
    # 只存後台改過的模型；沒有的 hop 用部署預設，改 .env 才會跟著生效。
    models: dict[str, str] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class CategoryUpdate:
    order: tuple[str, ...]
    enabled: tuple[str, ...]
    models: dict[str, str] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class CredentialStatus:
    configured: bool
    source: str
    masked: str


class ModelProviderCipher:
    """Derive vendor-separated Fernet keys from a deployment secret."""

    def __init__(self, secret: str) -> None:
        self._secret = secret.encode("utf-8")

    def _cipher(self, credential_id: str) -> Fernet:
        if len(self._secret) < 32:
            raise ModelProviderEncryptionUnavailable(
                "MODEL_PROVIDER_ENCRYPTION_SECRET must contain at least 32 bytes",
            )
        if credential_id not in CREDENTIAL_IDS:
            raise InvalidModelProviderSettings("unknown model provider credential")
        # 衍生標籤沿用只有決策時的字串：改了的話，從舊表搬過來的密文就解不開。
        derived = hmac.digest(
            self._secret,
            b"openvman:decision-provider:v1\0" + credential_id.encode("ascii"),
            hashlib.sha256,
        )
        return Fernet(base64.urlsafe_b64encode(derived))

    def encrypt(self, credential_id: str, value: str) -> str:
        return self._cipher(credential_id).encrypt(value.encode("utf-8")).decode("ascii")

    def decrypt(self, credential_id: str, ciphertext: str) -> str | None:
        try:
            return self._cipher(credential_id).decrypt(ciphertext.encode("ascii")).decode("utf-8")
        except (ModelProviderEncryptionUnavailable, InvalidToken, UnicodeError, ValueError):
            return None


class ModelProviderRepository:
    def __init__(self, database: AuthDatabase, *, encryption_secret: str) -> None:
        self.database = database
        self.cipher = ModelProviderCipher(encryption_secret)

    def get_settings(self, category_id: str) -> CategorySettings | None:
        """Saved settings, or None when the category still runs on deployment defaults."""
        category = _category(category_id)
        with self.database.transaction() as connection:
            row = connection.execute(
                "SELECT order_json, enabled_json, models_json "
                "FROM model_provider_settings WHERE category = ?",
                (category_id,),
            ).fetchone()
        if row is None:
            return None
        try:
            settings = CategorySettings(
                tuple(json.loads(row["order_json"])),
                tuple(json.loads(row["enabled_json"])),
                dict(json.loads(row["models_json"])),
            )
            _validate(category, settings.order, settings.enabled, settings.models)
        except (TypeError, ValueError) as exc:
            raise InvalidModelProviderSettings(
                f"stored {category_id} provider settings are invalid",
            ) from exc
        return settings

    def update(
        self,
        categories: Mapping[str, CategoryUpdate],
        *,
        reset_categories: tuple[str, ...] | list[str] = (),
        credentials: Mapping[str, str],
        reset_credentials: tuple[str, ...] | list[str] = (),
        actor_id: str,
    ) -> None:
        for category_id, change in categories.items():
            _validate(_category(category_id), change.order, change.enabled, change.models)
        reset_category_ids = tuple(reset_categories)
        for category_id in reset_category_ids:
            _category(category_id)
        if set(reset_category_ids) & set(categories):
            raise InvalidModelProviderSettings("category cannot be updated and reset together")
        encrypted: dict[str, tuple[str, bool]] = {}
        for credential_id, value in credentials.items():
            if credential_id not in CREDENTIAL_IDS:
                raise InvalidModelProviderSettings("unknown model provider credential")
            if len(value) > 4096:
                raise InvalidModelProviderSettings("provider credential is too long")
            stripped = value.strip()
            encrypted[credential_id] = (self.cipher.encrypt(credential_id, stripped), bool(stripped))
        reset = tuple(reset_credentials)
        if len(reset) != len(set(reset)) or not set(reset) <= CREDENTIAL_IDS:
            raise InvalidModelProviderSettings("unknown or duplicate credential reset provider")
        if set(reset) & set(encrypted):
            raise InvalidModelProviderSettings("credential cannot be updated and reset together")
        now = now_iso()
        with self.database.transaction(write=True) as connection:
            for category_id, change in categories.items():
                connection.execute(
                    """
                    INSERT INTO model_provider_settings(
                        category, order_json, enabled_json, models_json, updated_by, updated_at
                    ) VALUES (?, ?, ?, ?, ?, ?)
                    ON CONFLICT(category) DO UPDATE SET
                        order_json = excluded.order_json,
                        enabled_json = excluded.enabled_json,
                        models_json = excluded.models_json,
                        updated_by = excluded.updated_by,
                        updated_at = excluded.updated_at
                    """,
                    (
                        category_id,
                        json.dumps(change.order),
                        json.dumps(change.enabled),
                        json.dumps(change.models, sort_keys=True),
                        actor_id,
                        now,
                    ),
                )
                _append_audit(
                    connection,
                    action="model_provider_settings_updated",
                    actor_id=actor_id,
                    metadata={
                        "category": category_id,
                        "order": change.order,
                        "enabled": change.enabled,
                        "models": change.models,
                    },
                    now=now,
                )
            for category_id in reset_category_ids:
                connection.execute(
                    "DELETE FROM model_provider_settings WHERE category = ?", (category_id,),
                )
                _append_audit(
                    connection,
                    action="model_provider_settings_reset",
                    actor_id=actor_id,
                    metadata={"category": category_id},
                    now=now,
                )
            for credential_id, (ciphertext, configured) in encrypted.items():
                connection.execute(
                    """
                    INSERT INTO model_provider_secrets(credential_id, ciphertext, updated_by, updated_at)
                    VALUES (?, ?, ?, ?)
                    ON CONFLICT(credential_id) DO UPDATE SET
                        ciphertext = excluded.ciphertext,
                        updated_by = excluded.updated_by,
                        updated_at = excluded.updated_at
                    """,
                    (credential_id, ciphertext, actor_id, now),
                )
                _append_audit(
                    connection,
                    action="model_provider_credential_updated",
                    actor_id=actor_id,
                    metadata={"credential_id": credential_id, "configured": configured},
                    now=now,
                )
            for credential_id in reset:
                connection.execute(
                    "DELETE FROM model_provider_secrets WHERE credential_id = ?",
                    (credential_id,),
                )
                _append_audit(
                    connection,
                    action="model_provider_credential_reset",
                    actor_id=actor_id,
                    metadata={"credential_id": credential_id},
                    now=now,
                )

    def get_credential(self, credential_id: str, *, env_default: str) -> str:
        return self._resolve(credential_id, env_default)[0]

    def get_credential_status(self, credential_id: str, *, env_default: str) -> CredentialStatus:
        value, source = self._resolve(credential_id, env_default)
        return CredentialStatus(
            configured=bool(value),
            source=source,
            masked=f"••••{value[-4:]}" if value else "",
        )

    def unreadable_credentials(self) -> list[str]:
        """Saved keys the current encryption secret cannot decrypt."""
        with self.database.transaction() as connection:
            rows = connection.execute(
                "SELECT credential_id, ciphertext FROM model_provider_secrets ORDER BY credential_id",
            ).fetchall()
        return [
            str(row["credential_id"]) for row in rows
            if row["credential_id"] in CREDENTIAL_IDS
            and self.cipher.decrypt(str(row["credential_id"]), str(row["ciphertext"])) is None
        ]

    def _resolve(self, credential_id: str, env_default: str) -> tuple[str, str]:
        ciphertext = self._get_ciphertext(credential_id)
        if ciphertext is None:
            return env_default, "environment" if env_default else "none"
        value = self.cipher.decrypt(credential_id, ciphertext)
        if value is None:
            # 加密 secret 換掉或遺失時密文解不開。這跟 ROOT 刻意清除（解得開、值是空字串）
            # 不同：退回部署環境的 key，讓聊天與決策照常運作，頁面再提示重新輸入。
            return env_default, "unreadable"
        return value, "admin"

    def _get_ciphertext(self, credential_id: str) -> str | None:
        if credential_id not in CREDENTIAL_IDS:
            raise InvalidModelProviderSettings("unknown model provider credential")
        with self.database.transaction() as connection:
            row = connection.execute(
                "SELECT ciphertext FROM model_provider_secrets WHERE credential_id = ?",
                (credential_id,),
            ).fetchone()
        return str(row["ciphertext"]) if row else None


def _category(category_id: str) -> ModelCategory:
    category = CATEGORIES.get(category_id)
    if category is None:
        raise InvalidModelProviderSettings("unknown model provider category")
    return category


def _validate(
    category: ModelCategory,
    order: tuple[str, ...],
    enabled: tuple[str, ...],
    models: Mapping[str, str],
) -> None:
    hop_ids = category.hop_ids
    if len(order) != len(hop_ids) or set(order) != set(hop_ids):
        raise InvalidModelProviderSettings(f"{category.id} order must contain each hop exactly once")
    if len(enabled) != len(set(enabled)) or not set(enabled) <= set(hop_ids):
        raise InvalidModelProviderSettings(f"{category.id} enabled contains an unknown or duplicate hop")
    if models and not category.model_editable:
        raise InvalidModelProviderSettings(f"{category.id} models are fixed")
    for hop_id, model in models.items():
        if hop_id not in hop_ids or not isinstance(model, str) or not _MODEL_NAME.fullmatch(model):
            raise InvalidModelProviderSettings(f"{category.id} has an invalid model name")


def _append_audit(
    connection: sqlite3.Connection,
    *,
    action: str,
    actor_id: str,
    metadata: dict[str, object],
    now: str,
) -> None:
    connection.execute(
        """
        INSERT INTO auth_audit_events(
            id, action, actor_user_id, target_user_id, created_at, metadata_json
        ) VALUES (?, ?, ?, NULL, ?, ?)
        """,
        (
            f"aud_{uuid4().hex}",
            action,
            actor_id,
            now,
            json.dumps(metadata, ensure_ascii=False, separators=(",", ":")),
        ),
    )


__all__ = [
    "CategorySettings",
    "CategoryUpdate",
    "CredentialStatus",
    "InvalidModelProviderSettings",
    "ModelProviderCipher",
    "ModelProviderEncryptionUnavailable",
    "ModelProviderRepository",
]
