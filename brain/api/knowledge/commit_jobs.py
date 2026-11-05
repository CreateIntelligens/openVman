"""In-memory progress registry for the raw/ commit (import) pipeline.

單機部署下 job 狀態存記憶體即可：commit 由背景 task 執行，前端輪詢
job_snapshot 取得逐檔進度。重啟服務會遺失進度顯示，但 commit 本身對
raw/ 檔案是冪等的（成功的已搬離 raw/，失敗的留在原地可重跑）。
"""

from __future__ import annotations

import copy
import threading
from datetime import UTC, datetime
from typing import Any

_LOCK = threading.Lock()
_JOBS: dict[str, dict[str, Any]] = {}

_IDLE_SNAPSHOT: dict[str, Any] = {
    "state": "idle",
    "started_at": None,
    "finished_at": None,
    "files": {},
    "committed": [],
    "skipped": [],
    "results": {},
    "skip_reasons": {},
    "error": None,
}


def _now() -> str:
    return datetime.now(UTC).isoformat()


def start_job(project_id: str, files: list[str]) -> bool:
    with _LOCK:
        job = _JOBS.get(project_id)
        if job and job["state"] == "running":
            return False
        _JOBS[project_id] = {
            "state": "running",
            "started_at": _now(),
            "finished_at": None,
            "files": {path: "pending" for path in files},
            "committed": [],
            "skipped": [],
            "results": {},
            "skip_reasons": {},
            "error": None,
        }
        return True


def update_file(project_id: str, path: str, state: str) -> None:
    with _LOCK:
        job = _JOBS.get(project_id)
        if job and path in job["files"]:
            job["files"][path] = state


def record_result(project_id: str, path: str, result: dict[str, Any]) -> None:
    """Publish one file's outcome as soon as it is known; a batch can take minutes."""
    with _LOCK:
        job = _JOBS.get(project_id)
        if job:
            job["results"][path] = copy.deepcopy(result)


def record_skip(project_id: str, path: str, reason: str) -> None:
    with _LOCK:
        job = _JOBS.get(project_id)
        if job:
            job["skip_reasons"][path] = reason


def finish_job(project_id: str, committed: list[str], skipped: list[str]) -> None:
    with _LOCK:
        job = _JOBS.get(project_id)
        if not job:
            return
        job["state"] = "done"
        job["finished_at"] = _now()
        job["committed"] = list(committed)
        job["skipped"] = list(skipped)


def fail_job(project_id: str, error: str) -> None:
    with _LOCK:
        job = _JOBS.get(project_id)
        if not job:
            return
        job["state"] = "failed"
        job["finished_at"] = _now()
        job["error"] = error


def active_files(project_id: str) -> set[str]:
    """Files the running job has not finished with; they must not be listed or removed."""
    with _LOCK:
        job = _JOBS.get(project_id)
        if not job or job["state"] != "running":
            return set()
        return {path for path, state in job["files"].items() if state in ("pending", "normalizing")}


def job_snapshot(project_id: str) -> dict[str, Any]:
    with _LOCK:
        job = _JOBS.get(project_id)
        return copy.deepcopy(job) if job else copy.deepcopy(_IDLE_SNAPSHOT)
