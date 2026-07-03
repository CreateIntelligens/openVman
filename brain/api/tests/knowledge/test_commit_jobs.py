"""commit_jobs 進度註冊表的狀態轉移。"""

from __future__ import annotations

from knowledge import commit_jobs


def _reset():
    commit_jobs._JOBS.clear()


def test_snapshot_of_unknown_project_is_idle():
    _reset()
    snap = commit_jobs.job_snapshot("nope")
    assert snap["state"] == "idle"
    assert snap["files"] == {}


def test_start_job_registers_pending_files():
    _reset()
    assert commit_jobs.start_job("p1", ["a.pdf", "b.csv"]) is True
    snap = commit_jobs.job_snapshot("p1")
    assert snap["state"] == "running"
    assert snap["files"] == {"a.pdf": "pending", "b.csv": "pending"}


def test_second_start_while_running_is_rejected():
    _reset()
    commit_jobs.start_job("p1", ["a.pdf"])
    assert commit_jobs.start_job("p1", ["b.pdf"]) is False


def test_file_updates_and_finish():
    _reset()
    commit_jobs.start_job("p1", ["a.pdf"])
    commit_jobs.update_file("p1", "a.pdf", "normalizing")
    assert commit_jobs.job_snapshot("p1")["files"]["a.pdf"] == "normalizing"
    commit_jobs.finish_job("p1", ["knowledge/a.md"], [])
    snap = commit_jobs.job_snapshot("p1")
    assert snap["state"] == "done"
    assert snap["committed"] == ["knowledge/a.md"]
    assert snap["finished_at"]


def test_fail_job_records_error():
    _reset()
    commit_jobs.start_job("p1", ["a.pdf"])
    commit_jobs.fail_job("p1", "boom")
    snap = commit_jobs.job_snapshot("p1")
    assert snap["state"] == "failed"
    assert snap["error"] == "boom"


def test_restart_after_done_is_allowed():
    _reset()
    commit_jobs.start_job("p1", ["a.pdf"])
    commit_jobs.finish_job("p1", [], [])
    assert commit_jobs.start_job("p1", ["b.pdf"]) is True


def test_snapshot_is_a_copy():
    _reset()
    commit_jobs.start_job("p1", ["a.pdf"])
    snap = commit_jobs.job_snapshot("p1")
    snap["files"]["a.pdf"] = "mutated"
    assert commit_jobs.job_snapshot("p1")["files"]["a.pdf"] == "pending"
