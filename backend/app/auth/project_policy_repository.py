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

#: 後端 TTS 備援鏈認得的引擎名（與 service._provider_routes 一致）。
TTS_ENGINES = (
    "indextts", "voxcpm", "cosyvoice", "gemini-tts", "gcp-tts", "aws-polly", "edge-tts",
)


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
        allowed_characters=_json_ids(row["allowed_characters_json"]),
        default_character_id=row["default_character_id"] or None,
        allowed_backgrounds=_json_ids(row["allowed_backgrounds_json"]),
        default_background_id=row["default_background_id"] or None,
        allowed_mascots=_json_ids(row["allowed_mascots_json"]),
        default_mascot_id=row["default_mascot_id"] or None,
        tts_engine_order=_json_ids(row["tts_engine_order_json"]),
        asr_engine_order=_json_ids(row["asr_engine_order_json"]),
        updated_by=row["updated_by"],
        updated_at=row["updated_at"],
    )



def _valid_project_resource_ids(
    connection: sqlite3.Connection,
    project_id: str,
    resource_type: ResourceType,
) -> set[str]:
    rows = connection.execute(
        """
        SELECT resource_id FROM resources
        WHERE resource_type = ?
          AND (
              visibility = 'system_public'
              OR (visibility = 'project' AND owner_project_id = ?)
          )
        UNION
        SELECT resource_id FROM project_resource_assignments
        WHERE project_id = ? AND resource_type = ?
        """,
        (resource_type.value, project_id, project_id, resource_type.value),
    ).fetchall()
    return {row[0] for row in rows}


def _assigned_or_project_ids(
    connection: sqlite3.Connection,
    project_id: str,
    resource_type: ResourceType,
) -> set[str]:
    rows = connection.execute(
        """
        SELECT resource_id FROM resources
        WHERE resource_type = ?
          AND visibility = 'project'
          AND owner_project_id = ?
        UNION
        SELECT resource_id FROM project_resource_assignments
        WHERE project_id = ? AND resource_type = ?
        """,
        (resource_type.value, project_id, project_id, resource_type.value),
    ).fetchall()
    return {row[0] for row in rows}


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
        allowed_characters: Iterable[str] = (),
        default_character_id: str | None = None,
        allowed_backgrounds: Iterable[str] = (),
        default_background_id: str | None = None,
        allowed_mascots: Iterable[str] = (),
        default_mascot_id: str | None = None,
        tts_engine_order: Iterable[str] = (),
        asr_engine_order: Iterable[str] = (),
        updated_by: str | None,
    ) -> ProjectPolicyRecord:
        engines = _normalized_ids(allowed_asr_engines)
        voices = _normalized_ids(allowed_tts_voices)
        asr_default = _optional(default_asr_engine)
        taiwanese = _optional(taiwanese_asr_engine)
        voice_default = _optional(default_tts_voice)
        characters = _normalized_ids(allowed_characters)
        char_default = _optional(default_character_id)
        backgrounds = _normalized_ids(allowed_backgrounds)
        bg_default = _optional(default_background_id)
        mascots = _normalized_ids(allowed_mascots)
        mascot_default = _optional(default_mascot_id)
        tts_order = _normalized_ids(tts_engine_order)
        asr_order = _normalized_ids(asr_engine_order)
        unknown_tts = [name for name in tts_order if name not in TTS_ENGINES]
        if unknown_tts:
            raise InvalidProjectPolicyError(
                "tts_engine_order has unknown engines: " + ", ".join(unknown_tts)
            )
        unknown_asr = [name for name in asr_order if name not in SERVER_ASR_PROVIDERS]
        if unknown_asr:
            raise InvalidProjectPolicyError(
                "asr_engine_order must list batch ASR engines: " + ", ".join(unknown_asr)
            )
        if engines:
            # 順位是在允許清單裡排序，不能偷渡清單外的引擎。
            outside = [name for name in asr_order if name not in engines]
            if outside:
                raise InvalidProjectPolicyError(
                    "asr_engine_order must be a subset of allowed_asr_engines: "
                    + ", ".join(outside)
                )

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

            known_engines = _valid_project_resource_ids(
                connection, project_id, ResourceType.ASR_ENGINE
            )
            known_voices = _valid_project_resource_ids(
                connection, project_id, ResourceType.CUSTOM_VOICE
            )
            known_characters = _valid_project_resource_ids(
                connection, project_id, ResourceType.AVATAR_CHARACTER
            )
            known_backgrounds = _valid_project_resource_ids(
                connection, project_id, ResourceType.AVATAR_BACKGROUND
            )
            known_mascots = _valid_project_resource_ids(
                connection, project_id, ResourceType.AVATAR_MASCOT
            )

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
                *(f"avatar_character/{item}" for item in characters if item not in known_characters),
                *(
                    [f"avatar_character/{char_default}"]
                    if char_default and char_default not in known_characters else []
                ),
                *(f"avatar_background/{item}" for item in backgrounds if item not in known_backgrounds),
                *(
                    [f"avatar_background/{bg_default}"]
                    if bg_default and bg_default not in known_backgrounds else []
                ),
                *(f"avatar_mascot/{item}" for item in mascots if item not in known_mascots),
                *(
                    [f"avatar_mascot/{mascot_default}"]
                    if mascot_default and mascot_default not in known_mascots else []
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

            assigned_or_project_engines = _assigned_or_project_ids(
                connection, project_id, ResourceType.ASR_ENGINE
            )
            if engines:
                for label, value in (
                    ("default_asr_engine", asr_default),
                    ("taiwanese_asr_engine", taiwanese),
                ):
                    if value and value not in engines and value not in assigned_or_project_engines:
                        raise InvalidProjectPolicyError(
                            f"{label} must be one of allowed_asr_engines"
                        )

            assigned_or_project_voices = _assigned_or_project_ids(
                connection, project_id, ResourceType.CUSTOM_VOICE
            )
            if voices and voice_default and voice_default not in voices and voice_default not in assigned_or_project_voices:
                raise InvalidProjectPolicyError(
                    "default_tts_voice must be one of allowed_tts_voices"
                )

            assigned_or_project_characters = _assigned_or_project_ids(
                connection, project_id, ResourceType.AVATAR_CHARACTER
            )
            if characters and char_default and (
                char_default not in characters
                and char_default not in assigned_or_project_characters
            ):
                raise InvalidProjectPolicyError(
                    "default_character_id must be one of allowed_characters"
                )

            assigned_or_project_backgrounds = _assigned_or_project_ids(
                connection, project_id, ResourceType.AVATAR_BACKGROUND
            )
            if backgrounds and bg_default and (
                bg_default not in backgrounds
                and bg_default not in assigned_or_project_backgrounds
            ):
                raise InvalidProjectPolicyError(
                    "default_background_id must be one of allowed_backgrounds"
                )

            assigned_or_project_mascots = _assigned_or_project_ids(
                connection, project_id, ResourceType.AVATAR_MASCOT
            )
            if mascots and mascot_default and (
                mascot_default not in mascots
                and mascot_default not in assigned_or_project_mascots
            ):
                raise InvalidProjectPolicyError(
                    "default_mascot_id must be one of allowed_mascots"
                )


            if not (
                engines
                or voices
                or characters
                or backgrounds
                or mascots
                or asr_default
                or taiwanese
                or voice_default
                or char_default
                or bg_default
                or mascot_default
                or tts_order
                or asr_order
            ):
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
                    default_tts_voice, allowed_characters_json,
                    default_character_id, allowed_backgrounds_json,
                    default_background_id, allowed_mascots_json,
                    default_mascot_id, tts_engine_order_json,
                    asr_engine_order_json, updated_by, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(project_id) DO UPDATE SET
                    allowed_asr_engines_json = excluded.allowed_asr_engines_json,
                    default_asr_engine = excluded.default_asr_engine,
                    taiwanese_asr_engine = excluded.taiwanese_asr_engine,
                    allowed_tts_voices_json = excluded.allowed_tts_voices_json,
                    default_tts_voice = excluded.default_tts_voice,
                    allowed_characters_json = excluded.allowed_characters_json,
                    default_character_id = excluded.default_character_id,
                    allowed_backgrounds_json = excluded.allowed_backgrounds_json,
                    default_background_id = excluded.default_background_id,
                    allowed_mascots_json = excluded.allowed_mascots_json,
                    default_mascot_id = excluded.default_mascot_id,
                    tts_engine_order_json = excluded.tts_engine_order_json,
                    asr_engine_order_json = excluded.asr_engine_order_json,
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
                    json.dumps(list(characters), separators=(",", ":")),
                    char_default,
                    json.dumps(list(backgrounds), separators=(",", ":")),
                    bg_default,
                    json.dumps(list(mascots), separators=(",", ":")),
                    mascot_default,
                    json.dumps(list(tts_order), separators=(",", ":")),
                    json.dumps(list(asr_order), separators=(",", ":")),
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
            allowed_characters=characters,
            default_character_id=char_default,
            allowed_backgrounds=backgrounds,
            default_background_id=bg_default,
            allowed_mascots=mascots,
            default_mascot_id=mascot_default,
            tts_engine_order=tts_order,
            asr_engine_order=asr_order,
            updated_by=updated_by,
            updated_at=now,
        )
