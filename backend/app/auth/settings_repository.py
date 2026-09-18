"""Operator-editable settings that override environment defaults."""

from __future__ import annotations

import sqlite3

from ._repository_base import RepositoryError, now_iso
from .database import AuthDatabase


class UnknownSettingError(RepositoryError):
    """The key is not one this build knows how to apply."""


class InvalidSettingValueError(RepositoryError):
    """The value is outside the allowed set for this key."""


# key → 允許的值。白名單而不是自由字串：這些設定會直接改變每個使用者的
# 行為，打錯一個字母就整站沒有語音辨識，而且要到下一次有人講話才發現。
ASR_PROVIDER_KEY = "asr_provider"
_ALLOWED_VALUES: dict[str, frozenset[str]] = {
    ASR_PROVIDER_KEY: frozenset({"sensevoice", "breeze", "openai", "local"}),
}


class SystemSettingsRepository:
    """Read and write the settings an administrator may change at runtime."""

    def __init__(self, database: AuthDatabase) -> None:
        self.database = database

    def get(self, key: str) -> str | None:
        """Return the stored override, or None to fall back to the environment."""
        with self.database.transaction() as connection:
            row = connection.execute(
                "SELECT value FROM system_settings WHERE key = ?",
                (key,),
            ).fetchone()
        return row["value"] if row is not None else None

    def all(self) -> dict[str, str]:
        with self.database.transaction() as connection:
            rows = connection.execute(
                "SELECT key, value FROM system_settings"
            ).fetchall()
        return {row["key"]: row["value"] for row in rows}

    def allowed_values(self, key: str) -> frozenset[str]:
        try:
            return _ALLOWED_VALUES[key]
        except KeyError as exc:
            raise UnknownSettingError(f"unknown setting: {key}") from exc

    def set(self, key: str, value: str, *, actor_id: str) -> str:
        """Store an override after checking it against the key's allowed set."""
        allowed = self.allowed_values(key)
        if value not in allowed:
            raise InvalidSettingValueError(
                f"{key} must be one of: {', '.join(sorted(allowed))}"
            )
        now = now_iso()
        with self.database.transaction(write=True) as connection:
            connection.execute(
                """
                INSERT INTO system_settings(key, value, updated_by, updated_at)
                VALUES (?, ?, ?, ?)
                ON CONFLICT(key) DO UPDATE SET
                    value = excluded.value,
                    updated_by = excluded.updated_by,
                    updated_at = excluded.updated_at
                """,
                (key, value, actor_id, now),
            )
            _append_settings_audit(
                connection, key=key, value=value, actor_id=actor_id, now=now,
            )
        return value

    def clear(self, key: str, *, actor_id: str) -> None:
        """Drop the override so the environment default applies again."""
        self.allowed_values(key)
        now = now_iso()
        with self.database.transaction(write=True) as connection:
            connection.execute("DELETE FROM system_settings WHERE key = ?", (key,))
            _append_settings_audit(
                connection, key=key, value="", actor_id=actor_id, now=now,
            )


def _append_settings_audit(
    connection: sqlite3.Connection,
    *,
    key: str,
    value: str,
    actor_id: str,
    now: str,
) -> None:
    import json
    from uuid import uuid4

    connection.execute(
        """
        INSERT INTO auth_audit_events(
            id, action, actor_user_id, target_user_id, created_at, metadata_json
        ) VALUES (?, ?, ?, NULL, ?, ?)
        """,
        (
            f"aud_{uuid4().hex}",
            "system_setting_updated",
            actor_id,
            now,
            json.dumps({"key": key, "value": value}, ensure_ascii=False),
        ),
    )


__all__ = [
    "ASR_PROVIDER_KEY",
    "InvalidSettingValueError",
    "SystemSettingsRepository",
    "UnknownSettingError",
]
