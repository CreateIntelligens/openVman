"""Persistent per-document metadata for Knowledge Base sources."""

from __future__ import annotations

from datetime import UTC, datetime
import json
from pathlib import Path
from typing import Any

from knowledge.workspace import ensure_workspace_scaffold

DOC_META_FILENAME = ".doc_meta.json"
DEFAULT_SOURCE_TYPE = "upload"
UNSET = object()


def get_doc_meta_path(project_id: str = "default") -> Path:
    return ensure_workspace_scaffold(project_id) / DOC_META_FILENAME


def load_doc_meta(project_id: str = "default") -> dict[str, dict[str, Any]]:
    path = get_doc_meta_path(project_id)
    if not path.exists():
        return {}
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    if not isinstance(raw, dict):
        return {}

    result: dict[str, dict[str, Any]] = {}
    for relative_path, value in raw.items():
        if not isinstance(relative_path, str) or not isinstance(value, dict):
            continue
        result[relative_path] = _normalize_entry(value)
    return result


def save_doc_meta(metadata: dict[str, dict[str, Any]], project_id: str = "default") -> None:
    path = get_doc_meta_path(project_id)
    cleaned = {
        relative_path: _normalize_entry(value)
        for relative_path, value in sorted(metadata.items())
        if isinstance(relative_path, str) and isinstance(value, dict)
    }
    path.write_text(
        json.dumps(cleaned, ensure_ascii=False, indent=2, sort_keys=True),
        encoding="utf-8",
    )


def get_document_meta(relative_path: str, project_id: str = "default") -> dict[str, Any]:
    metadata = load_doc_meta(project_id)
    entry = metadata.get(relative_path, {})
    return _resolved_entry(entry)


def upsert_document_meta(
    relative_path: str,
    project_id: str = "default",
    *,
    source_type: str | object = UNSET,
    source_url: str | None | object = UNSET,
    enabled: bool | object = UNSET,
    created_at: str | object = UNSET,
) -> dict[str, Any]:
    metadata = load_doc_meta(project_id)
    current = dict(metadata.get(relative_path, {}))

    if source_type is not UNSET:
        current["source_type"] = str(source_type).strip() or DEFAULT_SOURCE_TYPE
    if source_url is not UNSET:
        cleaned_url = str(source_url).strip() if isinstance(source_url, str) else ""
        if cleaned_url:
            current["source_url"] = cleaned_url
        else:
            current.pop("source_url", None)
    if enabled is not UNSET:
        current["enabled"] = bool(enabled)
    if created_at is not UNSET:
        current["created_at"] = str(created_at).strip()

    resolved = _resolved_entry(current)
    current["source_type"] = resolved["source_type"]
    current["enabled"] = resolved["enabled"]
    current["created_at"] = resolved["created_at"]
    if resolved["source_url"]:
        current["source_url"] = resolved["source_url"]
    else:
        current.pop("source_url", None)

    metadata[relative_path] = _normalize_entry(current)
    save_doc_meta(metadata, project_id)
    return resolved


def touch_document_meta(relative_path: str, project_id: str = "default") -> dict[str, Any]:
    return upsert_document_meta(relative_path, project_id)


def delete_document_meta(relative_path: str, project_id: str = "default") -> None:
    metadata = load_doc_meta(project_id)
    if relative_path in metadata:
        metadata.pop(relative_path, None)
        save_doc_meta(metadata, project_id)


def move_document_meta(source_path: str, target_path: str, project_id: str = "default") -> None:
    metadata = load_doc_meta(project_id)
    if source_path not in metadata:
        return
    metadata[target_path] = metadata.pop(source_path)
    save_doc_meta(metadata, project_id)


def list_disabled_document_paths(project_id: str = "default") -> set[str]:
    return {
        relative_path
        for relative_path, value in load_doc_meta(project_id).items()
        if _resolved_entry(value)["enabled"] is False
    }


def _normalize_entry(value: dict[str, Any]) -> dict[str, Any]:
    entry: dict[str, Any] = {}
    source_type = str(value.get("source_type", "")).strip()
    if source_type:
        entry["source_type"] = source_type
    source_url = value.get("source_url")
    if isinstance(source_url, str) and source_url.strip():
        entry["source_url"] = source_url.strip()
    if "enabled" in value:
        entry["enabled"] = bool(value.get("enabled"))
    created_at = value.get("created_at")
    if isinstance(created_at, str) and created_at.strip():
        entry["created_at"] = created_at.strip()
    return entry


def _resolved_entry(value: dict[str, Any]) -> dict[str, Any]:
    normalized = _normalize_entry(value)
    created_at = normalized.get("created_at") or _now_iso()
    return {
        "source_type": normalized.get("source_type") or DEFAULT_SOURCE_TYPE,
        "source_url": normalized.get("source_url") or None,
        "enabled": bool(normalized.get("enabled", True)),
        "created_at": created_at,
    }


def _now_iso() -> str:
    return datetime.now(UTC).replace(tzinfo=None).isoformat(timespec="seconds")
