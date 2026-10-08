"""Runtime settings and encrypted credentials for typed decision providers."""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import sqlite3
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Final, Mapping
from uuid import uuid4

from cryptography.fernet import Fernet, InvalidToken

from ._repository_base import now_iso
from .database import AuthDatabase

DEFAULT_DECISION_ORDER: Final[tuple[str, ...]] = (
    "clef-primary", "clef-backup", "jev", "openai",
)
DECISION_HOPS: Final[dict[str, dict[str, str | bool]]] = {
    "clef-primary": {
        "provider": "clef", "label": "Clef 主端點",
        "endpoint": "https://clef.create360.ai/v1/systemone",
        "model": "clef-flash", "credential_id": "clef",
        "environment": "clef_api_key", "required": False,
    },
    "clef-backup": {
        "provider": "clef", "label": "Clef 備援端點",
        "endpoint": "https://clef.aiurl.tw/v1/systemone",
        "model": "clef-flash", "credential_id": "clef",
        "environment": "clef_api_key", "required": False,
    },
    "jev": {
        "provider": "jev", "label": "Jev",
        "endpoint": "https://api.typesafe.ai/v1/systemone",
        "model": "jev-latest", "credential_id": "jev",
        "environment": "typesafe_api_key", "required": True,
    },
    "openai": {
        "provider": "openai", "label": "OpenAI Decisions",
        "endpoint": "https://api.openai.com/v1/decisions",
        "model": "gpt-6-luna", "credential_id": "openai",
        "environment": "decision_openai_api_key", "required": True,
    },
}
DECISION_CREDENTIAL_IDS: Final[frozenset[str]] = frozenset({"clef", "jev", "openai"})


class InvalidDecisionProviderSettings(ValueError):
    """Provider IDs or order do not match this build's fixed provider list."""


class DecisionProviderEncryptionUnavailable(RuntimeError):
    """The deployment encryption secret is missing or invalid."""


@dataclass(frozen=True, slots=True)
class DecisionProviderSettings:
    order: tuple[str, ...]
    enabled: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class CredentialStatus:
    configured: bool
    source: str
    masked: str


class DecisionProviderCipher:
    """Derive provider-separated Fernet keys from a deployment secret."""

    def __init__(self, secret: str) -> None:
        self._secret = secret.encode("utf-8")

    def _cipher(self, provider_id: str) -> Fernet:
        if len(self._secret) < 32:
            raise DecisionProviderEncryptionUnavailable(
                "DECISION_PROVIDER_ENCRYPTION_SECRET must contain at least 32 bytes",
            )
        if provider_id not in DECISION_CREDENTIAL_IDS:
            raise InvalidDecisionProviderSettings("unknown decision provider credential")
        derived = hmac.digest(
            self._secret,
            b"openvman:decision-provider:v1\0" + provider_id.encode("ascii"),
            hashlib.sha256,
        )
        return Fernet(base64.urlsafe_b64encode(derived))

    def encrypt(self, provider_id: str, value: str) -> str:
        return self._cipher(provider_id).encrypt(value.encode("utf-8")).decode("ascii")

    def decrypt(self, provider_id: str, ciphertext: str) -> str | None:
        try:
            return self._cipher(provider_id).decrypt(ciphertext.encode("ascii")).decode("utf-8")
        except (DecisionProviderEncryptionUnavailable, InvalidToken, UnicodeError, ValueError):
            return None


class DecisionProviderRepository:
    def __init__(self, database: AuthDatabase, *, encryption_secret: str) -> None:
        self.database = database
        self.cipher = DecisionProviderCipher(encryption_secret)

    def get_settings(self) -> DecisionProviderSettings:
        with self.database.transaction() as connection:
            row = connection.execute(
                "SELECT order_json, enabled_json FROM decision_provider_settings WHERE setting_id = 1",
            ).fetchone()
        if row is None:
            return DecisionProviderSettings(DEFAULT_DECISION_ORDER, DEFAULT_DECISION_ORDER)
        try:
            order = tuple(json.loads(row["order_json"]))
            enabled = tuple(json.loads(row["enabled_json"]))
            self._validate_settings(order, enabled)
        except (TypeError, ValueError, json.JSONDecodeError) as exc:
            raise InvalidDecisionProviderSettings("stored decision provider settings are invalid") from exc
        return DecisionProviderSettings(order, enabled)

    def set_settings(
        self,
        order: tuple[str, ...] | list[str],
        enabled: tuple[str, ...] | list[str],
        *,
        actor_id: str,
    ) -> DecisionProviderSettings:
        return self.update(
            order, enabled, credentials={}, actor_id=actor_id,
        )

    def update(
        self,
        order: tuple[str, ...] | list[str],
        enabled: tuple[str, ...] | list[str],
        *,
        credentials: Mapping[str, str],
        reset_credentials: tuple[str, ...] | list[str] = (),
        actor_id: str,
    ) -> DecisionProviderSettings:
        order_tuple, enabled_tuple = tuple(order), tuple(enabled)
        self._validate_settings(order_tuple, enabled_tuple)
        encrypted: dict[str, tuple[str, bool]] = {}
        for provider_id, value in credentials.items():
            if provider_id not in DECISION_CREDENTIAL_IDS:
                raise InvalidDecisionProviderSettings("unknown decision provider credential")
            if len(value) > 4096:
                raise InvalidDecisionProviderSettings("provider credential is too long")
            stripped = value.strip()
            encrypted[provider_id] = (self.cipher.encrypt(provider_id, stripped), bool(stripped))
        reset = tuple(reset_credentials)
        if len(reset) != len(set(reset)) or not set(reset) <= DECISION_CREDENTIAL_IDS:
            raise InvalidDecisionProviderSettings("unknown or duplicate credential reset provider")
        if set(reset) & set(encrypted):
            raise InvalidDecisionProviderSettings("credential cannot be updated and reset together")
        now = now_iso()
        metadata = json.dumps(
            {"order": order_tuple, "enabled": enabled_tuple},
            ensure_ascii=False,
            separators=(",", ":"),
        )
        with self.database.transaction(write=True) as connection:
            connection.execute(
                """
                INSERT INTO decision_provider_settings(
                    setting_id, order_json, enabled_json, updated_by, updated_at
                ) VALUES (1, ?, ?, ?, ?)
                ON CONFLICT(setting_id) DO UPDATE SET
                    order_json = excluded.order_json,
                    enabled_json = excluded.enabled_json,
                    updated_by = excluded.updated_by,
                    updated_at = excluded.updated_at
                """,
                (json.dumps(order_tuple), json.dumps(enabled_tuple), actor_id, now),
            )
            self._append_audit(
                connection, action="decision_provider_order_updated",
                actor_id=actor_id, metadata=metadata, now=now,
            )
            for provider_id, (ciphertext, configured) in encrypted.items():
                connection.execute(
                    """
                    INSERT INTO decision_provider_secrets(provider_id, ciphertext, updated_by, updated_at)
                    VALUES (?, ?, ?, ?)
                    ON CONFLICT(provider_id) DO UPDATE SET
                        ciphertext = excluded.ciphertext,
                        updated_by = excluded.updated_by,
                        updated_at = excluded.updated_at
                    """,
                    (provider_id, ciphertext, actor_id, now),
                )
                self._append_audit(
                    connection,
                    action="decision_provider_credential_updated",
                    actor_id=actor_id,
                    metadata=json.dumps(
                        {"provider_id": provider_id, "configured": configured},
                        separators=(",", ":"),
                    ),
                    now=now,
                )
            for provider_id in reset:
                connection.execute(
                    "DELETE FROM decision_provider_secrets WHERE provider_id = ?",
                    (provider_id,),
                )
                self._append_audit(
                    connection,
                    action="decision_provider_credential_reset",
                    actor_id=actor_id,
                    metadata=json.dumps({"provider_id": provider_id}, separators=(",", ":")),
                    now=now,
                )
        return DecisionProviderSettings(order_tuple, enabled_tuple)

    def set_credential(self, provider_id: str, value: str, *, actor_id: str) -> None:
        if provider_id not in DECISION_CREDENTIAL_IDS:
            raise InvalidDecisionProviderSettings("unknown decision provider credential")
        if len(value) > 4096:
            raise InvalidDecisionProviderSettings("provider credential is too long")
        ciphertext = self.cipher.encrypt(provider_id, value.strip())
        now = now_iso()
        with self.database.transaction(write=True) as connection:
            connection.execute(
                """
                INSERT INTO decision_provider_secrets(provider_id, ciphertext, updated_by, updated_at)
                VALUES (?, ?, ?, ?)
                ON CONFLICT(provider_id) DO UPDATE SET
                    ciphertext = excluded.ciphertext,
                    updated_by = excluded.updated_by,
                    updated_at = excluded.updated_at
                """,
                (provider_id, ciphertext, actor_id, now),
            )
            self._append_audit(
                connection,
                action="decision_provider_credential_updated",
                actor_id=actor_id,
                metadata=json.dumps(
                    {"provider_id": provider_id, "configured": bool(value.strip())},
                    separators=(",", ":"),
                ),
                now=now,
            )

    def get_credential(self, provider_id: str, *, env_default: str) -> str:
        ciphertext = self._get_ciphertext(provider_id)
        if ciphertext is None:
            return env_default
        return self.cipher.decrypt(provider_id, ciphertext) or ""

    def get_credential_status(self, provider_id: str, *, env_default: str) -> CredentialStatus:
        ciphertext = self._get_ciphertext(provider_id)
        if ciphertext is None:
            value, source = env_default, "environment" if env_default else "none"
        else:
            value = self.cipher.decrypt(provider_id, ciphertext) or ""
            source = "admin"
        return CredentialStatus(
            configured=bool(value),
            source=source,
            masked=f"••••{value[-4:]}" if value else "",
        )

    def _get_ciphertext(self, provider_id: str) -> str | None:
        if provider_id not in DECISION_CREDENTIAL_IDS:
            raise InvalidDecisionProviderSettings("unknown decision provider credential")
        with self.database.transaction() as connection:
            row = connection.execute(
                "SELECT ciphertext FROM decision_provider_secrets WHERE provider_id = ?",
                (provider_id,),
            ).fetchone()
        return str(row["ciphertext"]) if row else None

    @staticmethod
    def _validate_settings(order: tuple[str, ...], enabled: tuple[str, ...]) -> None:
        if len(order) != len(DEFAULT_DECISION_ORDER) or set(order) != set(DEFAULT_DECISION_ORDER):
            raise InvalidDecisionProviderSettings("order must contain each decision hop exactly once")
        if len(enabled) != len(set(enabled)) or not set(enabled) <= set(DEFAULT_DECISION_ORDER):
            raise InvalidDecisionProviderSettings("enabled contains an unknown or duplicate decision hop")

    @staticmethod
    def _append_audit(
        connection: sqlite3.Connection,
        *,
        action: str,
        actor_id: str,
        metadata: str,
        now: datetime | str,
    ) -> None:
        timestamp = now.isoformat() if isinstance(now, datetime) else now
        connection.execute(
            """
            INSERT INTO auth_audit_events(
                id, action, actor_user_id, target_user_id, created_at, metadata_json
            ) VALUES (?, ?, ?, NULL, ?, ?)
            """,
            (f"aud_{uuid4().hex}", action, actor_id, timestamp, metadata),
        )


__all__ = [
    "CredentialStatus",
    "DECISION_CREDENTIAL_IDS",
    "DECISION_HOPS",
    "DEFAULT_DECISION_ORDER",
    "DecisionProviderCipher",
    "DecisionProviderEncryptionUnavailable",
    "DecisionProviderRepository",
    "DecisionProviderSettings",
    "InvalidDecisionProviderSettings",
]
