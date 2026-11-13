"""Counters and timing summaries include all workers, even after worker exit."""

from __future__ import annotations

import multiprocessing
from pathlib import Path

from safety.observability import MetricsStore, render_prometheus


def _record(directory: str, index: int):
    store = MetricsStore(Path(directory))
    for _ in range(50):
        store.increment("worker_requests_total", role="chat")
        store.observe("worker_latency_ms", index + 1, role="chat")


def test_metrics_sum_workers_and_keep_completed_observations(tmp_path: Path):
    ctx = multiprocessing.get_context("spawn")
    workers = [
        ctx.Process(target=_record, args=(str(tmp_path), index))
        for index in range(4)
    ]
    for worker in workers:
        worker.start()
    try:
        for worker in workers:
            worker.join(timeout=15)
            assert worker.exitcode == 0
        # The scraping worker has no local measurements itself.
        store = MetricsStore(tmp_path)
        snapshot = store.snapshot()
        assert snapshot["counters"] == {"worker_requests_total|role=chat": 200}
        assert snapshot["timings"]["worker_latency_ms|role=chat"] == {
            "count": 200, "sum_ms": 500, "max_ms": 4, "avg_ms": 2.5,
        }
        payload = render_prometheus(store).decode()
        assert 'worker_requests_total{role="chat"} 200' in payload
        assert 'worker_latency_ms_count{role="chat"} 200' in payload
        assert 'worker_latency_ms_sum{role="chat"} 500' in payload
        assert 'worker_latency_ms_max{role="chat"} 4' in payload
        assert MetricsStore(tmp_path / "next-run").snapshot() == {
            "counters": {}, "timings": {},
        }
    finally:
        for worker in workers:
            if worker.is_alive():
                worker.terminate()
            worker.join(timeout=5)


def test_singleton_selects_one_supervisor_epoch(monkeypatch, tmp_path: Path):
    from safety import observability

    monkeypatch.setenv("BRAIN_METRICS_DIR", str(tmp_path))
    monkeypatch.setenv("BRAIN_METRICS_RUN_ID", "firstrun")
    monkeypatch.setattr(observability, "_metrics", None)
    first = observability.get_metrics_store()
    first.increment("requests_total")
    monkeypatch.setenv("BRAIN_METRICS_RUN_ID", "secondrun")
    monkeypatch.setattr(observability, "_metrics", None)
    assert observability.get_metrics_store().snapshot() == {
        "counters": {}, "timings": {},
    }
    assert first.snapshot()["counters"] == {"requests_total": 1}
