from __future__ import annotations

import importlib
import sys
from pathlib import Path

import pytest

API_ROOT = Path(__file__).resolve().parents[1]
if str(API_ROOT) not in sys.path:
    sys.path.insert(0, str(API_ROOT))


def _import(module_name: str):
    return importlib.import_module(module_name)


def _configure_workspace(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> Path:
    workspace = _import("knowledge.workspace")
    root = tmp_path / "workspace"
    core_documents = {
        "soul": root / "SOUL.md",
        "agents": root / "AGENTS.md",
        "tools": root / "TOOLS.md",
        "memory": root / "MEMORY.md",
        "identity": root / "IDENTITY.md",
    }
    monkeypatch.setattr(workspace, "get_workspace_root", lambda project_id="default": root)
    monkeypatch.setattr(workspace, "get_core_documents", lambda project_id="default": core_documents)
    root.mkdir(parents=True, exist_ok=True)
    (root / "personas").mkdir(parents=True, exist_ok=True)
    core_documents["soul"].write_text("# Global Soul", encoding="utf-8")
    return root


def test_default_persona_has_null_avatar(monkeypatch, tmp_path):
    _configure_workspace(monkeypatch, tmp_path)
    personas = _import("personas.personas")
    items = personas.list_personas("default")
    assert all("avatar_char_id" in p for p in items)
    default = next(p for p in items if p["is_default"])
    assert default["avatar_char_id"] is None


def test_set_and_read_avatar(monkeypatch, tmp_path):
    _configure_workspace(monkeypatch, tmp_path)
    personas = _import("personas.personas")
    personas.create_persona_scaffold("doctor01", "Doctor", "default")
    personas.set_persona_avatar("doctor01", "008", "default")
    items = personas.list_personas("default")
    doctor = next(p for p in items if p["persona_id"] == "doctor01")
    assert doctor["avatar_char_id"] == "008"


def test_clear_avatar_with_none(monkeypatch, tmp_path):
    _configure_workspace(monkeypatch, tmp_path)
    personas = _import("personas.personas")
    personas.create_persona_scaffold("doctor01", "Doctor", "default")
    personas.set_persona_avatar("doctor01", "008", "default")
    personas.set_persona_avatar("doctor01", None, "default")
    items = personas.list_personas("default")
    doctor = next(p for p in items if p["persona_id"] == "doctor01")
    assert doctor["avatar_char_id"] is None


def test_set_avatar_missing_persona_raises(monkeypatch, tmp_path):
    _configure_workspace(monkeypatch, tmp_path)
    personas = _import("personas.personas")
    with pytest.raises(ValueError):
        personas.set_persona_avatar("nope-not-here", "008", "default")
