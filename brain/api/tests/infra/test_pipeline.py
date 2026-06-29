"""Tests for infra.pipeline — generic batch async pipeline skeleton + checkpoint."""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path

API_ROOT = Path(__file__).resolve().parents[2]
if str(API_ROOT) not in sys.path:
    sys.path.insert(0, str(API_ROOT))


def test_module_imports():
    import infra.pipeline  # noqa: F401


def test_async_helper_runs():
    async def _coro():
        return 42

    assert asyncio.run(_coro()) == 42


from infra.pipeline import PipelineConfig, ItemSource, BatchWorker, ResultSink


def test_pipeline_config_is_frozen():
    cfg = PipelineConfig(batch_size=100, concurrency=2)
    assert cfg.batch_size == 100
    assert cfg.concurrency == 2
    import dataclasses
    with __import__("pytest").raises(dataclasses.FrozenInstanceError):
        cfg.batch_size = 5  # type: ignore[misc]


def test_protocols_are_runtime_checkable():
    class _Src:
        def pending(self):
            return iter([])

    class _Worker:
        async def process_batch(self, items):
            return items

    class _Sink:
        def flush(self, results):
            ...

        def commit_checkpoint(self, done_items):
            ...

    assert isinstance(_Src(), ItemSource)
    assert isinstance(_Worker(), BatchWorker)
    assert isinstance(_Sink(), ResultSink)


import json
from infra.pipeline import CheckpointStore


def test_checkpoint_load_missing_returns_empty(tmp_path):
    store = CheckpointStore(tmp_path / "state.json")
    assert store.load() == {}


def test_checkpoint_commit_then_is_done(tmp_path):
    store = CheckpointStore(tmp_path / "state.json")
    store.commit({"a.md": "fp1"})
    assert store.is_done("a.md", "fp1") is True
    assert store.is_done("a.md", "fp_changed") is False
    assert store.is_done("missing.md", "fp1") is False


def test_checkpoint_commit_merges(tmp_path):
    store = CheckpointStore(tmp_path / "state.json")
    store.commit({"a.md": "fp1"})
    store.commit({"b.md": "fp2"})
    loaded = store.load()
    assert loaded == {"a.md": "fp1", "b.md": "fp2"}


def test_checkpoint_commit_is_atomic(tmp_path):
    path = tmp_path / "state.json"
    store = CheckpointStore(path)
    store.commit({"a.md": "fp1"})
    # No leftover temp file beside the real file.
    assert path.exists()
    assert list(tmp_path.glob("*.tmp")) == []


def test_checkpoint_load_corrupt_returns_empty(tmp_path):
    path = tmp_path / "state.json"
    path.write_text("{ not valid json", encoding="utf-8")
    store = CheckpointStore(path)
    assert store.load() == {}


def test_checkpoint_prune_reports_removed(tmp_path):
    store = CheckpointStore(tmp_path / "state.json")
    store.commit({"a.md": "fp1", "b.md": "fp2"})
    removed = store.prune(live_keys={"a.md"})
    assert removed == ["b.md"]


from infra.pipeline import run_pipeline, PipelineStats


class _ListSource:
    def __init__(self, items):
        self._items = items

    def pending(self):
        return iter(self._items)


class _RecordingSink:
    def __init__(self):
        self.calls = []
        self.flushed = []
        self.committed = []

    def flush(self, results):
        self.calls.append("flush")
        self.flushed.extend(results)

    def commit_checkpoint(self, done_items):
        self.calls.append("commit")
        self.committed.extend(done_items)


def test_run_pipeline_batches_and_counts():
    items = list(range(101))

    class _Worker:
        async def process_batch(self, batch):
            return [x * 2 for x in batch]

    sink = _RecordingSink()
    stats = asyncio.run(
        run_pipeline(_ListSource(items), _Worker(), sink, PipelineConfig(batch_size=100, concurrency=2))
    )
    assert isinstance(stats, PipelineStats)
    assert stats.batches == 2          # 101 -> [100, 1]
    assert stats.items == 101
    assert stats.results == 101
    assert sorted(sink.flushed) == [x * 2 for x in items]
    assert sorted(sink.committed) == items


def test_run_pipeline_flush_before_commit_per_batch():
    class _Worker:
        async def process_batch(self, batch):
            return batch

    sink = _RecordingSink()
    asyncio.run(
        run_pipeline(_ListSource([1, 2, 3]), _Worker(), sink, PipelineConfig(batch_size=1, concurrency=1))
    )
    # 3 batches, each flush immediately before its commit.
    assert sink.calls == ["flush", "commit", "flush", "commit", "flush", "commit"]


def test_run_pipeline_respects_concurrency_limit():
    peak = {"now": 0, "max": 0}

    class _Worker:
        async def process_batch(self, batch):
            peak["now"] += 1
            peak["max"] = max(peak["max"], peak["now"])
            await asyncio.sleep(0.01)
            peak["now"] -= 1
            return batch

    sink = _RecordingSink()
    asyncio.run(
        run_pipeline(_ListSource(list(range(20))), _Worker(), sink, PipelineConfig(batch_size=1, concurrency=3))
    )
    assert peak["max"] <= 3


class _CheckpointFilteredSource:
    """Streams items whose fingerprint isn't already in the checkpoint."""

    def __init__(self, items, store):
        self._items = items          # list[tuple[key, fingerprint]]
        self._store = store

    def pending(self):
        for key, fp in self._items:
            if not self._store.is_done(key, fp):
                yield (key, fp)


class _CheckpointSink:
    def __init__(self, store, processed):
        self._store = store
        self._processed = processed   # shared list recording processed keys

    def flush(self, results):
        self._processed.extend(results)

    def commit_checkpoint(self, done_items):
        self._store.commit({key: fp for key, fp in done_items})


def test_crash_then_resume_skips_done_batches(tmp_path):
    items = [(f"f{i}.md", f"fp{i}") for i in range(5)]
    store = CheckpointStore(tmp_path / "state.json")
    processed_first: list = []

    class _CrashingWorker:
        async def process_batch(self, batch):
            if any(key == "f3.md" for key, _ in batch):
                raise RuntimeError("boom on f3")
            return [key for key, _ in batch]

    src = _CheckpointFilteredSource(items, store)
    sink = _CheckpointSink(store, processed_first)
    with __import__("pytest").raises(RuntimeError):
        asyncio.run(run_pipeline(src, _CrashingWorker(), sink, PipelineConfig(batch_size=1, concurrency=1)))

    # f0..f2 committed before the crash; f3, f4 not.
    done = store.load()
    assert set(done) == {"f0.md", "f1.md", "f2.md"}

    # Resume with a healthy worker: only f3, f4 should be processed.
    processed_second: list = []

    class _HealthyWorker:
        async def process_batch(self, batch):
            return [key for key, _ in batch]

    src2 = _CheckpointFilteredSource(items, store)
    sink2 = _CheckpointSink(store, processed_second)
    asyncio.run(run_pipeline(src2, _HealthyWorker(), sink2, PipelineConfig(batch_size=1, concurrency=1)))

    assert sorted(processed_second) == ["f3.md", "f4.md"]
    assert set(store.load()) == {f"f{i}.md" for i in range(5)}
