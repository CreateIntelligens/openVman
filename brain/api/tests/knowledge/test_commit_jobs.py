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


def test_snapshots_carry_results_and_skip_reasons():
    _reset()
    idle = commit_jobs.job_snapshot("nope")
    assert idle["results"] == {} and idle["skip_reasons"] == {}
    commit_jobs.start_job("p1", ["a.pdf", "b.bin"])
    running = commit_jobs.job_snapshot("p1")
    assert running["results"] == {} and running["skip_reasons"] == {}


def test_results_are_visible_while_the_job_is_still_running():
    _reset()
    commit_jobs.start_job("p1", ["a.pdf", "b.bin"])
    commit_jobs.record_result("p1", "a.pdf", {"target": "knowledge/a.md", "kind": "document"})
    commit_jobs.record_skip("p1", "b.bin", "這個格式不支援")
    snap = commit_jobs.job_snapshot("p1")
    assert snap["state"] == "running"
    assert snap["results"]["a.pdf"]["target"] == "knowledge/a.md"
    assert snap["skip_reasons"] == {"b.bin": "這個格式不支援"}
    commit_jobs.finish_job("p1", ["knowledge/a.md"], ["b.bin"])
    done = commit_jobs.job_snapshot("p1")
    assert done["results"]["a.pdf"]["kind"] == "document"
    assert done["skip_reasons"]["b.bin"] == "這個格式不支援"


def test_new_job_starts_without_the_previous_results():
    _reset()
    commit_jobs.start_job("p1", ["a.pdf"])
    commit_jobs.record_result("p1", "a.pdf", {"target": "knowledge/a.md"})
    commit_jobs.finish_job("p1", ["knowledge/a.md"], [])
    commit_jobs.start_job("p1", ["b.pdf"])
    assert commit_jobs.job_snapshot("p1")["results"] == {}


def test_recording_for_an_unknown_project_is_ignored():
    _reset()
    commit_jobs.record_result("nope", "a.pdf", {"target": "x"})
    commit_jobs.record_skip("nope", "a.pdf", "reason")
    assert commit_jobs.job_snapshot("nope")["results"] == {}


def test_active_files_are_the_unfinished_ones_of_a_running_job():
    _reset()
    assert commit_jobs.active_files("p1") == set()
    commit_jobs.start_job("p1", ["queued.pdf", "busy.pdf", "done.pdf", "bad.bin"])
    commit_jobs.update_file("p1", "busy.pdf", "normalizing")
    commit_jobs.update_file("p1", "done.pdf", "committed")
    commit_jobs.update_file("p1", "bad.bin", "skipped")
    assert commit_jobs.active_files("p1") == {"queued.pdf", "busy.pdf"}
    commit_jobs.fail_job("p1", "boom")
    assert commit_jobs.active_files("p1") == set()
