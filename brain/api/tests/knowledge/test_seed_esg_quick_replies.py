from __future__ import annotations

import importlib
import sys
from pathlib import Path

import pytest


@pytest.fixture
def seed_module(monkeypatch: pytest.MonkeyPatch, tmp_path: Path):
    for module_name in list(sys.modules):
        if (
            module_name.startswith("knowledge.")
            or module_name == "knowledge"
            or module_name == "scripts.seed_esg_quick_replies"
        ):
            sys.modules.pop(module_name, None)
    workspace = importlib.import_module("knowledge.workspace")
    root = tmp_path / "workspace"
    monkeypatch.setattr(
        workspace,
        "get_workspace_root",
        lambda project_id="default": root,
    )
    return importlib.import_module("scripts.seed_esg_quick_replies")


def test_seed_is_idempotent_and_preserves_unrelated_entries(seed_module) -> None:
    from knowledge.qa_nodes import get_node, update_node

    first = seed_module.seed_esg_quick_replies()
    assert first["created"] is True
    assert first["quick_reply_count"] == 12

    node = get_node(seed_module.NODE_ID, seed_module.DEFAULT_PROJECT_ID)
    assert node is not None
    update_node(
        seed_module.NODE_ID,
        {
            "qa_entries": node["qa_entries"]
            + [
                {
                    "question": "保留我",
                    "source_path": "knowledge/qa/unrelated.md",
                    "hidden": False,
                    "image_id": None,
                }
            ]
        },
        project_id=seed_module.DEFAULT_PROJECT_ID,
    )

    second = seed_module.seed_esg_quick_replies()
    assert second["created"] is False
    updated = get_node(seed_module.NODE_ID, seed_module.DEFAULT_PROJECT_ID)
    assert updated is not None
    assert [entry["question"] for entry in updated["qa_entries"]] == [
        "保留我",
        *seed_module.QUICK_REPLIES,
    ]
