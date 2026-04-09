"""Tests for parse_identity() in knowledge.workspace."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

import pytest

from knowledge.workspace import parse_identity, _IDENTITY_DEFAULTS


@pytest.fixture()
def workspace_tmp(tmp_path: Path) -> Path:
    """Create a minimal workspace with IDENTITY.md."""
    ws = tmp_path / "workspace"
    ws.mkdir()
    for subdir in ("memory", "personas", "knowledge"):
        (ws / subdir).mkdir()
    return ws


def _write_identity(ws: Path, content: str) -> None:
    (ws / "IDENTITY.md").write_text(content, encoding="utf-8")


def _mock_paths(ws: Path, persona_id: str | None = None):
    """Return a dict matching resolve_core_document_paths output."""
    return {"identity": ws / "IDENTITY.md"}


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


def test_parse_identity_returns_defaults_when_file_missing(workspace_tmp: Path):
    with patch(
        "personas.personas.resolve_core_document_paths",
        return_value={"identity": workspace_tmp / "IDENTITY.md"},
    ):
        result = parse_identity("default", None)

    assert result == _IDENTITY_DEFAULTS


def test_parse_identity_extracts_fields_from_markdown(workspace_tmp: Path):
    _write_identity(
        workspace_tmp,
        "# IDENTITY\n\n## 基本資訊\n- name: 小V\n- emoji: 🤖\n- theme: professional\n\n## 說明\n- 其他\n",
    )

    with patch(
        "personas.personas.resolve_core_document_paths",
        return_value=_mock_paths(workspace_tmp),
    ):
        result = parse_identity("default", None)

    assert result == {"name": "小V", "emoji": "🤖", "theme": "professional"}


def test_parse_identity_partial_fields_use_defaults(workspace_tmp: Path):
    _write_identity(
        workspace_tmp,
        "# IDENTITY\n\n## 基本資訊\n- name: Alice\n\n## 其他\n- emoji: 🎉\n",
    )

    with patch(
        "personas.personas.resolve_core_document_paths",
        return_value=_mock_paths(workspace_tmp),
    ):
        result = parse_identity("default", None)

    # emoji outside 基本資訊 section should NOT be picked up
    assert result == {"name": "Alice", "emoji": "🤖", "theme": "default"}


def test_parse_identity_persona_override(workspace_tmp: Path):
    """When persona has its own IDENTITY.md, parse_identity returns overridden values."""
    persona_dir = workspace_tmp / "personas" / "doctor01"
    persona_dir.mkdir(parents=True)
    persona_identity = persona_dir / "IDENTITY.md"
    persona_identity.write_text(
        "# IDENTITY\n\n## 基本資訊\n- name: Dr. Wang\n- emoji: 🩺\n- theme: medical\n",
        encoding="utf-8",
    )

    with patch(
        "personas.personas.resolve_core_document_paths",
        return_value={"identity": persona_identity},
    ):
        result = parse_identity("default", "doctor01")

    assert result == {"name": "Dr. Wang", "emoji": "🩺", "theme": "medical"}


def test_parse_identity_ignores_unknown_keys(workspace_tmp: Path):
    _write_identity(
        workspace_tmp,
        "# IDENTITY\n\n## 基本資訊\n- name: Bot\n- color: red\n- emoji: 🎯\n- theme: dark\n",
    )

    with patch(
        "personas.personas.resolve_core_document_paths",
        return_value=_mock_paths(workspace_tmp),
    ):
        result = parse_identity("default", None)

    assert "color" not in result
    assert result == {"name": "Bot", "emoji": "🎯", "theme": "dark"}
