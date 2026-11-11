"""Measure Brain query caching against a real gateway, without project data.

Run with the Brain environment, working directory brain/api:
    python ../../scripts/experiments/embedding-load/query_cache.py

Only the query router's table-availability check is replaced. No LanceDB,
LLM, TTS, project reads or writes occur. This is not a chat E2E benchmark.
"""

from __future__ import annotations

import argparse
from concurrent.futures import ThreadPoolExecutor
import json
import logging
from pathlib import Path
from statistics import median
import sys
from time import perf_counter

sys.path.insert(0, str(Path.cwd()))

from config import BrainSettings  # noqa: E402
import memory.embedder as embedding  # noqa: E402
from memory.query_embedding_cache import QueryEmbeddingCache  # noqa: E402
import safety.observability as observability  # noqa: E402

QUESTIONS = [
    "測試服務中心週一幾點開門？",
    "測試服務中心可以預約嗎？",
    "How do I contact the sample service centre?",
    "¿Dónde está el centro de servicio de prueba?",
    "測試服務中心提供哪些服務？",
]


def run_case(
    cfg: BrainSettings,
    label: str,
    queries: list[str],
    size: int,
    workers: int,
    *,
    warm: bool = False,
) -> dict:
    cfg.embedding_query_cache_size = size
    embedding._query_vector_cache = QueryEmbeddingCache()
    if warm:
        for query in dict.fromkeys(queries):
            embedding.encode_query_with_fallback(query, project_id="synthetic")
    observability._metrics = observability.MetricsStore()

    def request(query: str) -> tuple[float, str | None]:
        started = perf_counter()
        try:
            route = embedding.encode_query_with_fallback(
                query, project_id="synthetic",
            )
            assert len(route.vector) == 768
            return (perf_counter() - started) * 1000, None
        except Exception as exc:
            return (perf_counter() - started) * 1000, type(exc).__name__

    started = perf_counter()
    with ThreadPoolExecutor(max_workers=workers) as pool:
        results = list(pool.map(request, queries))
    seconds = perf_counter() - started
    times = sorted(elapsed for elapsed, _ in results)
    counters = observability.get_metrics_store().snapshot()["counters"]
    return {
        "case": label,
        "cache_size": size,
        "workers": workers,
        "requests": len(queries),
        "unique_queries": len(set(queries)),
        "errors": [error for _, error in results if error],
        "wall_s": round(seconds, 3),
        "p50_ms": round(median(times), 2),
        "p95_ms": round(times[min(int(len(times) * .95), len(times) - 1)], 2),
        "http_requests": sum(
            value for key, value in counters.items()
            if key.startswith("embedding_http_requests_total|")
        ),
        "cache": {
            key.split("status=", 1)[1]: value
            for key, value in counters.items()
            if key.startswith("embedding_query_cache_total|")
        },
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--requests", type=int, default=100)
    parser.add_argument("--workers", type=int, default=16)
    parser.add_argument("--rounds", type=int, default=2)
    args = parser.parse_args()
    if min(args.requests, args.workers, args.rounds) < 1:
        parser.error("requests, workers and rounds must be positive")
    logging.basicConfig(level=logging.CRITICAL)
    cfg = BrainSettings(_env_file=None)
    embedding.get_settings = lambda: cfg
    embedding._version_has_queryable_tables = lambda *a, **kw: True
    # Prime HTTP connection/model before measuring; never print credentials.
    cfg.embedding_query_cache_size = 0
    embedding.encode_query_with_fallback("Synthetic gateway warmup")
    for round_number in range(1, args.rounds + 1):
        repeated = [QUESTIONS[i % len(QUESTIONS)] for i in range(args.requests)]
        unique = [
            f"測試服務中心，案件 {round_number}-{i} 的受理時間？"
            for i in range(args.requests)
        ]
        cases = [
            ("repeated_disabled", repeated, 0, False),
            ("repeated_cold", repeated, 1024, False),
            ("repeated_warm", repeated, 1024, True),
            ("unique_disabled", unique, 0, False),
            ("unique_cold", unique, 1024, False),
        ]
        if round_number % 2 == 0:
            cases.reverse()
        for label, queries, size, warm in cases:
            result = run_case(
                cfg, label, queries, size, args.workers, warm=warm,
            )
            print(json.dumps({"round": round_number, **result}), flush=True)
            if result["errors"]:
                raise RuntimeError("Benchmark requests failed")
    for embedder in embedding._embedder_cache.values():
        embedder.close()


if __name__ == "__main__":
    main()
