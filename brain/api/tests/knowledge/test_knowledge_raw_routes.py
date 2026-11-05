"""HTTP behavior of the raw/ import routes: pending list, removal, commit validation."""

from __future__ import annotations

import sys
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

API_ROOT = Path(__file__).resolve().parents[2]
if str(API_ROOT) not in sys.path:
    sys.path.insert(0, str(API_ROOT))

from knowledge.knowledge_admin import qa_document_lock  # noqa: E402
from main import app  # noqa: E402
from routes.knowledge_qa import qa_document_lock as ingest_lock  # noqa: E402


@pytest.fixture
def workspace(monkeypatch, tmp_path) -> Path:
    import knowledge.workspace

    root = tmp_path / "workspace"
    monkeypatch.setattr(knowledge.workspace, "get_workspace_root", lambda project_id="default": root)
    knowledge.workspace.ensure_workspace_scaffold()
    return root


@pytest.fixture
def client(workspace):
    from config import get_settings
    from knowledge import commit_jobs

    commit_jobs._JOBS.clear()
    yield TestClient(app, headers={"X-Internal-Token": get_settings().gateway_internal_token})
    commit_jobs._JOBS.clear()


@pytest.fixture
def started_jobs(monkeypatch) -> list[tuple]:
    """Record what the route hands to the background job instead of running it."""
    import routes.knowledge

    calls: list[tuple] = []

    async def _record(project_id, files, normalize=True):
        calls.append((project_id, files, normalize))

    monkeypatch.setattr(routes.knowledge, "_run_commit_job", _record)
    return calls


def _raw(workspace: Path, relative: str, content: str = "內容") -> Path:
    path = workspace / "raw" / relative
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")
    return path


def test_dragging_into_a_category_and_reuploading_share_one_lock():
    assert ingest_lock is qa_document_lock


def test_routes_require_the_internal_token(workspace):
    anonymous = TestClient(app)

    assert anonymous.get("/brain/knowledge/raw/pending").status_code in (401, 403)
    assert anonymous.delete("/brain/knowledge/raw/pending", params={"path": "a.md"}).status_code in (401, 403)


def test_pending_lists_files_relative_to_raw(client, workspace):
    _raw(workspace, "b.md", "兩個字")
    _raw(workspace, "sub/a.pdf", "x")

    response = client.get("/brain/knowledge/raw/pending")

    assert response.status_code == 200
    files = response.json()["files"]
    assert [item["path"] for item in files] == ["b.md", "sub/a.pdf"]
    assert files[0]["size"] == len("兩個字".encode("utf-8"))
    assert files[0]["updated_at"]


def test_pending_is_empty_without_uploads(client):
    assert client.get("/brain/knowledge/raw/pending").json() == {"files": []}


def _pending_paths(client) -> list[str]:
    return [item["path"] for item in client.get("/brain/knowledge/raw/pending").json()["files"]]


def test_pending_hides_only_the_files_being_imported(client, workspace):
    from knowledge import commit_jobs

    _raw(workspace, "queued.md")
    _raw(workspace, "running.md")
    _raw(workspace, "failed.pptx")
    _raw(workspace, "older.md")
    commit_jobs.start_job("default", ["queued.md", "running.md", "failed.pptx"])
    commit_jobs.update_file("default", "running.md", "normalizing")
    commit_jobs.update_file("default", "failed.pptx", "skipped")

    assert _pending_paths(client) == ["failed.pptx", "older.md"]


@pytest.mark.parametrize("end_job", ["finish", "fail"])
def test_pending_lists_files_left_behind_once_the_job_is_over(client, workspace, end_job):
    from knowledge import commit_jobs

    _raw(workspace, "failed.pptx")
    commit_jobs.start_job("default", ["failed.pptx"])
    if end_job == "finish":
        commit_jobs.finish_job("default", [], ["failed.pptx"])
    else:
        commit_jobs.fail_job("default", "匯入中斷")

    assert _pending_paths(client) == ["failed.pptx"]


def test_delete_pending_removes_one_file(client, workspace):
    target = _raw(workspace, "sub/a.md")
    other = _raw(workspace, "b.md")

    response = client.delete("/brain/knowledge/raw/pending", params={"path": "sub/a.md"})

    assert response.status_code == 200
    assert response.json() == {"status": "ok"}
    assert not target.exists()
    assert other.exists()


def test_delete_pending_accepts_the_raw_prefix(client, workspace):
    target = _raw(workspace, "a.md")

    assert client.delete("/brain/knowledge/raw/pending", params={"path": "raw/a.md"}).status_code == 200
    assert not target.exists()


def test_delete_pending_reports_a_missing_file(client, workspace):
    response = client.delete("/brain/knowledge/raw/pending", params={"path": "gone.md"})

    assert response.status_code == 404
    assert client.delete("/brain/knowledge/raw/pending", params={"path": "sub"}).status_code == 404


@pytest.mark.parametrize(
    "path",
    [
        "../SOUL.md",
        "../../etc/passwd",
        "raw/../SOUL.md",
        "raw/../../SOUL.md",
        "sub/../../SOUL.md",
        "/etc/passwd",
        "..\\SOUL.md",
        "./a.md",
        "a//b.md",
        "",
    ],
)
def test_delete_pending_refuses_paths_outside_raw(client, workspace, path):
    soul = workspace / "SOUL.md"
    assert soul.exists()

    response = client.delete("/brain/knowledge/raw/pending", params={"path": path})

    assert response.status_code == 400
    assert soul.exists()


def test_delete_pending_does_not_follow_a_symlink_out_of_raw(client, workspace):
    soul = workspace / "SOUL.md"
    (workspace / "raw" / "link.md").symlink_to(soul)

    assert client.delete("/brain/knowledge/raw/pending", params={"path": "link.md"}).status_code == 400
    assert soul.exists()


def test_delete_pending_refuses_a_file_being_imported(client, workspace):
    from knowledge import commit_jobs

    active = _raw(workspace, "active.md")
    failed = _raw(workspace, "failed.pptx")
    commit_jobs.start_job("default", ["active.md", "failed.pptx"])
    commit_jobs.update_file("default", "active.md", "normalizing")
    commit_jobs.update_file("default", "failed.pptx", "skipped")

    assert client.delete("/brain/knowledge/raw/pending", params={"path": "active.md"}).status_code == 409
    assert active.exists()
    # 沒匯入成功的留在 raw/，要能移除。
    assert client.delete("/brain/knowledge/raw/pending", params={"path": "failed.pptx"}).status_code == 200
    assert not failed.exists()


def test_commit_without_body_fields_takes_everything(client, workspace, started_jobs):
    _raw(workspace, "a.md")
    _raw(workspace, "sub/b.md")

    response = client.post("/brain/knowledge/raw/commit", json={"project_id": "default"})

    assert response.status_code == 202
    assert response.json()["status"] == "started"
    assert response.json()["job"]["files"] == {"a.md": "pending", "sub/b.md": "pending"}
    assert started_jobs == [("default", ["a.md", "sub/b.md"], True)]


def test_commit_with_paths_only_registers_those_files(client, workspace, started_jobs):
    _raw(workspace, "new.md")
    _raw(workspace, "older.md")

    response = client.post(
        "/brain/knowledge/raw/commit",
        json={"project_id": "default", "paths": ["raw/new.md", "new.md"], "normalize": False},
    )

    assert response.status_code == 202
    assert response.json()["job"]["files"] == {"new.md": "pending"}
    assert started_jobs == [("default", ["new.md"], False)]


def test_commit_lists_a_missing_requested_file_so_its_row_gets_an_answer(client, workspace, started_jobs):
    _raw(workspace, "here.md")

    response = client.post(
        "/brain/knowledge/raw/commit", json={"project_id": "default", "paths": ["here.md", "gone.md"]},
    )

    assert response.json()["job"]["files"] == {"here.md": "pending", "gone.md": "pending"}


@pytest.mark.parametrize("paths", [[], ["gone.md"]])
def test_commit_with_nothing_to_do_does_not_touch_other_uploads(client, workspace, started_jobs, paths):
    other = _raw(workspace, "older.md")

    response = client.post("/brain/knowledge/raw/commit", json={"project_id": "default", "paths": paths})

    assert response.status_code == 200
    assert response.json()["status"] == "nothing_to_commit"
    assert "job" not in response.json()
    assert started_jobs == []
    assert other.exists()


@pytest.mark.parametrize("path", ["../SOUL.md", "raw/../../SOUL.md", "/etc/passwd"])
def test_commit_refuses_paths_outside_raw(client, workspace, started_jobs, path):
    _raw(workspace, "a.md")

    response = client.post("/brain/knowledge/raw/commit", json={"project_id": "default", "paths": [path]})

    assert response.status_code == 400
    assert started_jobs == []


def test_commit_while_running_reports_the_job(client, workspace, started_jobs):
    from knowledge import commit_jobs

    _raw(workspace, "a.md")
    commit_jobs.start_job("default", ["a.md"])

    response = client.post("/brain/knowledge/raw/commit", json={"project_id": "default", "paths": ["a.md"]})

    assert response.status_code == 200
    assert response.json()["status"] == "already_running"
    assert response.json()["job"]["state"] == "running"
    assert started_jobs == []


def test_status_snapshot_has_the_new_fields_when_idle(client):
    snapshot = client.get("/brain/knowledge/raw/commit/status").json()

    assert snapshot["state"] == "idle"
    assert snapshot["results"] == {}
    assert snapshot["skip_reasons"] == {}
