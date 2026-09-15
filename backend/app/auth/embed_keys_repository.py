"""Embed key issuance, rotation, and per-key request accounting."""

from __future__ import annotations

import base64
import json
import secrets
import sqlite3
from collections.abc import Iterable, Sequence
from datetime import datetime, timezone

from ._repository_base import RepositoryError, now_iso
from .database import AuthDatabase
from .models import EmbedKeyRecord

EMBED_KEY_PREFIX = "ovk_"
EMBED_KEY_RANDOM_CHARS = 24
DEFAULT_RATE_LIMIT_PER_MINUTE = 60
DEFAULT_DAILY_REQUEST_QUOTA = 1000

_EMBED_KEY_TEXT_FIELDS = (
    "label",
    "default_character_id",
    "default_persona_id",
    "default_tts_provider",
    "default_tts_voice",
)
_EMBED_KEY_LIST_FIELDS = ("allowed_origins", "allowed_character_ids")
_EMBED_KEY_LIMIT_FIELDS = ("rate_limit_per_minute", "daily_request_quota")


class EmbedKeyNotFoundError(RepositoryError):
    pass


def generate_embed_key_id() -> str:
    """`ovk_` plus 24 lowercase base32 characters, no padding."""
    # 24 個 base32 字元需要 120 bits，也就是 15 bytes 才能不靠填充編滿。
    raw = base64.b32encode(secrets.token_bytes(15)).decode("ascii")
    return f"{EMBED_KEY_PREFIX}{raw.rstrip('=').lower()[:EMBED_KEY_RANDOM_CHARS]}"


def utc_day(now: datetime | None = None) -> str:
    moment = now or datetime.now(timezone.utc)
    return moment.astimezone(timezone.utc).strftime("%Y-%m-%d")


def _string_tuple(payload: str) -> tuple[str, ...]:
    try:
        values = json.loads(payload)
    except ValueError:
        return ()
    if not isinstance(values, list):
        return ()
    return tuple(value for value in values if isinstance(value, str) and value)


def _json_list(values: Iterable[str]) -> str:
    return json.dumps([str(value) for value in values], separators=(",", ":"))


def _embed_key_from_row(row: sqlite3.Row) -> EmbedKeyRecord:
    return EmbedKeyRecord(
        key_id=row["key_id"],
        label=row["label"],
        project_id=row["project_id"],
        allowed_origins=_string_tuple(row["allowed_origins_json"]),
        default_character_id=row["default_character_id"],
        allowed_character_ids=_string_tuple(row["allowed_character_ids_json"]),
        default_persona_id=row["default_persona_id"],
        default_tts_provider=row["default_tts_provider"],
        default_tts_voice=row["default_tts_voice"],
        rate_limit_per_minute=int(row["rate_limit_per_minute"]),
        daily_request_quota=int(row["daily_request_quota"]),
        disabled=bool(row["disabled"]),
        created_by=row["created_by"],
        created_at=row["created_at"],
        updated_at=row["updated_at"],
        last_used_at=row["last_used_at"],
    )


class EmbedKeyRepository:
    """CRUD plus per-day request accounting for embed keys."""

    def __init__(self, database: AuthDatabase) -> None:
        self.database = database

    def create(
        self,
        *,
        label: str,
        project_id: str,
        allowed_origins: Sequence[str],
        default_character_id: str = "",
        allowed_character_ids: Sequence[str] = (),
        default_persona_id: str = "",
        default_tts_provider: str = "",
        default_tts_voice: str = "",
        rate_limit_per_minute: int = DEFAULT_RATE_LIMIT_PER_MINUTE,
        daily_request_quota: int = DEFAULT_DAILY_REQUEST_QUOTA,
        created_by: str | None = None,
    ) -> EmbedKeyRecord:
        if not allowed_origins:
            raise ValueError("at least one allowed origin is required")
        if rate_limit_per_minute < 1 or daily_request_quota < 1:
            raise ValueError("limits must be at least 1")
        key_id = generate_embed_key_id()
        now = now_iso()
        with self.database.transaction(write=True) as connection:
            connection.execute(
                """
                INSERT INTO embed_keys(
                    key_id, label, project_id, allowed_origins_json,
                    default_character_id, allowed_character_ids_json,
                    default_persona_id, default_tts_provider,
                    default_tts_voice, rate_limit_per_minute,
                    daily_request_quota, disabled, created_by, created_at,
                    updated_at, last_used_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 0, ?, ?, ?, NULL)
                """,
                (
                    key_id,
                    label.strip(),
                    project_id.strip(),
                    _json_list(allowed_origins),
                    default_character_id.strip(),
                    _json_list(allowed_character_ids),
                    default_persona_id.strip(),
                    default_tts_provider.strip(),
                    default_tts_voice.strip(),
                    int(rate_limit_per_minute),
                    int(daily_request_quota),
                    created_by,
                    now,
                    now,
                ),
            )
        record = self.get(key_id)
        if record is None:
            raise RepositoryError("created embed key could not be reloaded")
        return record

    def get(self, key_id: str) -> EmbedKeyRecord | None:
        with self.database.transaction() as connection:
            row = connection.execute(
                "SELECT * FROM embed_keys WHERE key_id = ?",
                (key_id.strip(),),
            ).fetchone()
        return _embed_key_from_row(row) if row is not None else None

    def list_all(self) -> list[EmbedKeyRecord]:
        with self.database.transaction() as connection:
            rows = connection.execute(
                "SELECT * FROM embed_keys ORDER BY created_at DESC, key_id"
            ).fetchall()
        return [_embed_key_from_row(row) for row in rows]

    def update(self, key_id: str, **changes: object) -> EmbedKeyRecord:
        """Apply only the supplied fields; an unknown field name is a ValueError."""
        assignments: list[str] = []
        params: list[object] = []
        for name, value in changes.items():
            if name in _EMBED_KEY_TEXT_FIELDS:
                assignments.append(f"{name} = ?")
                params.append(str(value).strip())
            elif name in _EMBED_KEY_LIST_FIELDS:
                if name == "allowed_origins" and not value:
                    raise ValueError("at least one allowed origin is required")
                assignments.append(f"{name}_json = ?")
                params.append(_json_list(value))  # type: ignore[arg-type]
            elif name in _EMBED_KEY_LIMIT_FIELDS:
                limit = int(value)  # type: ignore[call-overload]
                if limit < 1:
                    raise ValueError("limits must be at least 1")
                assignments.append(f"{name} = ?")
                params.append(limit)
            elif name == "disabled":
                assignments.append("disabled = ?")
                params.append(1 if value else 0)
            else:
                raise ValueError(f"unknown embed key field: {name}")

        if assignments:
            assignments.append("updated_at = ?")
            params.append(now_iso())
            params.append(key_id.strip())
            with self.database.transaction(write=True) as connection:
                cursor = connection.execute(
                    f"UPDATE embed_keys SET {', '.join(assignments)} WHERE key_id = ?",
                    tuple(params),
                )
                if cursor.rowcount == 0:
                    raise EmbedKeyNotFoundError(key_id)

        record = self.get(key_id)
        if record is None:
            raise EmbedKeyNotFoundError(key_id)
        return record

    def delete(self, key_id: str) -> None:
        with self.database.transaction(write=True) as connection:
            cursor = connection.execute(
                "DELETE FROM embed_keys WHERE key_id = ?",
                (key_id.strip(),),
            )
            if cursor.rowcount == 0:
                raise EmbedKeyNotFoundError(key_id)

    def touch(self, key_id: str) -> None:
        with self.database.transaction(write=True) as connection:
            connection.execute(
                "UPDATE embed_keys SET last_used_at = ? WHERE key_id = ?",
                (now_iso(), key_id.strip()),
            )

    def requests_today(self, key_id: str, *, day: str | None = None) -> int:
        with self.database.transaction() as connection:
            row = connection.execute(
                """
                SELECT requests FROM embed_key_daily_usage
                WHERE key_id = ? AND day = ?
                """,
                (key_id.strip(), day or utc_day()),
            ).fetchone()
        return int(row["requests"]) if row is not None else 0

    def increment_daily(self, key_id: str, *, day: str | None = None) -> int:
        """Count one request and return the running total for that day."""
        target_day = day or utc_day()
        with self.database.transaction(write=True) as connection:
            connection.execute(
                """
                INSERT INTO embed_key_daily_usage(key_id, day, requests)
                VALUES (?, ?, 1)
                ON CONFLICT(key_id, day) DO UPDATE SET requests = requests + 1
                """,
                (key_id.strip(), target_day),
            )
            row = connection.execute(
                """
                SELECT requests FROM embed_key_daily_usage
                WHERE key_id = ? AND day = ?
                """,
                (key_id.strip(), target_day),
            ).fetchone()
        return int(row["requests"]) if row is not None else 0
