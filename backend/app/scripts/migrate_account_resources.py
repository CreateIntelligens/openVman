"""Reconcile legacy resources into the account ownership registry."""

from __future__ import annotations

import argparse
import json
import os
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from app.auth.database import AuthDatabase
from app.auth.models import (
    AccountRole,
    AccountType,
    ResourceRecord,
    ResourceType,
    ResourceVisibility,
    UserRecord,
)
from app.auth.repositories import (
    ResourceConflictError,
    ResourceRepository,
    UserRepository,
)
from app.config import get_tts_config

_MIGRATION_VERSION = 100
_MIGRATION_NAME = "legacy_account_resource_registry"
_PROJECT_ID_PATTERN = re.compile(r"^[A-Za-z0-9._-]{1,64}$")
_SAFE_RESOURCE_ID_PATTERN = re.compile(r"^[A-Za-z0-9._-]+$")
_CHARACTER_FILES = ("01.webm", "combined_data.json.gz")
_BACKGROUND_IMAGES = ("image.png", "image.jpg", "image.webp")
_MASCOT_MODEL = "model.vrm"
_BUILTIN_MASCOT_IDS = frozenset(
    {"haru-live2d", "qqman", "vrm-sample"}
)
_DEFAULT_PROJECT_ID = "proj-b85afb8bb6"
_DEFAULT_CHARACTER_ID = "0713"
_DEFAULT_VOICE_PROVIDER = "indextts"
_DEFAULT_VOICE_ID = "hayley"
_DEFAULT_MASCOT_ID = "haru-live2d"
_DEFAULT_BACKGROUND_ID = "8881"


@dataclass(frozen=True, slots=True)
class MigrationSources:
    projects_dir: Path
    avatar_dir: Path
    backgrounds_dir: Path
    mascots_dir: Path
    indextts_speaker_json: Path
    indextts_assets_dir: Path


@dataclass(frozen=True, slots=True)
class ExpectedResource:
    resource_type: ResourceType
    resource_id: str
    owner_user_id: str | None
    visibility: ResourceVisibility
    metadata: dict[str, object]
    source: str

    @property
    def key(self) -> tuple[ResourceType, str]:
        return self.resource_type, self.resource_id


class MigrationPrerequisiteError(RuntimeError):
    pass


def _new_report(*, dry_run: bool) -> dict[str, Any]:
    return {
        "status": "ok",
        "dry_run": dry_run,
        "migration": {
            "version": _MIGRATION_VERSION,
            "name": _MIGRATION_NAME,
            "marker_created": False,
        },
        "bootstrap_admin": None,
        "source_counts": {},
        "source_issues": [],
        "resources": {
            "registered": [],
            "would_register": [],
            "unchanged": [],
            "conflicts": [],
            "registry_without_source": [],
        },
        "defaults": {
            "created": [],
            "would_create": [],
            "preserved": [],
            "skipped": [],
        },
    }


def _resource_ref(resource_type: ResourceType, resource_id: str) -> dict[str, str]:
    return {
        "resource_type": resource_type.value,
        "resource_id": resource_id,
    }


def _record_source_issue(
    report: dict[str, Any],
    *,
    source: str,
    resource_id: str | None,
    reason: str,
) -> None:
    issue: dict[str, str] = {"source": source, "reason": reason}
    if resource_id is not None:
        issue["resource_id"] = resource_id
    report["source_issues"].append(issue)


def _read_label(directory: Path, fallback: str) -> str:
    metadata_path = directory / "meta.json"
    try:
        payload = json.loads(metadata_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return fallback
    label = payload.get("label") if isinstance(payload, dict) else None
    return label.strip() if isinstance(label, str) and label.strip() else fallback


def _discover_projects(
    root: Path,
    admin: UserRecord,
    report: dict[str, Any],
) -> list[ExpectedResource]:
    source = "brain_projects"
    if not root.is_dir():
        _record_source_issue(
            report,
            source=source,
            resource_id=None,
            reason=f"source directory is unavailable: {root}",
        )
        return []

    discovered: list[ExpectedResource] = []
    for directory in sorted(root.iterdir(), key=lambda item: item.name):
        if not directory.is_dir() or directory.name.startswith("."):
            continue
        if _PROJECT_ID_PATTERN.fullmatch(directory.name) is None:
            _record_source_issue(
                report,
                source=source,
                resource_id=directory.name,
                reason="invalid project identifier",
            )
            continue
        label_path = directory / "project.label"
        try:
            label = label_path.read_text(encoding="utf-8").strip()
        except OSError:
            label = ""
        discovered.append(
            ExpectedResource(
                resource_type=ResourceType.PROJECT,
                resource_id=directory.name,
                owner_user_id=admin.id,
                visibility=ResourceVisibility.PRIVATE,
                metadata={"label": label or directory.name},
                source=source,
            )
        )
    report["source_counts"][source] = len(discovered)
    return discovered


def _discover_characters(
    root: Path,
    report: dict[str, Any],
) -> list[ExpectedResource]:
    source = "avatar_characters"
    if not root.is_dir():
        _record_source_issue(
            report,
            source=source,
            resource_id=None,
            reason=f"source directory is unavailable: {root}",
        )
        return []

    discovered: list[ExpectedResource] = []
    for directory in sorted(root.iterdir(), key=lambda item: item.name):
        if not directory.is_dir() or directory.name.startswith("."):
            continue
        if _SAFE_RESOURCE_ID_PATTERN.fullmatch(directory.name) is None:
            _record_source_issue(
                report,
                source=source,
                resource_id=directory.name,
                reason="invalid character identifier",
            )
            continue
        missing = [
            filename
            for filename in _CHARACTER_FILES
            if not (directory / filename).is_file()
            or (directory / filename).stat().st_size <= 0
        ]
        if missing:
            _record_source_issue(
                report,
                source=source,
                resource_id=directory.name,
                reason=f"incomplete character assets: {', '.join(missing)}",
            )
            continue
        discovered.append(
            ExpectedResource(
                resource_type=ResourceType.AVATAR_CHARACTER,
                resource_id=directory.name,
                owner_user_id=None,
                visibility=ResourceVisibility.SYSTEM_PUBLIC,
                metadata={"label": _read_label(directory, directory.name)},
                source=source,
            )
        )
    report["source_counts"][source] = len(discovered)
    return discovered


def _discover_backgrounds(
    root: Path,
    report: dict[str, Any],
) -> list[ExpectedResource]:
    source = "avatar_backgrounds"
    if not root.is_dir():
        _record_source_issue(
            report,
            source=source,
            resource_id=None,
            reason=f"source directory is unavailable: {root}",
        )
        return []

    discovered: list[ExpectedResource] = []
    for directory in sorted(root.iterdir(), key=lambda item: item.name):
        if not directory.is_dir() or directory.name.startswith("."):
            continue
        images = [
            directory / filename
            for filename in _BACKGROUND_IMAGES
            if (directory / filename).is_file()
            and (directory / filename).stat().st_size > 0
        ]
        if len(images) != 1:
            _record_source_issue(
                report,
                source=source,
                resource_id=directory.name,
                reason="background must contain exactly one non-empty runtime image",
            )
            continue
        discovered.append(
            ExpectedResource(
                resource_type=ResourceType.AVATAR_BACKGROUND,
                resource_id=directory.name,
                owner_user_id=None,
                visibility=ResourceVisibility.SYSTEM_PUBLIC,
                metadata={
                    "label": _read_label(directory, directory.name),
                    "image": images[0].name,
                },
                source=source,
            )
        )
    report["source_counts"][source] = len(discovered)
    return discovered


def _discover_mascots(
    root: Path,
    report: dict[str, Any],
) -> list[ExpectedResource]:
    source = "avatar_mascots"
    if not root.is_dir():
        _record_source_issue(
            report,
            source=source,
            resource_id=None,
            reason=f"source directory is unavailable: {root}",
        )
        return []

    discovered: list[ExpectedResource] = []
    directory_ids = {
        directory.name
        for directory in root.iterdir()
        if directory.is_dir() and not directory.name.startswith(".")
    }
    for mascot_id in sorted(directory_ids | _BUILTIN_MASCOT_IDS):
        directory = root / mascot_id
        is_builtin = mascot_id in _BUILTIN_MASCOT_IDS
        model_path = directory / _MASCOT_MODEL
        if not is_builtin and (
            not model_path.is_file() or model_path.stat().st_size <= 0
        ):
            _record_source_issue(
                report,
                source=source,
                resource_id=mascot_id,
                reason="mascot model.vrm is missing or empty",
            )
            continue
        discovered.append(
            ExpectedResource(
                resource_type=ResourceType.AVATAR_MASCOT,
                resource_id=mascot_id,
                owner_user_id=None,
                visibility=ResourceVisibility.SYSTEM_PUBLIC,
                metadata={
                    "label": _read_label(directory, mascot_id),
                    "builtin": is_builtin,
                },
                source=source,
            )
        )
    report["source_counts"][source] = len(discovered)
    return discovered


def _resolve_speaker_reference(reference: str, assets_dir: Path) -> Path | None:
    relative = Path(reference)
    if relative.is_absolute() or ".." in relative.parts:
        return None
    parts = relative.parts[1:] if relative.parts[:1] == ("assets",) else relative.parts
    return assets_dir.joinpath(*parts)


def _discover_indextts_speakers(
    speaker_json: Path,
    assets_dir: Path,
    report: dict[str, Any],
) -> list[ExpectedResource]:
    source = "indextts_speakers"
    try:
        payload = json.loads(speaker_json.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        _record_source_issue(
            report,
            source=source,
            resource_id=None,
            reason=f"speaker catalog is unavailable or invalid: {exc}",
        )
        return []
    if not isinstance(payload, dict):
        _record_source_issue(
            report,
            source=source,
            resource_id=None,
            reason="speaker catalog must be a JSON object",
        )
        return []

    discovered: list[ExpectedResource] = []
    for voice_id, raw_references in sorted(payload.items()):
        if (
            not isinstance(voice_id, str)
            or not voice_id.strip()
            or not isinstance(raw_references, list)
            or not raw_references
            or any(not isinstance(item, str) or not item for item in raw_references)
        ):
            _record_source_issue(
                report,
                source=source,
                resource_id=str(voice_id),
                reason="speaker entry must contain at least one reference path",
            )
            continue
        references = [
            _resolve_speaker_reference(item, assets_dir) for item in raw_references
        ]
        if any(
            path is None or not path.is_file() or path.stat().st_size <= 0
            for path in references
        ):
            _record_source_issue(
                report,
                source=source,
                resource_id=voice_id,
                reason="one or more speaker reference files are unavailable",
            )
            continue
        discovered.append(
            ExpectedResource(
                resource_type=ResourceType.CUSTOM_VOICE,
                resource_id=voice_id.strip(),
                owner_user_id=None,
                visibility=ResourceVisibility.SYSTEM_PUBLIC,
                metadata={"provider": "indextts"},
                source=source,
            )
        )
    report["source_counts"][source] = len(discovered)
    return discovered


def discover_resources(
    sources: MigrationSources,
    admin: UserRecord,
    report: dict[str, Any],
) -> dict[tuple[ResourceType, str], ExpectedResource]:
    resources = [
        *_discover_projects(sources.projects_dir, admin, report),
        *_discover_characters(sources.avatar_dir, report),
        *_discover_backgrounds(sources.backgrounds_dir, report),
        *_discover_mascots(sources.mascots_dir, report),
        *_discover_indextts_speakers(
            sources.indextts_speaker_json,
            sources.indextts_assets_dir,
            report,
        ),
    ]
    return {resource.key: resource for resource in resources}


def _select_bootstrap_admin(users: UserRepository) -> tuple[UserRecord, list[str]]:
    candidates = [
        user
        for user in users.list()
        if user.role is AccountRole.ADMIN
        and user.account_type is AccountType.FORMAL
        and not user.disabled
        and user.created_by is None
    ]
    if not candidates:
        raise MigrationPrerequisiteError(
            "an enabled bootstrap formal administrator is required"
        )
    candidates.sort(key=lambda user: (user.created_at, user.id))
    return candidates[0], [user.id for user in candidates[1:]]


def _matches_expected(
    existing: ResourceRecord,
    expected: ExpectedResource,
) -> bool:
    return (
        existing.owner_user_id == expected.owner_user_id
        and existing.visibility is expected.visibility
    )


def _reconcile_resources(
    resources: ResourceRepository,
    expected_resources: dict[tuple[ResourceType, str], ExpectedResource],
    *,
    dry_run: bool,
    report: dict[str, Any],
) -> None:
    for key in sorted(expected_resources, key=lambda item: (item[0].value, item[1])):
        expected = expected_resources[key]
        reference = _resource_ref(expected.resource_type, expected.resource_id)
        existing = resources.get(*key)
        if existing is not None:
            if _matches_expected(existing, expected):
                report["resources"]["unchanged"].append(reference)
            else:
                report["resources"]["conflicts"].append(
                    {
                        **reference,
                        "desired_owner_user_id": expected.owner_user_id,
                        "desired_visibility": expected.visibility.value,
                        "existing_owner_user_id": existing.owner_user_id,
                        "existing_visibility": existing.visibility.value,
                    }
                )
            continue
        if dry_run:
            report["resources"]["would_register"].append(reference)
            continue
        try:
            resources.register(
                resource_type=expected.resource_type,
                resource_id=expected.resource_id,
                owner_user_id=expected.owner_user_id,
                visibility=expected.visibility,
                metadata=expected.metadata,
            )
        except ResourceConflictError:
            existing = resources.get(*key)
            report["resources"]["conflicts"].append(
                {
                    **reference,
                    "desired_owner_user_id": expected.owner_user_id,
                    "desired_visibility": expected.visibility.value,
                    "existing_owner_user_id": (
                        existing.owner_user_id if existing is not None else None
                    ),
                    "existing_visibility": (
                        existing.visibility.value if existing is not None else None
                    ),
                    "reason": "concurrent registration conflict",
                }
            )
        else:
            report["resources"]["registered"].append(reference)


def _report_registry_without_source(
    resources: ResourceRepository,
    expected_resources: dict[tuple[ResourceType, str], ExpectedResource],
    report: dict[str, Any],
) -> None:
    for resource_type in ResourceType:
        for record in resources.list_by_type(resource_type):
            key = record.resource_type, record.resource_id
            should_reconcile = (
                record.resource_type is ResourceType.PROJECT
                or record.visibility is ResourceVisibility.SYSTEM_PUBLIC
            )
            if should_reconcile and key not in expected_resources:
                report["resources"]["registry_without_source"].append(
                    _resource_ref(record.resource_type, record.resource_id)
                )


def _default_resource_record(
    resources: ResourceRepository,
    expected_resources: dict[tuple[ResourceType, str], ExpectedResource],
    resource_type: ResourceType,
    resource_id: str,
    *,
    dry_run: bool,
) -> ResourceRecord | ExpectedResource | None:
    existing = resources.get(resource_type, resource_id)
    if existing is not None:
        return existing
    if dry_run:
        return expected_resources.get((resource_type, resource_id))
    return None


def _formal_account_can_read(
    user: UserRecord,
    resource: ResourceRecord | ExpectedResource,
) -> bool:
    return (
        user.role is AccountRole.ADMIN
        or resource.owner_user_id == user.id
        or resource.visibility is ResourceVisibility.SYSTEM_PUBLIC
    )


def _reconcile_formal_defaults(
    database: AuthDatabase,
    users: UserRepository,
    resources: ResourceRepository,
    expected_resources: dict[tuple[ResourceType, str], ExpectedResource],
    *,
    dry_run: bool,
    report: dict[str, Any],
) -> None:
    desired = (
        _DEFAULT_PROJECT_ID,
        _DEFAULT_CHARACTER_ID,
        _DEFAULT_VOICE_PROVIDER,
        _DEFAULT_VOICE_ID,
        _DEFAULT_MASCOT_ID,
        _DEFAULT_BACKGROUND_ID,
    )
    required_resources = (
        (ResourceType.PROJECT, _DEFAULT_PROJECT_ID),
        (ResourceType.AVATAR_CHARACTER, _DEFAULT_CHARACTER_ID),
        (ResourceType.CUSTOM_VOICE, _DEFAULT_VOICE_ID),
    )
    for user in users.list():
        if user.account_type is not AccountType.FORMAL:
            continue
        with database.transaction() as connection:
            existing = connection.execute(
                "SELECT * FROM account_defaults WHERE user_id = ?",
                (user.id,),
            ).fetchone()
        if existing is not None:
            report["defaults"]["preserved"].append(
                {"user_id": user.id, "reason": "defaults already exist"}
            )
            continue

        inaccessible: list[dict[str, str]] = []
        for resource_type, resource_id in required_resources:
            resource = _default_resource_record(
                resources,
                expected_resources,
                resource_type,
                resource_id,
                dry_run=dry_run,
            )
            if resource is None or not _formal_account_can_read(user, resource):
                inaccessible.append(_resource_ref(resource_type, resource_id))
        if inaccessible:
            report["defaults"]["skipped"].append(
                {
                    "user_id": user.id,
                    "reason": "one or more defaults are missing or inaccessible",
                    "resources": inaccessible,
                }
            )
            continue

        entry = {
            "user_id": user.id,
            "project_id": desired[0],
            "character_id": desired[1],
            "voice_provider": desired[2],
            "voice_id": desired[3],
            "mascot_id": desired[4],
            "background_id": desired[5],
        }
        if dry_run:
            report["defaults"]["would_create"].append(entry)
            continue
        with database.transaction(write=True) as connection:
            inserted = connection.execute(
                """
                INSERT OR IGNORE INTO account_defaults(
                    user_id, project_id, character_id, voice_provider, voice_id,
                    mascot_id, background_id
                ) VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (user.id, *desired),
            ).rowcount
        target = "created" if inserted else "preserved"
        report["defaults"][target].append(entry)


def _record_migration_marker(
    database: AuthDatabase,
    admin: UserRecord,
    report: dict[str, Any],
) -> None:
    details = json.dumps(
        {
            "name": _MIGRATION_NAME,
            "bootstrap_admin_id": admin.id,
            "source_counts": report["source_counts"],
        },
        separators=(",", ":"),
        sort_keys=True,
    )
    with database.transaction(write=True) as connection:
        inserted = connection.execute(
            """
            INSERT OR IGNORE INTO schema_migrations(version, details_json)
            VALUES (?, ?)
            """,
            (_MIGRATION_VERSION, details),
        ).rowcount
    report["migration"]["marker_created"] = bool(inserted)


def migrate_account_resources(
    *,
    database: AuthDatabase,
    sources: MigrationSources,
    dry_run: bool,
) -> dict[str, Any]:
    report = _new_report(dry_run=dry_run)
    users = UserRepository(database)
    resources = ResourceRepository(database)
    admin, additional_bootstrap_admins = _select_bootstrap_admin(users)
    report["bootstrap_admin"] = {
        "id": admin.id,
        "username": admin.username,
    }
    if additional_bootstrap_admins:
        _record_source_issue(
            report,
            source="accounts",
            resource_id=None,
            reason=(
                "multiple bootstrap administrators found; selected oldest and left "
                f"others unchanged: {', '.join(additional_bootstrap_admins)}"
            ),
        )

    expected_resources = discover_resources(sources, admin, report)
    _reconcile_resources(
        resources,
        expected_resources,
        dry_run=dry_run,
        report=report,
    )
    _report_registry_without_source(resources, expected_resources, report)
    _reconcile_formal_defaults(
        database,
        users,
        resources,
        expected_resources,
        dry_run=dry_run,
        report=report,
    )
    if not dry_run:
        _record_migration_marker(database, admin, report)
    if report["source_issues"] or report["resources"]["conflicts"]:
        report["status"] = "needs_review"
    return report


def _build_parser() -> argparse.ArgumentParser:
    config = get_tts_config()
    parser = argparse.ArgumentParser(
        description="Migrate and reconcile legacy account resource ownership",
    )
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--report", type=Path)
    parser.add_argument(
        "--database",
        type=Path,
        default=Path(config.auth_database_path),
    )
    parser.add_argument(
        "--projects-dir",
        type=Path,
        default=Path(os.getenv("BRAIN_PROJECTS_DIR", "/brain-data/projects")),
    )
    parser.add_argument(
        "--avatar-dir",
        type=Path,
        default=Path(config.avatar_assets_dir),
    )
    parser.add_argument(
        "--backgrounds-dir",
        type=Path,
        default=Path(config.avatar_backgrounds_dir),
    )
    parser.add_argument(
        "--mascots-dir",
        type=Path,
        default=Path(config.avatar_mascots_dir),
    )
    parser.add_argument(
        "--indextts-speaker-json",
        type=Path,
        default=Path(
            os.getenv(
                "INDEXTTS_SPEAKER_JSON",
                "/indextts-assets/speaker.json",
            )
        ),
    )
    parser.add_argument(
        "--indextts-assets-dir",
        type=Path,
        default=Path(os.getenv("INDEXTTS_ASSETS_DIR", "/indextts-assets")),
    )
    return parser


def _emit_report(report: dict[str, Any], destination: Path | None) -> None:
    rendered = json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True)
    print(rendered)
    if destination is not None:
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_text(f"{rendered}\n", encoding="utf-8")


def main() -> int:
    args = _build_parser().parse_args()
    database = AuthDatabase(args.database)
    database.initialize()
    sources = MigrationSources(
        projects_dir=args.projects_dir,
        avatar_dir=args.avatar_dir,
        backgrounds_dir=args.backgrounds_dir,
        mascots_dir=args.mascots_dir,
        indextts_speaker_json=args.indextts_speaker_json,
        indextts_assets_dir=args.indextts_assets_dir,
    )
    try:
        report = migrate_account_resources(
            database=database,
            sources=sources,
            dry_run=args.dry_run,
        )
    except MigrationPrerequisiteError as exc:
        report = _new_report(dry_run=args.dry_run)
        report["status"] = "error"
        report["error"] = str(exc)
        _emit_report(report, args.report)
        return 1
    _emit_report(report, args.report)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
