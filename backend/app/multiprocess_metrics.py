"""Per-process metric shards summed on read (same design as brain/api/infra/multiprocess_metrics.py)."""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path
from uuid import uuid4


class MetricShards:
    """One SQLite writer per worker; scrapes sum every shard in this run."""

    def __init__(self, directory: Path) -> None:
        self.directory = directory
        directory.mkdir(mode=0o700, parents=True, exist_ok=True)
        self.connection = sqlite3.connect(
            directory / f"{uuid4().hex}.db", check_same_thread=False,
        )
        self.connection.execute("PRAGMA journal_mode=WAL")
        # Metrics are expendable at container termination. Avoid a disk sync
        # for every measured node while preserving transactional scraper reads.
        self.connection.execute("PRAGMA synchronous=OFF")
        self.connection.execute(
            "CREATE TABLE series ("
            "name TEXT, labels TEXT, kind TEXT, count REAL, total REAL, peak REAL, "
            "PRIMARY KEY (name, labels, kind))"
        )
        self.connection.commit()

    def record(
        self, name: str, labels: tuple, kind: str, value: float,
    ) -> None:
        with self.connection:
            self.connection.execute(
                "INSERT INTO series VALUES (?, ?, ?, ?, ?, ?) "
                "ON CONFLICT(name, labels, kind) DO UPDATE SET "
                "count=count+excluded.count, total=total+excluded.total, "
                "peak=MAX(peak, excluded.peak)",
                (name, json.dumps(labels), kind, 1, value, max(0, value)),
            )

    def read(self) -> tuple[dict, dict]:
        counters: dict = {}
        timings: dict = {}
        for path in self.directory.glob("*.db"):
            connection = sqlite3.connect(
                path.as_uri() + "?mode=ro", uri=True, timeout=5,
            )
            try:
                rows = connection.execute("SELECT * FROM series").fetchall()
            except sqlite3.OperationalError as exc:
                # A new worker may have opened its file before creating the
                # schema. It has no observations yet and can be omitted.
                if "no such table" not in str(exc):
                    raise
                continue
            finally:
                connection.close()
            for name, labels_json, kind, count, total, peak in rows:
                key = (name, tuple(tuple(label) for label in json.loads(labels_json)))
                if kind == "counter":
                    counters[key] = counters.get(key, 0) + int(total)
                else:
                    bucket = timings.setdefault(
                        key, {"count": 0, "sum_ms": 0.0, "max_ms": 0.0},
                    )
                    bucket["count"] += int(count)
                    bucket["sum_ms"] += total
                    bucket["max_ms"] = max(bucket["max_ms"], peak)
        return counters, timings
