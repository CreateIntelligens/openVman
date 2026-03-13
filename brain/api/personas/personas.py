"""Persona discovery and workspace overlay helpers."""

from __future__ import annotations

import re
import shutil
from pathlib import Path
from typing import Any

from knowledge import workspace

PERSONA_CORE_FILENAMES = {
    "SOUL.md",
    "AGENTS.md",
    "TOOLS.md",
    "MEMORY.md",
}
PERSONA_CORE_KEYS = {"soul", "agents", "tools", "memory"}
_PERSONA_ID_RE = re.compile(r"^[A-Za-z0-9._-]{1,64}$")


def normalize_persona_id(persona_id: str | None) -> str:
    text = (persona_id or "").strip() or "default"
    if not _PERSONA_ID_RE.match(text):
        raise ValueError("persona_id 格式不合法")
    return text


def get_persona_directory(persona_id: str | None) -> Path:
    normalized = normalize_persona_id(persona_id)
    return workspace.WORKSPACE_ROOT / "personas" / normalized


def resolve_core_document_paths(persona_id: str | None = None) -> dict[str, Path]:
    normalized = normalize_persona_id(persona_id)
    resolved = dict(workspace.CORE_DOCUMENTS)
    if normalized == "default":
        return resolved

    overrides = {
        "soul": get_persona_directory(normalized) / "SOUL.md",
        "agents": get_persona_directory(normalized) / "AGENTS.md",
        "tools": get_persona_directory(normalized) / "TOOLS.md",
        "memory": get_persona_directory(normalized) / "MEMORY.md",
    }
    for key, path in overrides.items():
        if path.exists():
            resolved[key] = path
    return resolved


def list_personas() -> list[dict[str, Any]]:
    workspace.ensure_workspace_scaffold()
    personas = [_build_default_persona_summary()]
    personas_root = workspace.WORKSPACE_ROOT / "personas"
    personas_root.mkdir(parents=True, exist_ok=True)

    for path in sorted(personas_root.iterdir()):
        if not path.is_dir():
            continue
        soul_path = path / "SOUL.md"
        if not soul_path.exists():
            continue
        persona_id = normalize_persona_id(path.name)
        personas.append(_build_persona_summary(persona_id, soul_path, is_default=False))
    return personas


def create_persona_scaffold(persona_id: str, label: str = "") -> dict[str, Any]:
    normalized = normalize_persona_id(_require_text(persona_id, "persona_id"))
    if normalized == "default":
        raise ValueError("default persona 已存在，無法重建")

    persona_dir = get_persona_directory(normalized)
    soul_path = persona_dir / "SOUL.md"
    if soul_path.exists():
        raise ValueError("persona 已存在")

    persona_dir.mkdir(parents=True, exist_ok=True)
    display_name = label.strip() or normalized
    files = _build_persona_files(display_name)
    for filename, content in files.items():
        (persona_dir / filename).write_text(content, encoding="utf-8")

    persona = _get_persona_summary(normalized)
    return {
        "status": "ok",
        "persona": persona,
        "files": [
            (persona_dir / filename).relative_to(workspace.WORKSPACE_ROOT).as_posix()
            for filename in files
        ],
    }


def delete_persona_scaffold(persona_id: str) -> dict[str, Any]:
    normalized = normalize_persona_id(_require_text(persona_id, "persona_id"))
    if normalized == "default":
        raise ValueError("default persona 不可刪除")

    persona_dir = get_persona_directory(normalized)
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
) -> dict[str, Any]:
    source_paths = resolve_core_document_paths(source_persona_id)
    target_id = normalize_persona_id(_require_text(target_persona_id, "target_persona_id"))
    if target_id == "default":
        raise ValueError("不可覆蓋 default persona")

    target_dir = get_persona_directory(target_id)
    if target_dir.exists():
        raise ValueError("target persona 已存在")

    target_dir.mkdir(parents=True, exist_ok=True)
    copied_files: list[str] = []
    for key, source_path in source_paths.items():
        if key not in PERSONA_CORE_KEYS:
            continue
        target_path = target_dir / source_path.name
        shutil.copyfile(source_path, target_path)
        copied_files.append(target_path.relative_to(workspace.WORKSPACE_ROOT).as_posix())

    persona = _get_persona_summary(target_id)
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


def _build_default_persona_summary() -> dict[str, Any]:
    soul_path = workspace.CORE_DOCUMENTS["soul"]
    return _build_persona_summary("default", soul_path, is_default=True)


def _require_text(value: str | None, field_name: str) -> str:
    text = (value or "").strip()
    if not text:
        raise ValueError(f"{field_name} 不可為空")
    return text


def _get_persona_summary(persona_id: str) -> dict[str, Any]:
    normalized = normalize_persona_id(persona_id)
    return next(item for item in list_personas() if item["persona_id"] == normalized)


def _build_persona_summary(
    persona_id: str,
    soul_path: Path,
    *,
    is_default: bool,
) -> dict[str, Any]:
    return {
        "persona_id": persona_id,
        "label": _extract_heading_or_name(soul_path, persona_id),
        "path": soul_path.relative_to(workspace.WORKSPACE_ROOT).as_posix(),
        "preview": _read_preview(soul_path),
        "is_default": is_default,
    }


def _build_persona_files(label: str) -> dict[str, str]:
    return {
        "SOUL.md": _build_soul_template(label),
        "AGENTS.md": _build_agents_template(label),
        "TOOLS.md": _build_tools_template(label),
        "MEMORY.md": _build_memory_template(label),
    }


def _extract_heading_or_name(path: Path, fallback: str) -> str:
    for line in path.read_text(encoding="utf-8-sig").splitlines():
        stripped = line.strip().lstrip("#").strip()
        if stripped:
            return stripped
    return fallback


def _read_preview(path: Path, limit: int = 120) -> str:
    snippet = " ".join(path.read_text(encoding="utf-8-sig").split())
    return snippet[:limit]


def _build_soul_template(label: str) -> str:
    return f"""# {label} Persona SOUL

你是「{label}」這個 persona 的對話核心。

## 角色定位
- 這個 persona 會覆蓋預設的 SOUL 設定。
- 保留 openVman Brain 的誠實與可執行回覆原則。

## 語氣要求
- 先說重點，再補充必要細節。
- 若資訊不足，直接指出缺口，不要編造。
"""


def _build_agents_template(label: str) -> str:
    return f"""# {label} Persona AGENTS

- 在這裡定義 {label} persona 專屬的工作流程或轉派規則。
- 若沒有特別覆蓋，系統仍會沿用全域 AGENTS 設定。
"""


def _build_tools_template(label: str) -> str:
    return f"""# {label} Persona TOOLS

- 在這裡記錄 {label} persona 專屬工具、參數限制或使用規範。
- 若沒有特別覆蓋，系統仍會沿用全域 TOOLS 設定。
"""


def _build_memory_template(label: str) -> str:
    return f"""# {label} Persona MEMORY

- 在這裡記錄 {label} persona 的長期核心記憶或固定事實。
- 若沒有特別覆蓋，系統仍會沿用全域 MEMORY 設定。
"""
