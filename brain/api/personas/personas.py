"""Persona discovery and workspace overlay helpers."""

from __future__ import annotations

import re
import shutil
from pathlib import Path
from typing import Any

from knowledge import workspace

PERSONA_CORE_KEYS_TO_FILES: dict[str, str] = {
    "soul": "SOUL.md",
    "agents": "AGENTS.md",
    "tools": "TOOLS.md",
    "memory": "MEMORY.md",
    "identity": "IDENTITY.md",
}
PERSONA_CORE_KEYS = frozenset(PERSONA_CORE_KEYS_TO_FILES.keys())
PERSONA_CORE_FILENAMES = frozenset(PERSONA_CORE_KEYS_TO_FILES.values())
_PERSONA_ID_RE = re.compile(r"^[A-Za-z0-9._-]{1,64}$")


def normalize_persona_id(persona_id: str | None) -> str:
    text = (persona_id or "").strip() or "default"
    if not _PERSONA_ID_RE.match(text):
        raise ValueError("persona_id 格式不合法")
    return text


def get_persona_directory(persona_id: str | None, project_id: str = "default") -> Path:
    normalized = normalize_persona_id(persona_id)
    ws = workspace.get_workspace_root(project_id)
    return ws / "personas" / normalized


def resolve_core_document_paths(persona_id: str | None = None, project_id: str = "default") -> dict[str, Path]:
    normalized = normalize_persona_id(persona_id)
    resolved = dict(workspace.get_core_documents(project_id))
    if normalized == "default":
        return resolved

    persona_dir = get_persona_directory(normalized, project_id)
    for key, filename in PERSONA_CORE_KEYS_TO_FILES.items():
        override = persona_dir / filename
        if override.exists():
            resolved[key] = override
    return resolved


def list_personas(project_id: str = "default") -> list[dict[str, Any]]:
    workspace.ensure_workspace_scaffold(project_id)
    ws = workspace.get_workspace_root(project_id)
    personas = [_build_default_persona_summary(project_id)]
    personas_root = ws / "personas"
    personas_root.mkdir(parents=True, exist_ok=True)

    for path in sorted(personas_root.iterdir()):
        if not path.is_dir():
            continue
        soul_path = path / "SOUL.md"
        if not soul_path.exists():
            continue
        persona_id = normalize_persona_id(path.name)
        personas.append(_build_persona_summary(persona_id, soul_path, is_default=False, project_id=project_id))
    return personas


def create_persona_scaffold(persona_id: str, label: str = "", project_id: str = "default") -> dict[str, Any]:
    normalized = normalize_persona_id(_require_text(persona_id, "persona_id"))
    if normalized == "default":
        raise ValueError("default persona 已存在，無法重建")

    persona_dir = get_persona_directory(normalized, project_id)
    soul_path = persona_dir / "SOUL.md"
    if soul_path.exists():
        raise ValueError("persona 已存在")

    persona_dir.mkdir(parents=True, exist_ok=True)
    display_name = label.strip() or normalized
    files = _build_persona_files(display_name)
    for filename, content in files.items():
        (persona_dir / filename).write_text(content, encoding="utf-8")

    ws = workspace.get_workspace_root(project_id)
    persona = _build_persona_summary(normalized, persona_dir / "SOUL.md", is_default=False, project_id=project_id)
    return {
        "status": "ok",
        "persona": persona,
        "files": [
            (persona_dir / filename).relative_to(ws).as_posix()
            for filename in files
        ],
    }


def delete_persona_scaffold(persona_id: str, project_id: str = "default") -> dict[str, Any]:
    normalized = normalize_persona_id(_require_text(persona_id, "persona_id"))
    if normalized == "default":
        raise ValueError("default persona 不可刪除")

    persona_dir = get_persona_directory(normalized, project_id)
    if not persona_dir.exists():
        raise ValueError("persona 不存在")

    shutil.rmtree(persona_dir)
    return {
        "status": "ok",
        "persona_id": normalized,
    }


def clone_persona_scaffold(
    source_persona_id: str,
    target_persona_id: str,
    project_id: str = "default",
) -> dict[str, Any]:
    source_paths = resolve_core_document_paths(source_persona_id, project_id)
    target_id = normalize_persona_id(_require_text(target_persona_id, "target_persona_id"))
    if target_id == "default":
        raise ValueError("不可覆蓋 default persona")

    target_dir = get_persona_directory(target_id, project_id)
    if target_dir.exists():
        raise ValueError("target persona 已存在")

    ws = workspace.get_workspace_root(project_id)
    target_dir.mkdir(parents=True, exist_ok=True)
    copied_files: list[str] = []
    for key, source_path in source_paths.items():
        if key not in PERSONA_CORE_KEYS:
            continue
        target_path = target_dir / source_path.name
        shutil.copyfile(source_path, target_path)
        copied_files.append(target_path.relative_to(ws).as_posix())

    persona = _build_persona_summary(target_id, target_dir / "SOUL.md", is_default=False, project_id=project_id)
    return {
        "status": "ok",
        "persona": persona,
        "files": copied_files,
        "source_persona_id": normalize_persona_id(source_persona_id),
    }


def extract_persona_id_from_relative_path(relative_path: str) -> str:
    parts = Path(relative_path).parts
    if len(parts) >= 2 and parts[0] == "personas":
        return normalize_persona_id(parts[1])
    return "global"


def is_persona_core_relative_path(relative_path: str) -> bool:
    parts = Path(relative_path).parts
    return (
        len(parts) == 3
        and parts[0] == "personas"
        and parts[2] in PERSONA_CORE_FILENAMES
    )


def _build_default_persona_summary(project_id: str = "default") -> dict[str, Any]:
    core_docs = workspace.get_core_documents(project_id)
    soul_path = core_docs["soul"]
    return _build_persona_summary(
        "default", soul_path, is_default=True, label="default", project_id=project_id,
    )


def _require_text(value: str | None, field_name: str) -> str:
    text = (value or "").strip()
    if not text:
        raise ValueError(f"{field_name} 不可為空")
    return text


def _build_persona_summary(
    persona_id: str,
    soul_path: Path,
    *,
    is_default: bool,
    label: str = "",
    project_id: str = "default",
) -> dict[str, Any]:
    ws = workspace.get_workspace_root(project_id)
    return {
        "persona_id": persona_id,
        "label": label or _extract_heading_or_name(soul_path, persona_id),
        "path": soul_path.relative_to(ws).as_posix(),
        "preview": _read_preview(soul_path),
        "is_default": is_default,
    }


def _build_persona_files(label: str) -> dict[str, str]:
    return {
        filename: _PERSONA_TEMPLATES[key](label)
        for key, filename in PERSONA_CORE_KEYS_TO_FILES.items()
    }


def _extract_heading_or_name(path: Path, fallback: str) -> str:
    """Extract the first heading text from a markdown file, or return fallback."""
    for line in path.read_text(encoding="utf-8-sig").splitlines():
        stripped = line.strip()
        if stripped.startswith("#"):
            heading = stripped.lstrip("#").strip()
            if heading:
                return heading
    return fallback


def _read_preview(path: Path, limit: int = 120) -> str:
    snippet = " ".join(path.read_text(encoding="utf-8-sig").split())
    return snippet[:limit]


def _simple_persona_template(section: str, description: str) -> callable:
    """Return a template builder for a standard persona override section."""
    def builder(label: str) -> str:
        return (
            f"# {label} Persona {section}\n\n"
            f"- {description}\n"
            f"- 若沒有特別覆蓋，系統仍會沿用全域 {section} 設定。\n"
        )
    return builder


_PERSONA_TEMPLATES: dict[str, callable] = {
    "soul": lambda label: f"""# {label} Persona SOUL

你是「{label}」這個 persona 的對話核心。

## 角色定位
- 這個 persona 會覆蓋預設的 SOUL 設定。
- 保留 openVman Brain 的誠實與可執行回覆原則。

## 語氣要求
- 先說重點，再補充必要細節。
- 若資訊不足，直接指出缺口，不要編造。
""",
    "agents": _simple_persona_template(
        "AGENTS", "在這裡定義 persona 專屬的工作流程或轉派規則。",
    ),
    "tools": _simple_persona_template(
        "TOOLS", "在這裡記錄 persona 專屬工具、參數限制或使用規範。",
    ),
    "memory": _simple_persona_template(
        "MEMORY", "在這裡記錄 persona 的長期核心記憶或固定事實。",
    ),
    "identity": lambda label: f"""# {label} Persona IDENTITY

## 基本資訊
- name: {label}
- theme: default

## 說明
- 此檔定義 {label} persona 的外部身份與視覺主題。
- 若沒有特別覆蓋，系統仍會沿用全域 IDENTITY 設定。
""",
}
