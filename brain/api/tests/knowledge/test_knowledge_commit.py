from __future__ import annotations

import sys
from pathlib import Path

import pytest

API_ROOT = Path(__file__).resolve().parents[1]
if str(API_ROOT) not in sys.path:
    sys.path.insert(0, str(API_ROOT))

import knowledge.normalizer
import knowledge.workspace
from knowledge.doc_meta import get_document_meta
from knowledge.knowledge_admin import commit_raw_documents


@pytest.fixture
def workspace(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> Path:
    root = tmp_path / "workspace"
    monkeypatch.setattr(
        knowledge.workspace, "get_workspace_root", lambda project_id="default": root
    )
    knowledge.workspace.ensure_workspace_scaffold()
    monkeypatch.setattr(
        knowledge.normalizer, "normalize_to_markdown", lambda text: f"LLM_CLEANED\n{text}"
    )
    return root


def test_commit_qa_csv_skips_llm_and_marks_source_type_qa(workspace: Path):
    raw_dir = workspace / "raw"
    raw_dir.mkdir(parents=True, exist_ok=True)
    (raw_dir / "faq.csv").write_bytes("問題,答案,display\nQ1,A1,\nQ2,A2,false\n".encode("utf-8"))

    result = commit_raw_documents("default")

    assert result["committed"] == ["knowledge/faq.md"]
    content = (workspace / "knowledge" / "faq.md").read_text(encoding="utf-8")
    assert "LLM_CLEANED" not in content
    assert "## Q1" in content
    assert '"hidden": true' in content
    assert get_document_meta("knowledge/faq.md", "default").get("source_type") == "qa"


def test_commit_plain_csv_still_normalizes_as_upload(workspace: Path):
    raw_dir = workspace / "raw"
    raw_dir.mkdir(parents=True, exist_ok=True)
    (raw_dir / "table.csv").write_bytes(b"name,age\nAlice,20\n")

    result = commit_raw_documents("default")

    assert result["committed"] == ["knowledge/table.md"]
    content = (workspace / "knowledge" / "table.md").read_text(encoding="utf-8")
    assert "LLM_CLEANED" in content
    assert get_document_meta("knowledge/table.md", "default").get("source_type") == "upload"
