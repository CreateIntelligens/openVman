"""Backend metrics summed across uvicorn worker processes."""

from __future__ import annotations

import multiprocessing


def _worker(directory: str, done) -> None:
    import os

    os.environ["BACKEND_METRICS_DIR"] = directory
    from app import observability

    for _ in range(25):
        observability.increment_counter("chat_requests")
        observability.record_timing("chat_ms", 10.0)
    done.put(os.getpid())


def test_snapshot_sums_every_process(tmp_path, monkeypatch):
    context = multiprocessing.get_context("spawn")
    done = context.Queue()
    workers = [context.Process(target=_worker, args=(str(tmp_path), done)) for _ in range(4)]
    for worker in workers:
        worker.start()
    for worker in workers:
        worker.join(60)
    assert len({done.get(timeout=5) for _ in workers}) == 4

    from app import observability

    monkeypatch.setenv("BACKEND_METRICS_DIR", str(tmp_path))
    monkeypatch.setattr(observability, "_shards_ready", False)
    monkeypatch.setattr(observability, "_shards", None)
    snapshot = observability.get_metrics_snapshot()
    assert snapshot["counters"]["chat_requests"] == 100
    assert snapshot["timings"]["chat_ms"]["count"] == 100
    assert snapshot["timings"]["chat_ms"]["avg_ms"] == 10.0
    assert snapshot["scope"]["totals"] == "all_processes"
