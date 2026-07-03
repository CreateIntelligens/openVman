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

    assert result["committed"] == ["knowledge/qa/faq.md"]
    content = (workspace / "knowledge" / "qa" / "faq.md").read_text(encoding="utf-8")
    assert "LLM_CLEANED" not in content
    assert "## Q1" in content
    assert '"hidden": true' in content
    assert get_document_meta("knowledge/qa/faq.md", "default").get("source_type") == "qa"

    # 採納即進樹：QA CSV 轉出的文件自動成為問答樹節點
    import knowledge.qa_nodes as qa_nodes

    nodes = qa_nodes.list_nodes("default")
    matching = [n for n in nodes.values() if n["label"] == "faq"]
    assert len(matching) == 1
    entries = {e["question"]: e for e in matching[0]["qa_entries"]}
    assert set(entries) == {"Q1", "Q2"}
    assert entries["Q1"]["source_path"] == "knowledge/qa/faq.md"
    assert entries["Q2"]["hidden"] is True


def test_commit_plain_csv_still_normalizes_as_upload(workspace: Path):
    raw_dir = workspace / "raw"
    raw_dir.mkdir(parents=True, exist_ok=True)
    (raw_dir / "table.csv").write_bytes(b"name,age\nAlice,20\n")

    result = commit_raw_documents("default")

    assert result["committed"] == ["knowledge/table.md"]
    content = (workspace / "knowledge" / "table.md").read_text(encoding="utf-8")
    assert "LLM_CLEANED" in content
    assert get_document_meta("knowledge/table.md", "default").get("source_type") == "upload"


def test_commit_archives_original_and_records_provenance(workspace):
    raw_dir = workspace / "raw"
    raw_dir.mkdir(parents=True, exist_ok=True)
    faq_csv = raw_dir / "faq.csv"
    faq_csv.write_bytes("問題,答案,display\nQ1,A1,\n".encode("utf-8"))
    
    result = commit_raw_documents("default")
    
    assert not faq_csv.exists()
    archive_file = workspace / "archive" / "originals" / "faq.csv"
    assert archive_file.exists()
    assert archive_file.read_bytes() == "問題,答案,display\nQ1,A1,\n".encode("utf-8")
    
    from knowledge.doc_meta import get_document_meta
    meta = get_document_meta("knowledge/qa/faq.md", "default")
    assert meta["origin_path"] == "archive/originals/faq.csv"
    import hashlib
    expected_hash = hashlib.sha256("問題,答案,display\nQ1,A1,\n".encode("utf-8")).hexdigest()
    assert meta["origin_hash"] == expected_hash


def test_commit_same_name_twice_keeps_both_archives(workspace):
    raw_dir = workspace / "raw"
    raw_dir.mkdir(parents=True, exist_ok=True)
    
    # First commit
    faq_csv = raw_dir / "faq.csv"
    faq_csv.write_bytes("問題,答案,display\nQ1,A1,\n".encode("utf-8"))
    commit_raw_documents("default")
    
    # Second commit
    faq_csv.write_bytes("問題,答案,display\nQ2,A2,\n".encode("utf-8"))
    commit_raw_documents("default")
    
    # Verify both archived files exist in archive/originals/
    archive_dir = workspace / "archive" / "originals"
    archived_files = list(archive_dir.glob("faq*.csv"))
    assert len(archived_files) == 2
    for f in archived_files:
        assert f.stat().st_size > 0


def test_list_raw_files(workspace):
    from knowledge.knowledge_admin import list_raw_files
    raw_dir = workspace / "raw"
    raw_dir.mkdir(parents=True, exist_ok=True)
    
    (raw_dir / "b.pdf").write_text("pdf", encoding="utf-8")
    sub_dir = raw_dir / "sub"
    sub_dir.mkdir(parents=True, exist_ok=True)
    (sub_dir / "a.txt").write_text("txt", encoding="utf-8")
    
    files = list_raw_files("default")
    assert files == ["b.pdf", "sub/a.txt"]


def test_commit_reports_per_file_progress(workspace, monkeypatch):
    raw_dir = workspace / "raw"
    raw_dir.mkdir(parents=True, exist_ok=True)
    
    (raw_dir / "a.csv").write_bytes("問題,答案,display\nQ1,A1,\n".encode("utf-8"))
    (raw_dir / "b.csv").write_bytes("問題,答案,display\nQ2,A2,\n".encode("utf-8"))
    
    events: list[tuple[str, str]] = []
    
    commit_raw_documents("default", on_progress=lambda p, s: events.append((p, s)))
    
    # Verify events
    # Each file should report "normalizing" then "committed"
    assert ("a.csv", "normalizing") in events
    assert ("a.csv", "committed") in events
    assert ("b.csv", "normalizing") in events
    assert ("b.csv", "committed") in events


def test_commit_reports_skipped_files(workspace, monkeypatch):
    raw_dir = workspace / "raw"
    raw_dir.mkdir(parents=True, exist_ok=True)
    
    (raw_dir / "unsupported.bin").write_bytes(b"\x00\x01")
    
    events: list[tuple[str, str]] = []
    commit_raw_documents("default", on_progress=lambda p, s: events.append((p, s)))
    
    assert ("unsupported.bin", "skipped") in events


@pytest.mark.asyncio
async def test_commit_route_trigger_and_status(workspace, monkeypatch):
    import knowledge.indexer
    monkeypatch.setattr(knowledge.indexer, "rebuild_knowledge_index", lambda project_id="default": {"status": "ok"})
    import memory.embedder
    class FakeEmbedder:
        def encode(self, texts, **kwargs):
            return [[0.1] * 1024 for _ in texts]
    fake_emb = FakeEmbedder()
    monkeypatch.setattr(memory.embedder, "get_embedder", lambda *args, **kwargs: fake_emb)
    monkeypatch.setattr(knowledge.indexer, "get_embedder", lambda *args, **kwargs: fake_emb)

    import threading
    import asyncio
    from knowledge.knowledge_admin import commit_raw_documents
    event = threading.Event()
    orig_commit = commit_raw_documents

    def mock_commit(project_id, on_progress=None):
        print("MOCK COMMIT ENTERED", flush=True)
        event.wait(timeout=5)
        print("MOCK COMMIT EXITING", flush=True)
        return orig_commit(project_id, on_progress)

    import routes.knowledge
    monkeypatch.setattr(routes.knowledge, "commit_raw_documents", mock_commit)

    # Reset jobs state
    from knowledge import commit_jobs
    commit_jobs._JOBS.clear()

    from routes.knowledge import commit_knowledge_raw_route, commit_status_route
    from protocol.schemas import AdminActionRequest
    from fastapi import Response

    # 1. Commit when there are no files
    payload = AdminActionRequest(project_id="default")
    response = Response()
    res = await commit_knowledge_raw_route(payload, response)
    assert response.status_code == 200
    assert res["status"] == "nothing_to_commit"

    # 2. Add a file
    raw_dir = workspace / "raw"
    raw_dir.mkdir(parents=True, exist_ok=True)
    (raw_dir / "a.csv").write_bytes("問題,答案,display\nQ1,A1,\n".encode("utf-8"))

    # 3. Commit normally
    response = Response()
    res = await commit_knowledge_raw_route(payload, response)
    assert response.status_code == 202
    assert res["status"] == "started"
    assert res["job"]["state"] == "running"

    # 4. Duplicate commit while running
    response = Response()
    res = await commit_knowledge_raw_route(payload, response)
    assert response.status_code == 200
    assert res["status"] == "already_running"

    # Release mock_commit
    event.set()

    # Wait a bit for the thread to complete
    await asyncio.sleep(0.5)

    # 5. Query status
    status_res = await commit_status_route(project_id="default")
    assert status_res["state"] == "done"




