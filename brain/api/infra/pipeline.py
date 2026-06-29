"""Generic batch-async pipeline skeleton with checkpointing.

Pure mechanism: knows nothing about LanceDB, embedders, or LLMs. Concrete
pipelines (knowledge indexing, graph extraction) plug in an ItemSource,
BatchWorker, and ResultSink.
"""

from __future__ import annotations

import asyncio
import json
import os
from collections.abc import Iterator
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Protocol, runtime_checkable


@dataclass(frozen=True, slots=True)
class PipelineConfig:
    batch_size: int
    concurrency: int


@runtime_checkable
class ItemSource(Protocol):
    """Discover + Filter: stream pending items, already checkpoint-filtered."""

    def pending(self) -> Iterator[Any]: ...


@runtime_checkable
class BatchWorker(Protocol):
    """The unit scheduled by bounded in-flight pipeline tasks."""

    async def process_batch(self, items: list[Any]) -> list[Any]: ...


@runtime_checkable
class ResultSink(Protocol):
    """Batch & Flush: land one batch's results, then advance the checkpoint."""

    def flush(self, results: list[Any]) -> None: ...

    def commit_checkpoint(self, done_items: list[Any]) -> None: ...


class CheckpointStore:
    """File-backed checkpoint of {item_key: fingerprint}, written atomically.

    Mechanism only; how keys and fingerprints are computed is the ItemSource's
    policy. Atomic write (tmp + os.replace) guards against torn writes that
    would otherwise corrupt the checkpoint and force a full re-run.
    """

    def __init__(self, path: Path) -> None:
        self._path = Path(path)

    def load(self) -> dict[str, str]:
        if not self._path.exists():
            return {}
        try:
            parsed = json.loads(self._path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            return {}
        documents = parsed.get("documents") if isinstance(parsed, dict) else None
        return documents if isinstance(documents, dict) else {}

    def is_done(self, key: str, fingerprint: str) -> bool:
        return self.load().get(key) == fingerprint

    def commit(self, done: dict[str, str]) -> None:
        merged = {**self.load(), **done}
        self._path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self._path.with_suffix(self._path.suffix + ".tmp")
        tmp.write_text(
            json.dumps({"documents": merged}, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        os.replace(tmp, self._path)

    def prune(self, live_keys: set[str]) -> list[str]:
        return sorted(set(self.load()) - live_keys)


@dataclass(frozen=True, slots=True)
class PipelineStats:
    batches: int
    items: int
    results: int


def _batched(iterator: Iterator[Any], size: int) -> Iterator[list[Any]]:
    batch: list[Any] = []
    for item in iterator:
        batch.append(item)
        if len(batch) >= size:
            yield batch
            batch = []
    if batch:
        yield batch


async def run_pipeline(
    source: ItemSource,
    worker: BatchWorker,
    sink: ResultSink,
    config: PipelineConfig,
) -> PipelineStats:
    """Drive batches through the worker with bounded in-flight tasks, landing each batch
    then advancing the checkpoint. flush precedes commit_checkpoint so a crash
    can never record progress for results that were not persisted.

    Fail-fast: batches are started under back-pressure (a new batch starts only
    once a slot frees), and once any batch raises, no further batches are
    started or landed. This is why we do NOT create_task over the whole source
    up front — eager scheduling would let later batches flush/commit even after
    an earlier batch failed, breaking the checkpoint's crash-resume invariant.

    sink.flush/commit_checkpoint run on the event-loop thread (no internal
    concurrency), so they need no locking even while other batches are in flight.
    """
    async def _run(batch: list[Any]) -> tuple[list[Any], list[Any]]:
        results = await worker.process_batch(batch)
        sink.flush(results)
        sink.commit_checkpoint(batch)
        return batch, results

    batches = 0
    total_items = 0
    total_results = 0
    inflight: set[asyncio.Task[tuple[list[Any], list[Any]]]] = set()

    async def _drain_one() -> None:
        nonlocal total_items, total_results
        done, _ = await asyncio.wait(inflight, return_when=asyncio.FIRST_COMPLETED)
        for task in done:
            inflight.discard(task)
            batch, results = task.result()  # re-raises any worker exception
            total_items += len(batch)
            total_results += len(results)

    try:
        for batch in _batched(source.pending(), config.batch_size):
            while len(inflight) >= config.concurrency:
                await _drain_one()
            batches += 1
            inflight.add(asyncio.create_task(_run(batch)))
        while inflight:
            await _drain_one()
    except BaseException:
        for task in inflight:
            task.cancel()
        if inflight:
            await asyncio.gather(*inflight, return_exceptions=True)
        raise

    return PipelineStats(batches=batches, items=total_items, results=total_results)
