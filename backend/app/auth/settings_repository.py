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

# 瀏覽器內建的 Web Speech API。它跟其他幾個不同類：辨識在使用者的裝置上
# 發生，音檔不會送到後端，所以 _TRANSCRIBERS 裡沒有對應的函式，也不參與
# 伺服器端的 fallback chain。後端存它只是記住使用者的偏好。
BROWSER_ASR_PROVIDER = "browser"

# Gemini transcribe-live 串流辨識：前台經 /api/v1/asr/stream 邊錄邊送，跟 browser
# 一樣不進 transcribe() 的 fallback chain，後端存它只是記住偏好與授權。
GEMINI_STREAM_ASR_PROVIDER = "gemini-live"

# 伺服器端引擎：音檔會送上來，走 transcribe() 與 fallback chain。
SERVER_ASR_PROVIDERS = frozenset({"breeze", "xiaomi", "sensevoice", "openai"})

# 使用者可以在聊天室選哪些引擎，由管理者決定（例如 openai 會把語音送到
# 外部服務，不一定想開放給每個人）。空集合代表不開放使用者自選。
ASR_USER_CHOICES_KEY = "asr_user_choices"

_ASR_PROVIDERS = SERVER_ASR_PROVIDERS | {BROWSER_ASR_PROVIDER, GEMINI_STREAM_ASR_PROVIDER}
_ALLOWED_VALUES: dict[str, frozenset[str]] = {
    ASR_PROVIDER_KEY: SERVER_ASR_PROVIDERS,
    ASR_USER_CHOICES_KEY: _ASR_PROVIDERS,
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

    def set_many(
        self, key: str, values: list[str], *, actor_id: str,
    ) -> list[str]:
        """Store a set-valued setting as a sorted, comma-separated string.

        沿用同一張表與同一條稽核路徑，不另外開一張表：這裡要存的只是「哪些
        選項開放」，一個字串就夠。排序後再存，讀回來的順序才穩定。
        """
        allowed = self.allowed_values(key)
        unknown = sorted(set(values) - allowed)
        if unknown:
            raise InvalidSettingValueError(
                f"{key} contains unknown values: {', '.join(unknown)}"
            )
        joined = ",".join(sorted(set(values)))
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
                (key, joined, actor_id, now),
            )
            _append_settings_audit(
                connection, key=key, value=joined, actor_id=actor_id, now=now,
            )
        return sorted(set(values))

    def get_many(self, key: str) -> list[str] | None:
        """Read a set-valued setting, or None when no override is stored.

        空字串是有意義的值（管理者關閉了所有選項），不能跟「沒設定過」混為
        一談——後者要回退到預設，前者不能。
        """
        stored = self.get(key)
        if stored is None:
            return None
        return [item for item in stored.split(",") if item]

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
    "ASR_USER_CHOICES_KEY",
    "BROWSER_ASR_PROVIDER",
    "SERVER_ASR_PROVIDERS",
    "InvalidSettingValueError",
    "SystemSettingsRepository",
    "UnknownSettingError",
]
