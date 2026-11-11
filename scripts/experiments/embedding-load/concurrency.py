"""Bounded synthetic /embed benchmark for an isolated gateway container.

Run this client in a separate process from the server, inside its container:
    python /experiments/concurrency.py --label 1-a --seconds 6 \
        --levels 1,16,32 --reference /tmp/concurrency-reference.json

Reuse the reference file for 1-a / 2-a / 2-b / 1-b to measure numerical
agreement across settings. Only httpx and the standard library are needed.
No Brain cache, production credentials, real documents, or model imports are
used. Each document request always contains eight synthetic 600-character
segments. Client concurrency is capped at 32; no request is retried.
"""

from __future__ import annotations

import argparse
import asyncio
from collections import Counter
import hashlib
import json
import math
import os
from pathlib import Path
import random
import sys
import time
from typing import Any

import httpx


BASE_URL = "http://127.0.0.1:8009"
SYNTHETIC_TOKEN = "synthetic-concurrency-probe"
SEED = 714223
DIMENSIONS = 768
MIN_COSINE = 0.999
QUERY_TEXTS = [
    "虛構星砂工坊的紙製飛船如何分類？",
    "虛構月莓圖書館的借閱規則是什麼？",
    "虛構雲朵列車何時抵達薄荷小站？",
    "虛構水晶花園如何記錄彩色種子？",
    "虛構橙光郵局如何整理想像明信片？",
    "虛構銀河廚房如何保存玩具食譜？",
    "虛構泡泡學院的故事教室在哪裡？",
    "虛構虹橋劇團如何安排布偶演出？",
]
_SENTENCES = [
    "本段為完全虛構的合成資料，描述星砂島上不存在的紙製飛船工坊。",
    "想像中的管理員將彩色積木依照故事章節排列，沒有任何真實客戶或個人資訊。",
    "月莓圖書館只收藏夢境明信片，借閱者以虛構的雲朵印章記錄閱讀進度。",
    "薄荷小站使用玩具時鐘安排彩虹列車，所有站名與規則均為測試而創作。",
    "水晶花園以紙片代表種子，將每次澆灌想像成一段沒有實際用途的童話。",
    "布偶劇團在故事舞臺練習問候，每個角色的名稱都不對應任何真實人物。",
]
_corpus_random = random.Random(SEED)
DOCUMENT_TEXTS = [
    (f"虛構段落{index}。" + "".join(
        _corpus_random.choice(_SENTENCES) for _ in range(40)
    ))[:600]
    for index in range(8)
]
CORPUS = {"query": QUERY_TEXTS, "document": DOCUMENT_TEXTS}
CORPUS_SHA256 = hashlib.sha256(
    json.dumps(CORPUS, ensure_ascii=False, sort_keys=True).encode()
).hexdigest()


def percentile(values: list[float], fraction: float) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    position = (len(ordered) - 1) * fraction
    lower = math.floor(position)
    upper = math.ceil(position)
    return ordered[lower] + (ordered[upper] - ordered[lower]) * (
        position - lower
    )


def cosine(left: list[float], right: list[float]) -> float:
    denominator = math.sqrt(sum(v * v for v in left)) * math.sqrt(
        sum(v * v for v in right)
    )
    if not denominator or not math.isfinite(denominator):
        raise ValueError("zero_or_invalid_vector_norm")
    return sum(a * b for a, b in zip(left, right)) / denominator


def validate_response(
    body: dict[str, Any],
    kind: str,
    count: int,
    identity: str | None = None,
) -> tuple[list[list[float]], str]:
    spec = body.get("embedding_spec", {})
    actual_identity = spec.get("identity")
    if not isinstance(actual_identity, str) or not actual_identity:
        raise ValueError("missing_identity")
    if identity is not None and actual_identity != identity:
        raise ValueError("identity_mismatch")
    if spec.get("dimensions") != DIMENSIONS:
        raise ValueError("spec_dimension_mismatch")
    if spec.get("input_semantics") != kind:
        raise ValueError("input_semantics_mismatch")
    vectors = body.get("vectors")
    if not isinstance(vectors, list) or len(vectors) != count:
        raise ValueError("vector_count_mismatch")
    for vector in vectors:
        if not isinstance(vector, list) or len(vector) != DIMENSIONS:
            raise ValueError("vector_dimension_mismatch")
        if any(
            isinstance(value, bool)
            or not isinstance(value, (float, int))
            or not math.isfinite(value)
            for value in vector
        ):
            raise ValueError("nonfinite_or_nonnumeric_vector")
        if not any(vector):
            raise ValueError("zero_vector")
    return vectors, actual_identity


async def wait_ready(client: httpx.AsyncClient) -> dict[str, Any]:
    deadline = time.perf_counter() + 120
    while (remaining := deadline - time.perf_counter()) > 0:
        try:
            async with asyncio.timeout(remaining):
                live = await client.get("/health", timeout=min(8, remaining))
                live.raise_for_status()
                ready = await client.get(
                    "/health/ready", timeout=min(8, remaining)
                )
                ready.raise_for_status()
                body = ready.json()
                if body.get("embedding_spec", {}).get("dimensions") == 768:
                    return body
        except (httpx.HTTPError, ValueError, TimeoutError):
            pass
        await asyncio.sleep(min(1, max(0, deadline - time.perf_counter())))
    raise RuntimeError("readiness_deadline_exceeded_120s")


async def references(
    client: httpx.AsyncClient, path: Path | None
) -> dict[str, Any]:
    if path is not None and path.exists():
        reference = json.loads(path.read_text())
        if reference.get("corpus_sha256") != CORPUS_SHA256:
            raise ValueError("reference_corpus_mismatch")
        for kind, texts in CORPUS.items():
            validate_response(reference[kind], kind, len(texts))
        return reference

    reference: dict[str, Any] = {"corpus_sha256": CORPUS_SHA256}
    for kind, texts in CORPUS.items():
        vectors = []
        identity = None
        spec = None
        # Single-text requests make the baseline independent of document batches.
        for text in texts:
            response = await client.post(
                "/embed", json={"texts": [text], "input_type": kind}
            )
            response.raise_for_status()
            body = response.json()
            batch, identity = validate_response(body, kind, 1, identity)
            vectors.extend(batch)
            spec = body["embedding_spec"]
        reference[kind] = {"vectors": vectors, "embedding_spec": spec}
    if path is not None:
        path.write_text(json.dumps(reference, ensure_ascii=False) + "\n")
    return reference


async def smi_rows(query: str) -> list[list[str]] | None:
    process = None
    try:
        process = await asyncio.create_subprocess_exec(
            "nvidia-smi", query, "--format=csv,noheader,nounits",
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.DEVNULL,
        )
        stdout, _ = await asyncio.wait_for(process.communicate(), timeout=1.5)
        if process.returncode != 0:
            return None
        return [
            [part.strip() for part in line.split(",")]
            for line in stdout.decode().splitlines() if line.strip()
        ]
    except (OSError, TimeoutError, UnicodeError):
        return None
    finally:
        if process is not None and process.returncode is None:
            try:
                process.kill()
            except ProcessLookupError:
                pass
            await process.communicate()


async def monitor_gpu(
    stop: asyncio.Event, server_pid: int | None, output: dict[str, Any]
) -> None:
    next_sample = time.perf_counter()
    while not stop.is_set():
        gpu_rows, process_rows = await asyncio.gather(
            smi_rows("--query-gpu=uuid,memory.used,utilization.gpu"),
            smi_rows("--query-compute-apps=pid,used_gpu_memory"),
        )
        if gpu_rows is not None:
            for row in gpu_rows:
                try:
                    uuid, memory, utilization = row
                    memory_value = float(memory)
                    utilization_value = float(utilization)
                except (ValueError, TypeError):
                    continue
                peak = output["gpus"].setdefault(uuid, {
                    "memory_used_mib_peak": 0.0,
                    "utilization_percent_peak": 0.0,
                })
                peak["memory_used_mib_peak"] = max(
                    peak["memory_used_mib_peak"], memory_value
                )
                peak["utilization_percent_peak"] = max(
                    peak["utilization_percent_peak"], utilization_value
                )
            output["gpu_samples"] += 1
        if process_rows is not None and server_pid is not None:
            values = []
            for row in process_rows:
                try:
                    if int(row[0]) == server_pid:
                        values.append(float(row[1]))
                except (ValueError, IndexError):
                    continue
            if values:
                previous = output["server_memory_used_mib_peak"] or 0
                output["server_memory_used_mib_peak"] = max(
                    previous, sum(values)
                )
                output["server_samples"] += 1
        next_sample += 0.5
        try:
            await asyncio.wait_for(
                stop.wait(), timeout=max(0, next_sample - time.perf_counter())
            )
        except TimeoutError:
            pass


async def benchmark(
    client: httpx.AsyncClient,
    args: argparse.Namespace,
    level: int,
    scenario: str,
    reference: dict[str, Any],
) -> dict[str, Any]:
    randomizer = random.Random(SEED)
    query_indices = list(range(len(QUERY_TEXTS)))
    randomizer.shuffle(query_indices)
    pattern = ["query"] * 4 + ["document"]
    randomizer.shuffle(pattern)
    statistics: dict[str, Any] = {
        kind: {
            "started": 0, "completed": 0, "valid": 0,
            "http_statuses": Counter(), "errors": Counter(),
            "latencies": [], "valid_latencies": [], "cosine_min": None,
        }
        for kind in CORPUS
    }
    telemetry: dict[str, Any] = {
        "interval_seconds": 0.5,
        "server_pid": args.server_pid,
        "gpu_samples": 0,
        "server_samples": 0,
        "gpus": {},
        "server_memory_used_mib_peak": None,
    }
    stop = asyncio.Event()
    sequence = 0
    started = time.perf_counter()
    deadline = started + args.seconds
    gpu_task = asyncio.create_task(monitor_gpu(stop, args.server_pid, telemetry))

    async def worker() -> None:
        nonlocal sequence
        while time.perf_counter() < deadline:
            index = sequence
            sequence += 1
            kind = "query" if scenario == "query_only" else pattern[index % 5]
            query_index = query_indices[index % len(query_indices)]
            texts = (
                [QUERY_TEXTS[query_index]] if kind == "query"
                else DOCUMENT_TEXTS
            )
            stats = statistics[kind]
            stats["started"] += 1
            request_started = time.perf_counter()
            try:
                response = await client.post(
                    "/embed", json={"texts": texts, "input_type": kind}
                )
                latency = time.perf_counter() - request_started
                stats["latencies"].append(latency)
                stats["http_statuses"][str(response.status_code)] += 1
                if response.status_code != 200:
                    stats["errors"][f"http_{response.status_code}"] += 1
                    continue
                vectors, _ = validate_response(
                    response.json(), kind, len(texts),
                    reference[kind]["embedding_spec"]["identity"],
                )
                expected = reference[kind]["vectors"]
                if kind == "query":
                    expected = [expected[query_index]]
                minimum = min(cosine(a, b) for a, b in zip(vectors, expected))
                previous = stats["cosine_min"]
                stats["cosine_min"] = (
                    minimum if previous is None else min(previous, minimum)
                )
                if minimum < MIN_COSINE:
                    raise ValueError("cosine_below_0.999")
                stats["valid"] += 1
                stats["valid_latencies"].append(latency)
            except httpx.HTTPError as error:
                stats["latencies"].append(time.perf_counter() - request_started)
                stats["errors"][type(error).__name__] += 1
            except (ValueError, TypeError, KeyError, AttributeError) as error:
                # Record safe categories, never server bodies or auth headers.
                category = (
                    str(error) if type(error) is ValueError
                    else type(error).__name__
                )
                if category not in {
                    "missing_identity", "identity_mismatch",
                    "spec_dimension_mismatch", "input_semantics_mismatch",
                    "vector_count_mismatch", "vector_dimension_mismatch",
                    "nonfinite_or_nonnumeric_vector", "zero_vector",
                    "zero_or_invalid_vector_norm", "cosine_below_0.999",
                }:
                    category = type(error).__name__
                stats["errors"][category] += 1
            finally:
                stats["completed"] += 1

    try:
        await asyncio.gather(*(worker() for _ in range(level)))
    finally:
        elapsed = time.perf_counter() - started
        stop.set()
        await gpu_task

    for stats in statistics.values():
        latencies = stats.pop("latencies")
        valid_latencies = stats.pop("valid_latencies")
        stats["error_count"] = sum(stats["errors"].values())
        stats["latency_ms_all_attempts"] = {
            "samples": len(latencies),
            "p50": percentile(latencies, 0.5),
            "p95": percentile(latencies, 0.95),
        }
        stats["latency_ms_valid"] = {
            "samples": len(valid_latencies),
            "p50": percentile(valid_latencies, 0.5),
            "p95": percentile(valid_latencies, 0.95),
        }
        for name in ("latency_ms_all_attempts", "latency_ms_valid"):
            for quantile in ("p50", "p95"):
                value = stats[name][quantile]
                stats[name][quantile] = None if value is None else value * 1000
    completed = sum(stats["completed"] for stats in statistics.values())
    valid = sum(stats["valid"] for stats in statistics.values())
    if not telemetry["gpus"]:
        telemetry["gpus"] = None
    return {
        "label": args.label,
        "server_max_concurrency": os.environ.get("EMBEDDING_MAX_CONCURRENCY"),
        "client_concurrency": level,
        "scenario": scenario,
        "mixed_offered_pattern": pattern if scenario == "mixed_80_20" else None,
        "seed": SEED,
        "corpus_sha256": CORPUS_SHA256,
        "document_segments": 8,
        "document_characters_per_segment": 600,
        "request_timeout_seconds": 10,
        "target_seconds": args.seconds,
        "elapsed_seconds_including_drain": elapsed,
        "completed_requests_per_second": completed / elapsed,
        "valid_requests_per_second": valid / elapsed,
        "valid_vectors_per_second": (
            statistics["query"]["valid"] + 8 * statistics["document"]["valid"]
        ) / elapsed,
        "reference_source": str(args.reference) if args.reference else "memory",
        "identities": {
            kind: reference[kind]["embedding_spec"]["identity"]
            for kind in CORPUS
        },
        "cosine_threshold": MIN_COSINE,
        "requests": statistics,
        "gpu": telemetry,
    }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--seconds", type=float, default=6)
    parser.add_argument("--server-pid", type=int)
    parser.add_argument(
        "--label", required=True, choices=("1-a", "2-a", "2-b", "1-b")
    )
    parser.add_argument("--levels", default="1,16,32")
    parser.add_argument("--reference", type=Path)
    args = parser.parse_args()
    try:
        args.levels = [int(level) for level in args.levels.split(",")]
    except ValueError:
        parser.error("--levels must be comma-separated integers")
    if not args.levels or any(level < 1 or level > 32 for level in args.levels):
        parser.error("--levels must be between 1 and 32")
    if not math.isfinite(args.seconds) or args.seconds <= 0:
        parser.error("--seconds must be finite and positive")
    if args.server_pid is not None and args.server_pid <= 0:
        parser.error("--server-pid must be positive")
    return args


async def main(args: argparse.Namespace) -> int:
    if os.environ.get("EMBEDDING_BEARER_TOKEN") != SYNTHETIC_TOKEN:
        raise ValueError("requires_isolated_synthetic_bearer_environment")
    configured = os.environ.get("EMBEDDING_MAX_CONCURRENCY")
    if configured is not None and configured != args.label.split("-")[0]:
        raise ValueError("label_does_not_match_server_concurrency_environment")
    limits = httpx.Limits(
        max_connections=max(args.levels), max_keepalive_connections=32
    )
    async with httpx.AsyncClient(
        base_url=BASE_URL,
        headers={"Authorization": f"Bearer {SYNTHETIC_TOKEN}"},
        timeout=10,
        limits=limits,
        trust_env=False,
    ) as client:
        await wait_ready(client)
        reference = await references(client, args.reference)
        failed = False
        for level in args.levels:
            for scenario in ("query_only", "mixed_80_20"):
                result = await benchmark(client, args, level, scenario, reference)
                print(
                    json.dumps(result, ensure_ascii=False, allow_nan=False),
                    flush=True,
                )
                failed = any(
                    stats["error_count"] for stats in result["requests"].values()
                )
                # Timed-out requests may still occupy the server queue; avoid
                # presenting later groups as uncontaminated measurements.
                if failed:
                    print(
                        "stopped_after_failed_group_to_avoid_queue_contamination",
                        file=sys.stderr,
                    )
                    return 1
        return int(failed)


if __name__ == "__main__":
    try:
        sys.exit(asyncio.run(main(parse_args())))
    except (OSError, httpx.HTTPError, ValueError, RuntimeError) as error:
        # Exception messages can contain server bodies; expose only the type.
        print(json.dumps({"fatal_error": type(error).__name__}), file=sys.stderr)
        sys.exit(1)
