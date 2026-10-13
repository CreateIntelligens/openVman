"""Persistence and validation of per-project voice policies."""

from __future__ import annotations

import json
import sqlite3
from collections.abc import Iterable

from ._repository_base import now_iso
from .database import AuthDatabase
from .models import ProjectPolicyRecord, ResourceType
from .repository_errors import InvalidProjectPolicyError
from .settings_repository import SERVER_ASR_PROVIDERS


def _normalized_ids(values: Iterable[str]) -> tuple[str, ...]:
    seen: list[str] = []
    for value in values:
        item = value.strip()
        if item and item not in seen:
            seen.append(item)
    return tuple(seen)


def _optional(value: str | None) -> str | None:
    item = (value or "").strip()
    return item or None


def _json_ids(raw: str) -> tuple[str, ...]:
    try:
        payload = json.loads(raw)
    except (TypeError, ValueError):
        return ()
    if not isinstance(payload, list):
        return ()
    return tuple(item for item in payload if isinstance(item, str) and item)


def _policy_from_row(row: sqlite3.Row) -> ProjectPolicyRecord:
    return ProjectPolicyRecord(
        project_id=row["project_id"],
        allowed_asr_engines=_json_ids(row["allowed_asr_engines_json"]),
        default_asr_engine=row["default_asr_engine"] or None,
        taiwanese_asr_engine=row["taiwanese_asr_engine"] or None,
        allowed_tts_voices=_json_ids(row["allowed_tts_voices_json"]),
        default_tts_voice=row["default_tts_voice"] or None,
        updated_by=row["updated_by"],
        updated_at=row["updated_at"],
    )


def _registered_ids(
    connection: sqlite3.Connection,
    resource_type: ResourceType,
) -> set[str]:
    return {
        row["resource_id"]
        for row in connection.execute(
            "SELECT resource_id FROM resources WHERE resource_type = ?",
            (resource_type.value,),
        ).fetchall()
    }


class ProjectPolicyRepository:
    def __init__(self, database: AuthDatabase) -> None:
        self.database = database

    def get(self, project_id: str) -> ProjectPolicyRecord:
        """Return the stored policy, or an unrestricted one when none exists."""
        with self.database.transaction() as connection:
            row = connection.execute(
                "SELECT * FROM project_policies WHERE project_id = ?",
                (project_id,),
            ).fetchone()
        if row is None:
            return ProjectPolicyRecord(project_id=project_id)
        return _policy_from_row(row)

    def replace(
        self,
        *,
        project_id: str,
        allowed_asr_engines: Iterable[str] = (),
        default_asr_engine: str | None = None,
        taiwanese_asr_engine: str | None = None,
        allowed_tts_voices: Iterable[str] = (),
        default_tts_voice: str | None = None,
        updated_by: str | None,
    ) -> ProjectPolicyRecord:
        engines = _normalized_ids(allowed_asr_engines)
        voices = _normalized_ids(allowed_tts_voices)
        asr_default = _optional(default_asr_engine)
        taiwanese = _optional(taiwanese_asr_engine)
        voice_default = _optional(default_tts_voice)

        with self.database.transaction(write=True) as connection:
            project = connection.execute(
                """
                SELECT 1 FROM resources
                WHERE resource_type = 'project' AND resource_id = ?
                """,
                (project_id,),
            ).fetchone()
            if project is None:
                raise InvalidProjectPolicyError("project is not registered")

            known_engines = _registered_ids(connection, ResourceType.ASR_ENGINE)
            known_voices = _registered_ids(connection, ResourceType.CUSTOM_VOICE)
            unknown = [
                *(f"asr_engine/{item}" for item in engines if item not in known_engines),
                *(
                    f"asr_engine/{item}"
                    for item in (asr_default, taiwanese)
                    if item and item not in known_engines
                ),
                *(f"custom_voice/{item}" for item in voices if item not in known_voices),
                *(
                    [f"custom_voice/{voice_default}"]
                    if voice_default and voice_default not in known_voices else []
                ),
            ]
            if unknown:
                raise InvalidProjectPolicyError(
                    "resource is not registered: " + ", ".join(sorted(set(unknown)))
                )
            # 台語分流走批次辨識（串流引擎聽不懂台語），只能指定伺服器端的批次引擎。
            if taiwanese and taiwanese not in SERVER_ASR_PROVIDERS:
                raise InvalidProjectPolicyError(
                    "taiwanese_asr_engine must be a batch ASR engine"
                )
            if engines:
                for label, value in (
                    ("default_asr_engine", asr_default),
                    ("taiwanese_asr_engine", taiwanese),
                ):
                    if value and value not in engines:
                        raise InvalidProjectPolicyError(
                            f"{label} must be one of allowed_asr_engines"
                        )
            if voices and voice_default and voice_default not in voices:
                raise InvalidProjectPolicyError(
                    "default_tts_voice must be one of allowed_tts_voices"
                )

            if not (engines or voices or asr_default or taiwanese or voice_default):
                # 全部清空等於「不限制」：刪掉整列，之後讀到的就是沒有設定的狀態。
                connection.execute(
                    "DELETE FROM project_policies WHERE project_id = ?",
                    (project_id,),
                )
                return ProjectPolicyRecord(project_id=project_id)

            now = now_iso()
            connection.execute(
                """
                INSERT INTO project_policies(
                    project_id, allowed_asr_engines_json, default_asr_engine,
                    taiwanese_asr_engine, allowed_tts_voices_json,
                    default_tts_voice, updated_by, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(project_id) DO UPDATE SET
                    allowed_asr_engines_json = excluded.allowed_asr_engines_json,
                    default_asr_engine = excluded.default_asr_engine,
                    taiwanese_asr_engine = excluded.taiwanese_asr_engine,
                    allowed_tts_voices_json = excluded.allowed_tts_voices_json,
                    default_tts_voice = excluded.default_tts_voice,
                    updated_by = excluded.updated_by,
                    updated_at = excluded.updated_at
                """,
                (
                    project_id,
                    json.dumps(list(engines), separators=(",", ":")),
                    asr_default,
                    taiwanese,
                    json.dumps(list(voices), separators=(",", ":")),
                    voice_default,
                    updated_by,
                    now,
                ),
            )
        return ProjectPolicyRecord(
            project_id=project_id,
            allowed_asr_engines=engines,
            default_asr_engine=asr_default,
            taiwanese_asr_engine=taiwanese,
            allowed_tts_voices=voices,
            default_tts_voice=voice_default,
            updated_by=updated_by,
            updated_at=now,
        )
