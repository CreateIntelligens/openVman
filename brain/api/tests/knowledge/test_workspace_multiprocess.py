"""Workspace initialization must not overwrite a concurrent error journal."""

from __future__ import annotations

import multiprocessing
from pathlib import Path
from time import sleep


def _scaffold_and_append(root: str, barrier, delayed, index: int):
    from infra.learnings import record_error_event
    from knowledge.workspace import ensure_workspace_scaffold

    from infra import project_context

    project_context._DATA_ROOT = Path(root)
    original = Path.write_text
    slow = index == 0

    def delay_template(path, content, *args, **kwargs):
        if slow and path.name == "ERRORS.md":
            delayed.set()
            sleep(0.5)
        return original(path, content, *args, **kwargs)

    Path.write_text = delay_template
    barrier.wait(timeout=15)
    if not slow:
        assert delayed.wait(timeout=15)
    ensure_workspace_scaffold()
    record_error_event("test", f"process-{index}")


def test_new_workspace_templates_preserve_concurrent_error_appends(tmp_path: Path):
    ctx = multiprocessing.get_context("spawn")
    barrier, delayed = ctx.Barrier(4), ctx.Event()
    workers = [
        ctx.Process(target=_scaffold_and_append, args=(str(tmp_path), barrier, delayed, index))
        for index in range(4)
    ]
    for worker in workers:
        worker.start()
    try:
        for worker in workers:
            worker.join(timeout=20)
            assert worker.exitcode == 0
        text = (tmp_path / "default" / "workspace" / ".learnings" / "ERRORS.md").read_text()
        for index in range(4):
            assert text.count(f"process-{index}") == 1
    finally:
        for worker in workers:
            if worker.is_alive():
                worker.terminate()
            worker.join(timeout=5)


def _migrate_and_append(root: str, barrier, delayed, index: int):
    from infra.learnings import record_error_event
    from knowledge.workspace import ensure_workspace_scaffold

    from infra import project_context

    project_context._DATA_ROOT = Path(root)
    original = Path.rename

    def delay_migration(path, target):
        if index == 0 and path.name == "ERRORS.md":
            delayed.set()
            sleep(0.5)
        return original(path, target)

    Path.rename = delay_migration
    barrier.wait(timeout=15)
    if index:
        assert delayed.wait(timeout=15)
    ensure_workspace_scaffold()
    record_error_event("test", f"process-{index}")


def test_legacy_journal_migrates_once_while_chat_workers_append(tmp_path: Path):
    old = tmp_path / "default" / "workspace" / "ERRORS.md"
    old.parent.mkdir(parents=True)
    old.write_text("legacy-error\n")
    ctx = multiprocessing.get_context("spawn")
    barrier, delayed = ctx.Barrier(4), ctx.Event()
    workers = [
        ctx.Process(target=_migrate_and_append, args=(str(tmp_path), barrier, delayed, index))
        for index in range(4)
    ]
    for worker in workers:
        worker.start()
    try:
        for worker in workers:
            worker.join(timeout=20)
            assert worker.exitcode == 0
        assert not old.exists()
        text = (old.parent / ".learnings" / "ERRORS.md").read_text()
        assert text.count("legacy-error") == 1
        for index in range(4):
            assert text.count(f"process-{index}") == 1
    finally:
        for worker in workers:
            if worker.is_alive():
                worker.terminate()
            worker.join(timeout=5)
