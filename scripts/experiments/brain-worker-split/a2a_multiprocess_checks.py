"""In-network HTTP acceptance checks against split-backend + fake-hub.

Run inside the isolated Compose `client` container via:
  python /experiments/a2a_multiprocess_checks.py <command> [args...]
"""

from __future__ import annotations

import argparse
import asyncio
from collections import Counter
from contextlib import asynccontextmanager
import json
import os
from pathlib import Path
import sqlite3
import sys
import time
from typing import Any

import httpx
import redis.asyncio as aioredis

from app.gateway.a2a_store import A2ACredentialStore

BACKEND = "http://split-backend:8200"
HUB = "http://fake-hub:8095"
FAKE_LLM = "http://fake-llm:8080"
INTERNAL_TOKEN = "synthetic-worker-internal-token"
HEADERS = {"X-Internal-Token": INTERNAL_TOKEN, "Connection": "close"}


def _new_http_client(timeout: float = 20.0) -> httpx.AsyncClient:
    return httpx.AsyncClient(
        timeout=timeout,
        trust_env=False,
        limits=httpx.Limits(max_connections=256, max_keepalive_connections=0),
    )


@asynccontextmanager
async def _rotate_accept_queue(client: httpx.AsyncClient, concurrency: int = 16):
    """Continuously hit /metrics/prometheus to occupy fast LIFO workers across all processes."""
    stop_event = asyncio.Event()

    async def _worker() -> None:
        while not stop_event.is_set():
            try:
                await client.get(f"{BACKEND}/metrics/prometheus", headers={"Connection": "close"})
            except Exception:
                pass
            await asyncio.sleep(0)

    tasks = [asyncio.create_task(_worker()) for _ in range(concurrency)]
    try:
        await asyncio.sleep(0.01)
        yield
    finally:
        stop_event.set()
        for t in tasks:
            t.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)


async def _gather_until_all_workers(
    client: httpx.AsyncClient,
    fn,
    *,
    expected_workers: int = 4,
    batch_size: int = 32,
    max_rounds: int = 15,
    min_rounds: int = 2,
) -> list[tuple[Any, ...]]:
    results: list[tuple[Any, ...]] = []
    seen: set[str] = set()
    idx = 0

    async def _staggered(idx_val: int, j: int):
        await asyncio.sleep((j % 8) * 0.002)
        return await fn(idx_val + j)

    async with _rotate_accept_queue(client, 16):
        for round_idx in range(max_rounds):
            batch = await asyncio.gather(*(_staggered(idx, j) for j in range(batch_size)))
            idx += batch_size
            results.extend(batch)
            for item in batch:
                wid = item[-1]
                if wid:
                    seen.add(wid)
            if round_idx + 1 >= min_rounds and len(seen) >= expected_workers:
                break
            await asyncio.sleep(0.04)
    return results


def _extract_worker_id(resp: httpx.Response, body: dict[str, Any] | None = None) -> str | None:
    wid = resp.headers.get("X-OpenVMan-Worker-ID")
    if wid:
        return wid
    if isinstance(body, dict):
        return body.get("worker_id")
    return None


async def _sample_workers_with_hits(
    client: httpx.AsyncClient,
    *,
    expected_workers: int = 4,
    probes: int = 32,
    strict_200: bool = True,
    require_all: bool = True,
) -> tuple[dict[str, bool], Counter[str]]:
    async def one(j: int):
        await asyncio.sleep((j % 8) * 0.002)
        r = await client.get(f"{BACKEND}/api/v1/internal/a2a/peers", headers=HEADERS)
        if r.status_code != 200:
            if strict_200:
                raise AssertionError(f"/peers returned HTTP {r.status_code}: {r.text}")
            return None
        data = r.json()
        return _extract_worker_id(r, data), bool(data.get("is_leader"))

    workers: dict[str, bool] = {}
    hits: Counter[str] = Counter()
    batch = max(24, probes)
    async with _rotate_accept_queue(client, 16):
        for round_idx in range(15):
            results = await asyncio.gather(*(one(j) for j in range(batch)))
            for item in results:
                if item and item[0]:
                    wid, is_l = item
                    workers[wid] = is_l
                    hits[wid] += 1
            if round_idx >= 1 and len(workers) >= expected_workers:
                break
            await asyncio.sleep(0.04)
    if require_all and len(workers) != expected_workers:
        raise AssertionError(
            f"Expected {expected_workers} distinct workers, saw {len(workers)}: {dict(hits)}"
        )
    return workers, hits


async def _wait_for_ready(client: httpx.AsyncClient, expected_workers: int = 4, timeout: float = 45.0) -> dict[str, Any]:
    deadline = time.monotonic() + timeout
    last_err = None
    while time.monotonic() < deadline:
        try:
            hub_state = (await client.get(f"{HUB}/control/state")).json()
            if hub_state.get("active_token") and hub_state.get("active_sse_streams", 0) >= 1:
                workers, hits = await _sample_workers_with_hits(
                    client,
                    expected_workers=expected_workers,
                    probes=max(24, expected_workers * 8),
                    strict_200=False,
                    require_all=False,
                )
                leaders = [w for w, is_l in workers.items() if is_l]
                if len(workers) == expected_workers and len(leaders) == 1:
                    return {
                        "hub_state": hub_state,
                        "workers": workers,
                        "worker_hits": dict(hits),
                        "leader": leaders[0],
                    }
        except Exception as exc:
            last_err = str(exc)
        await asyncio.sleep(0.4)
    raise RuntimeError(f"A2A cluster did not become ready within {timeout}s (last_err={last_err})")


async def _sample_workers(client: httpx.AsyncClient, probes: int = 32) -> dict[str, bool]:
    workers, _ = await _sample_workers_with_hits(
        client,
        expected_workers=4,
        probes=probes,
        strict_200=False,
        require_all=False,
    )
    return workers


async def cmd_ready(args: argparse.Namespace) -> None:
    async with _new_http_client(timeout=15.0) as client:
        info = await _wait_for_ready(client, expected_workers=args.workers)
        print(json.dumps(info, ensure_ascii=False))


async def cmd_outbound(_args: argparse.Namespace) -> None:
    async with _new_http_client(timeout=20.0) as client:
        await _wait_for_ready(client, expected_workers=4)
        await client.post(f"{HUB}/control/reset", json={"full": True})

        async def hit_peers(_i: int):
            r = await client.get(f"{BACKEND}/api/v1/internal/a2a/peers", headers=HEADERS)
            body = r.json() if r.headers.get("content-type", "").startswith("application/json") else {}
            return r.status_code, body.get("is_leader"), _extract_worker_id(r, body)

        async def hit_task(i: int):
            r = await client.post(
                f"{BACKEND}/api/v1/internal/a2a/tasks",
                headers=HEADERS,
                json={"target_agent_id": "peer-alpha", "message": f"outbound-{i}"},
            )
            body = r.json() if r.headers.get("content-type", "").startswith("application/json") else {}
            return r.status_code, _extract_worker_id(r, body)

        async def hit_group(i: int):
            r = await client.post(
                f"{BACKEND}/api/v1/internal/a2a/groups/messages",
                headers=HEADERS,
                json={"group_id": "grp-alpha", "message": f"group-{i}"},
            )
            body = r.json() if r.headers.get("content-type", "").startswith("application/json") else {}
            return r.status_code, _extract_worker_id(r, body)

        peers_res = await _gather_until_all_workers(client, hit_peers, expected_workers=4, batch_size=32)
        tasks_res = await _gather_until_all_workers(client, hit_task, expected_workers=4, batch_size=32)
        groups_res = await _gather_until_all_workers(client, hit_group, expected_workers=4, batch_size=32)

        hub_state = (await client.get(f"{HUB}/control/state")).json()
        peers_statuses = Counter(s for s, _, _ in peers_res)
        tasks_statuses = Counter(s for s, _ in tasks_res)
        groups_statuses = Counter(s for s, _ in groups_res)
        peers_worker_hits = Counter(w for _, _, w in peers_res if w)
        tasks_worker_hits = Counter(w for _, w in tasks_res if w)
        groups_worker_hits = Counter(w for _, w in groups_res if w)
        non_leader_200 = sum(1 for s, is_l, _ in peers_res if s == 200 and is_l is False)

        assert peers_statuses == {200: len(peers_res)}, f"peers statuses unexpected: {peers_statuses}"
        assert tasks_statuses == {200: len(tasks_res)}, f"tasks statuses unexpected: {tasks_statuses}"
        assert groups_statuses == {200: len(groups_res)}, f"groups statuses unexpected: {groups_statuses}"
        assert hub_state["peers_requests"] == len(peers_res), hub_state
        assert hub_state["outbound_tasks_count"] == len(tasks_res), hub_state
        assert hub_state["group_requests"] == len(groups_res), hub_state
        assert len(peers_worker_hits) == 4 and non_leader_200 > 0, (peers_worker_hits, non_leader_200)
        assert len(tasks_worker_hits) == 4, tasks_worker_hits
        assert len(groups_worker_hits) == 4, groups_worker_hits

        print(
            json.dumps(
                {
                    "check": "outbound_endpoints",
                    "peers_http_200": peers_statuses[200],
                    "peers_http_503": peers_statuses.get(503, 0),
                    "tasks_http_200": tasks_statuses[200],
                    "tasks_http_503": tasks_statuses.get(503, 0),
                    "groups_http_200": groups_statuses[200],
                    "groups_http_503": groups_statuses.get(503, 0),
                    "hub_peers_received": hub_state["peers_requests"],
                    "hub_tasks_received": hub_state["outbound_tasks_count"],
                    "hub_groups_received": hub_state["group_requests"],
                    "peers_worker_hits": dict(peers_worker_hits),
                    "tasks_worker_hits": dict(tasks_worker_hits),
                    "groups_worker_hits": dict(groups_worker_hits),
                    "non_leader_200_count": non_leader_200,
                },
                ensure_ascii=False,
            )
        )


async def cmd_inbound_once(args: argparse.Namespace) -> None:
    count = args.count
    async with _new_http_client(timeout=20.0) as client:
        await _wait_for_ready(client, expected_workers=args.workers)
        await client.post(f"{HUB}/control/reset", json={"full": True})
        llm_before = (await client.get(f"{FAKE_LLM}/stats")).json()["requests"]

        push_resp = (
            await client.post(
                f"{HUB}/control/push_tasks",
                json={"count": count, "prefix": "inbound-once"},
            )
        ).json()
        expected_keys = {f"reply-{item['taskId']}" for item in push_resp["pushed"]}
        expected_seqs = {str(item["sequence"]) for item in push_resp["pushed"]}

        deadline = time.monotonic() + 90.0
        hub_state = {}
        while time.monotonic() < deadline:
            hub_state = (await client.get(f"{HUB}/control/state")).json()
            if (
                hub_state["ack_total"] >= count
                and hub_state["inbound_replies_total"] >= count
            ):
                break
            await asyncio.sleep(0.3)
        else:
            raise RuntimeError(f"Timed out waiting for {count} inbound tasks: {hub_state}")

        await asyncio.sleep(2.0)
        hub_state = (await client.get(f"{HUB}/control/state")).json()
        llm_after = (await client.get(f"{FAKE_LLM}/stats")).json()["requests"]
        llm_delta = llm_after - llm_before

        ack_counts = hub_state["ack_counts"]
        reply_counts = hub_state["inbound_replies_by_key"]
        assert set(ack_counts.keys()) == expected_seqs, (ack_counts, expected_seqs)
        assert all(v == 1 for v in ack_counts.values()), ack_counts
        assert set(reply_counts.keys()) == expected_keys, (reply_counts, expected_keys)
        assert all(v == 1 for v in reply_counts.values()), reply_counts
        assert llm_delta == count, f"Expected {count} Brain/LLM requests, got {llm_delta}"

        print(
            json.dumps(
                {
                    "check": "inbound_processed_once",
                    "pushed_tasks": count,
                    "brain_llm_calls": llm_delta,
                    "unique_seqs_acked": len(ack_counts),
                    "total_acks": hub_state["ack_total"],
                    "unique_replies_sent": len(reply_counts),
                    "total_replies": hub_state["inbound_replies_total"],
                },
                ensure_ascii=False,
            )
        )


async def cmd_reply_errors(_args: argparse.Namespace) -> None:
    """Scenario B: Fake Hub injects HTTP 429 (exponential backoff >= Retry-After), 503, and 401 on outbound replies."""
    async with _new_http_client(timeout=20.0) as client:
        info = await _wait_for_ready(client, expected_workers=4)
        reg_before = int(info["hub_state"]["registration_seq"])
        await client.post(f"{HUB}/control/reset", json={"full": True})
        await client.post(
            f"{HUB}/control/inject_reply_errors",
            json={
                "queues": [
                    [{"status": 429, "retry_after": 1} for _ in range(4)],
                    [{"status": 503}, {"status": 503}],
                    [{"status": 401, "rotate": True}],
                ]
            },
        )
        llm_before = (await client.get(f"{FAKE_LLM}/stats")).json()["requests"]

        count = 3
        push_resp = (
            await client.post(
                f"{HUB}/control/push_tasks",
                json={"count": count, "prefix": "reply-err"},
            )
        ).json()
        expected_keys = {f"reply-{item['taskId']}" for item in push_resp["pushed"]}
        expected_seqs = {str(item["sequence"]) for item in push_resp["pushed"]}

        deadline = time.monotonic() + 90.0
        hub_state: dict[str, Any] = {}
        while time.monotonic() < deadline:
            hub_state = (await client.get(f"{HUB}/control/state")).json()
            if (
                hub_state["ack_total"] >= count
                and hub_state["inbound_replies_total"] >= count
                and len(hub_state.get("inbound_replies_by_key", {})) >= count
            ):
                break
            await asyncio.sleep(0.3)
        else:
            raise RuntimeError(f"Timed out waiting for reply-error recovery tasks: {hub_state}")

        await asyncio.sleep(1.5)
        hub_state = (await client.get(f"{HUB}/control/state")).json()
        llm_after = (await client.get(f"{FAKE_LLM}/stats")).json()["requests"]
        llm_delta = llm_after - llm_before

        ack_counts = hub_state["ack_counts"]
        reply_counts = hub_state["inbound_replies_by_key"]
        injected = hub_state.get("injected_reply_errors", {})

        assert set(ack_counts.keys()) == expected_seqs and all(v == 1 for v in ack_counts.values()), ack_counts
        assert set(reply_counts.keys()) == expected_keys and all(v == 1 for v in reply_counts.values()), reply_counts
        assert llm_delta == count, f"Expected {count} Brain/LLM requests across reply error retries, got {llm_delta}"

        # Assert 4x 429 grew via exponential backoff (2s, 4s, 8s, 16s even with Retry-After=1) within 10m window
        k429 = [entries for entries in injected.values() if sum(1 for e in entries if e["status"] == 429) == 4]
        assert k429, f"Expected one reply key to receive 4x HTTP 429 and recover, got {injected}"
        ts_429 = [e["ts"] for e in k429[0] if e["status"] == 429]
        gaps_429 = [round(ts_429[i + 1] - ts_429[i], 3) for i in range(len(ts_429) - 1)]
        assert len(gaps_429) == 3, gaps_429
        assert gaps_429[0] >= 1.7 and gaps_429[1] >= 3.5 and gaps_429[2] >= 7.5, (
            f"Expected exponential backoff ~2s, ~4s, ~8s across repeated 429s, got {gaps_429}"
        )
        assert gaps_429[2] > gaps_429[1] > gaps_429[0], f"Expected strictly increasing 429 gaps: {gaps_429}"

        # Assert 2x 503 had exponential backoff >= ~1.5s
        k503 = [entries for entries in injected.values() if sum(1 for e in entries if e["status"] == 503) == 2]
        assert k503, f"Expected one reply key to receive 2x HTTP 503, got {injected}"
        ts_503 = [e["ts"] for e in k503[0] if e["status"] == 503]
        gap_503 = round(ts_503[1] - ts_503[0], 3)
        assert gap_503 >= 1.5, f"Expected >= 1.5s exponential backoff between 503 retries, got {gap_503}s"

        # Assert 401 rotation triggered fresh registration and delivery
        k401 = [entries for entries in injected.values() if any(e["status"] == 401 for e in entries)]
        assert k401, f"Expected one reply key to receive injected HTTP 401, got {injected}"
        assert int(hub_state["registration_seq"]) > reg_before, hub_state

        print(
            json.dumps(
                {
                    "check": "reply_errors_recovery",
                    "pushed_tasks": count,
                    "brain_llm_calls": llm_delta,
                    "unique_replies_sent": len(reply_counts),
                    "total_replies": hub_state["inbound_replies_total"],
                    "injected_429_count": 4,
                    "injected_429_gaps_s": gaps_429,
                    "injected_503_count": 2,
                    "injected_503_gap_s": gap_503,
                    "injected_401_count": sum(1 for e in k401[0] if e["status"] == 401),
                    "registration_seq_before": reg_before,
                    "registration_seq_after": hub_state["registration_seq"],
                },
                ensure_ascii=False,
            )
        )


async def cmd_failover_prepare(_args: argparse.Namespace) -> None:
    async with _new_http_client(timeout=20.0) as client:
        info = await _wait_for_ready(client, expected_workers=4)
        await client.post(f"{HUB}/control/reset", json={"full": True})
        llm_before = (await client.get(f"{FAKE_LLM}/stats")).json()["requests"]

        # First run 8 tasks to completion so the queue is aligned and idle before pushing the 4 held tasks.
        push_init = (
            await client.post(
                f"{HUB}/control/push_tasks",
                json={"count": 8, "prefix": "pre-kill"},
            )
        ).json()
        dl_init = time.monotonic() + 30.0
        while time.monotonic() < dl_init:
            hub_state = (await client.get(f"{HUB}/control/state")).json()
            if hub_state["ack_total"] >= 8 and hub_state["inbound_replies_total"] >= 8:
                break
            await asyncio.sleep(0.15)
        else:
            raise RuntimeError("Timed out waiting for initial 8 pre-kill tasks to complete")

        # Brief settle so all 8 are committed COMPLETED and worker loop is idle before pushing the held batch of 4.
        await asyncio.sleep(0.6)
        await client.post(
            f"{HUB}/control/hold_replies",
            json={"hold_after": 8, "accept_before_hold": True},
        )
        push_held = (
            await client.post(
                f"{HUB}/control/push_tasks",
                json={"count": 4, "prefix": "pre-kill"},
            )
        ).json()
        push1_pushed = list(push_init["pushed"]) + list(push_held["pushed"])

        # Hold all 4 replies in-flight AFTER Hub accepted them (before mark_outbound_sent runs).
        dl = time.monotonic() + 10.0
        hub_state: dict[str, Any] = {}
        while time.monotonic() < dl:
            hub_state = (await client.get(f"{HUB}/control/state")).json()
            if (
                hub_state["ack_total"] >= 12
                and hub_state["inbound_replies_total"] >= 12
                and hub_state["held_reply_requests"] >= 4
                and len(hub_state.get("accepted_before_hold_by_key", {})) >= 4
            ):
                break
            await asyncio.sleep(0.15)
        else:
            raise RuntimeError(
                f"Timed out waiting for 8 completed + 4 Hub-accepted held PROCESSING events: {hub_state}"
            )
        await asyncio.sleep(0.3)
        llm_mid = (await client.get(f"{FAKE_LLM}/stats")).json()["requests"]
        assert llm_mid - llm_before == 12, f"Expected 12 Brain/LLM calls for batch1, got {llm_mid - llm_before}"

        db_path = Path(os.environ.get("A2A_QUEUE_DB_PATH", "/data/a2a/work_queue.db"))
        with sqlite3.connect(str(db_path)) as conn:
            conn.row_factory = sqlite3.Row
            proc_rows = conn.execute(
                "SELECT id, task_id, status, attempts, processing_owner, reply_task_id, reply_message FROM a2a_inbox_events WHERE status = 'PROCESSING' ORDER BY sequence ASC"
            ).fetchall()
            all_pre_kill = conn.execute(
                "SELECT id, sequence, task_id, status, attempts, processing_owner, error, reply_task_id FROM a2a_inbox_events WHERE task_id LIKE 'pre-kill-%' ORDER BY sequence ASC"
            ).fetchall()
            out_pending = conn.execute(
                "SELECT idempotency_key, task_id, status FROM a2a_outbound_tasks WHERE status = 'PENDING'"
            ).fetchall()
        assert len(proc_rows) == 4, (
            f"Expected 4 PROCESSING rows before kill, got {len(proc_rows)}; "
            f"all_pre_kill={[dict(r) for r in all_pre_kill]}; "
            f"out_pending={[dict(r) for r in out_pending]}; hub_state={hub_state}"
        )
        assert all(r["reply_task_id"] and r["reply_message"] for r in proc_rows), [dict(r) for r in proc_rows]
        pending_keys = {str(r["idempotency_key"]): str(r["task_id"]) for r in out_pending}
        accepted_map = hub_state.get("accepted_before_hold_by_key", {})
        assert len(accepted_map) == 4, accepted_map
        for idem, accepted_tid in accepted_map.items():
            assert pending_keys.get(idem) == accepted_tid, (idem, accepted_tid, pending_keys)
        processing_reply_task_ids = [str(r["reply_task_id"]) for r in proc_rows]

        leader_worker_id = info["leader"]
        leader_pid = int(leader_worker_id.split("-")[1])
        print(
            json.dumps(
                {
                    "leader_worker_id": leader_worker_id,
                    "leader_pid": leader_pid,
                    "llm_before": llm_before,
                    "batch1": push1_pushed,
                    "processing_count_before_kill": len(proc_rows),
                    "processing_reply_task_ids": processing_reply_task_ids,
                    "accepted_before_hold_by_key": accepted_map,
                },
                ensure_ascii=False,
            )
        )


async def cmd_failover_verify(args: argparse.Namespace) -> None:
    async with _new_http_client(timeout=20.0) as client:
        if args.wait_kill_stdin:
            await client.get(f"{HUB}/control/state")
            print("READY_FOR_KILL", flush=True)
            line = sys.stdin.readline().strip()
            if not line:
                raise RuntimeError("Missing kill epoch timestamp on stdin")
            kill_epoch = float(line)
        else:
            kill_epoch = time.time() - args.elapsed_before_poll

        await client.post(f"{HUB}/control/release_replies")
        push_task = asyncio.create_task(
            client.post(
                f"{HUB}/control/push_tasks",
                json={"count": 8, "prefix": "during-failover"},
            )
        )

        async def _probe_once() -> tuple[str | None, bool]:
            r = await client.get(f"{BACKEND}/api/v1/internal/a2a/peers", headers=HEADERS)
            if r.status_code != 200:
                return None, False
            data = r.json()
            return _extract_worker_id(r, data), bool(data.get("is_leader"))

        new_leader = None
        takeover_seconds = None
        deadline = time.monotonic() + max(15.0, args.ttl * 2.5)
        async with _rotate_accept_queue(client, 16):
            while time.monotonic() < deadline:
                try:
                    probes = await asyncio.gather(
                        *(_probe_once() for _ in range(24)),
                        return_exceptions=True,
                    )
                    for item in probes:
                        if (
                            isinstance(item, tuple)
                            and item[0]
                            and item[1]
                            and item[0] != args.old_leader_worker_id
                        ):
                            new_leader = item[0]
                            takeover_seconds = round(time.time() - kill_epoch, 3)
                            break
                    if new_leader:
                        break
                except Exception:
                    pass
                await asyncio.sleep(0.08)
        if not new_leader or takeover_seconds is None:
            raise RuntimeError("No replacement leader took over after leader kill")

        push2 = (await push_task).json()
        expected_total = 20
        dl = time.monotonic() + 60.0
        hub_state = {}
        while time.monotonic() < dl:
            hub_state = (await client.get(f"{HUB}/control/state")).json()
            if (
                hub_state["ack_total"] >= expected_total
                and hub_state["inbound_replies_total"] >= expected_total
                and len(hub_state.get("replayed_after_hold_by_key", {})) >= 4
            ):
                break
            await asyncio.sleep(0.3)
        else:
            raise RuntimeError(f"Failover tasks incomplete: {hub_state}")

        await asyncio.sleep(2.0)
        hub_state = (await client.get(f"{HUB}/control/state")).json()
        llm_after = (await client.get(f"{FAKE_LLM}/stats")).json()["requests"]
        llm_delta = llm_after - args.llm_before

        ack_counts = hub_state["ack_counts"]
        reply_counts = hub_state["inbound_replies_by_key"]
        delivered_task_ids = set(hub_state.get("inbound_reply_task_ids", []))
        accepted_map = hub_state.get("accepted_before_hold_by_key", {})
        replayed_map = hub_state.get("replayed_after_hold_by_key", {})
        expected_saved_task_ids = [
            tid.strip() for tid in (args.expected_reply_task_ids or "").split(",") if tid.strip()
        ]
        assert len(ack_counts) == expected_total and all(v == 1 for v in ack_counts.values()), ack_counts
        assert len(reply_counts) == expected_total and all(v == 1 for v in reply_counts.values()), reply_counts
        assert llm_delta == expected_total, f"Expected {expected_total} Brain/LLM requests, got {llm_delta}"
        assert 0.0 < takeover_seconds <= args.ttl, f"Takeover {takeover_seconds}s outside (0, {args.ttl}]"
        if expected_saved_task_ids:
            missing_ids = [tid for tid in expected_saved_task_ids if tid not in delivered_task_ids]
            assert not missing_ids, (
                f"Recovered PROCESSING replies did not preserve saved reply_task_ids: missing={missing_ids}"
            )
        assert len(accepted_map) == 4 and set(accepted_map.keys()) == set(replayed_map.keys()), (
            accepted_map,
            replayed_map,
        )
        for idem_k, orig_tid in accepted_map.items():
            assert replayed_map.get(idem_k) == [orig_tid], (
                f"Replay mismatch for {idem_k}: accepted={orig_tid}, replayed={replayed_map.get(idem_k)}"
            )

        # Ensure replacement worker brought worker pool back to 4 with strictly 1 leader.
        stabilized_workers, _ = await _sample_workers_with_hits(
            client, expected_workers=4, probes=32, strict_200=True, require_all=True
        )
        assert sum(1 for is_l in stabilized_workers.values() if is_l) == 1, stabilized_workers

        print(
            json.dumps(
                {
                    "check": "leader_failover",
                    "old_leader": args.old_leader_worker_id,
                    "new_leader": new_leader,
                    "lease_ttl_seconds": args.ttl,
                    "takeover_seconds": takeover_seconds,
                    "pushed_before_and_during": expected_total,
                    "recovered_processing_count": len(expected_saved_task_ids),
                    "preserved_reply_task_ids": expected_saved_task_ids,
                    "accepted_before_kill_replayed_same_keys_and_task_ids": {
                        k: {"before_kill_task_id": accepted_map[k], "replayed_task_ids": replayed_map[k]}
                        for k in sorted(accepted_map)
                    },
                    "unique_acks": len(ack_counts),
                    "total_acks": hub_state["ack_total"],
                    "unique_replies": len(reply_counts),
                    "total_replies": hub_state["inbound_replies_total"],
                    "brain_llm_calls_delta": llm_delta,
                    "workers_after_recovery": len(stabilized_workers),
                    "during_failover_seqs": [item["sequence"] for item in push2["pushed"]],
                },
                ensure_ascii=False,
            )
        )


async def cmd_mid_brain_prepare(_args: argparse.Namespace) -> None:
    """Scenario D prepare: Hold Brain/LLM mid-call so leader dies with reply_message IS NULL."""
    async with _new_http_client(timeout=20.0) as client:
        info = await _wait_for_ready(client, expected_workers=4)
        await client.post(f"{HUB}/control/reset", json={"full": True})
        stats_before = (await client.get(f"{FAKE_LLM}/stats")).json()
        llm_before = int(stats_before["requests"])
        held_before = int(stats_before.get("held_requests", 0))

        await client.post(f"{FAKE_LLM}/control/hold_chat", json={"count": 2})
        push = (
            await client.post(
                f"{HUB}/control/push_tasks",
                json={"count": 2, "prefix": "mid-brain"},
            )
        ).json()

        dl = time.monotonic() + 30.0
        while time.monotonic() < dl:
            hub_state = (await client.get(f"{HUB}/control/state")).json()
            stats_now = (await client.get(f"{FAKE_LLM}/stats")).json()
            if (
                hub_state["ack_total"] >= 2
                and (int(stats_now.get("held_requests", 0)) - held_before) >= 2
            ):
                break
            await asyncio.sleep(0.15)
        else:
            raise RuntimeError("Timed out waiting for 2 mid-Brain held requests")
        await asyncio.sleep(0.2)

        db_path = Path(os.environ.get("A2A_QUEUE_DB_PATH", "/data/a2a/work_queue.db"))
        with sqlite3.connect(str(db_path)) as conn:
            conn.row_factory = sqlite3.Row
            proc_rows = conn.execute(
                "SELECT id, task_id, status, reply_task_id, reply_message FROM a2a_inbox_events WHERE status = 'PROCESSING'"
            ).fetchall()
        assert len(proc_rows) == 2, [dict(r) for r in proc_rows]
        assert all(r["reply_message"] is None for r in proc_rows), [dict(r) for r in proc_rows]

        leader_worker_id = info["leader"]
        leader_pid = int(leader_worker_id.split("-")[1])
        print(
            json.dumps(
                {
                    "leader_worker_id": leader_worker_id,
                    "leader_pid": leader_pid,
                    "llm_before": llm_before,
                    "pushed": push["pushed"],
                },
                ensure_ascii=False,
            )
        )


async def cmd_mid_brain_verify(args: argparse.Namespace) -> None:
    """Scenario D verify: Release fake-llm after SIGKILL, confirm new leader completes with 1 reply/task."""
    async with _new_http_client(timeout=20.0) as client:
        if args.wait_kill_stdin:
            await client.get(f"{HUB}/control/state")
            print("READY_FOR_KILL", flush=True)
            line = sys.stdin.readline().strip()
            if not line:
                raise RuntimeError("Missing kill epoch timestamp on stdin")
            kill_epoch = float(line)
        else:
            kill_epoch = time.time()

        await client.post(f"{FAKE_LLM}/control/release_chat")

        async def _probe_once() -> tuple[str | None, bool]:
            r = await client.get(f"{BACKEND}/api/v1/internal/a2a/peers", headers=HEADERS)
            if r.status_code != 200:
                return None, False
            data = r.json()
            return _extract_worker_id(r, data), bool(data.get("is_leader"))

        new_leader = None
        takeover_seconds = None
        deadline = time.monotonic() + max(15.0, args.ttl * 2.5)
        async with _rotate_accept_queue(client, 16):
            while time.monotonic() < deadline:
                try:
                    probes = await asyncio.gather(
                        *(_probe_once() for _ in range(24)),
                        return_exceptions=True,
                    )
                    for item in probes:
                        if (
                            isinstance(item, tuple)
                            and item[0]
                            and item[1]
                            and item[0] != args.old_leader_worker_id
                        ):
                            new_leader = item[0]
                            takeover_seconds = round(time.time() - kill_epoch, 3)
                            break
                    if new_leader:
                        break
                except Exception:
                    pass
                await asyncio.sleep(0.08)
        if not new_leader or takeover_seconds is None:
            raise RuntimeError("No replacement leader took over after mid-Brain kill")

        dl = time.monotonic() + 45.0
        hub_state: dict[str, Any] = {}
        while time.monotonic() < dl:
            hub_state = (await client.get(f"{HUB}/control/state")).json()
            if hub_state["ack_total"] >= 2 and hub_state["inbound_replies_total"] >= 2:
                break
            await asyncio.sleep(0.25)
        else:
            raise RuntimeError(f"Mid-Brain recovery incomplete: {hub_state}")

        await asyncio.sleep(2.0)
        hub_state = (await client.get(f"{HUB}/control/state")).json()
        llm_after = (await client.get(f"{FAKE_LLM}/stats")).json()["requests"]
        llm_delta = llm_after - args.llm_before

        ack_counts = hub_state["ack_counts"]
        reply_counts = hub_state["inbound_replies_by_key"]
        assert len(ack_counts) == 2 and all(v == 1 for v in ack_counts.values()), ack_counts
        assert len(reply_counts) == 2 and all(v == 1 for v in reply_counts.values()), reply_counts
        assert hub_state["inbound_replies_total"] == 2, hub_state
        # 2 aborted calls on killed leader + 2 completed calls on new leader == 4
        assert llm_delta == 4, f"Expected 4 Brain calls (2 aborted + 2 recovery), got {llm_delta}"
        stabilized_workers, _ = await _sample_workers_with_hits(
            client, expected_workers=4, probes=32, strict_200=True, require_all=True
        )
        assert sum(1 for is_l in stabilized_workers.values() if is_l) == 1, stabilized_workers

        print(
            json.dumps(
                {
                    "check": "mid_brain_kill_recovery",
                    "old_leader": args.old_leader_worker_id,
                    "new_leader": new_leader,
                    "takeover_seconds": takeover_seconds,
                    "tasks_pushed": 2,
                    "brain_llm_calls_delta": llm_delta,
                    "unique_replies": len(reply_counts),
                    "total_replies": hub_state["inbound_replies_total"],
                    "workers_after_recovery": len(stabilized_workers),
                },
                ensure_ascii=False,
            )
        )


async def cmd_stale_leader_prepare(_args: argparse.Namespace) -> None:
    """Scenario A prepare: Push 2 tasks held in Brain so old leader holds PROCESSING when SIGSTOPped."""
    async with _new_http_client(timeout=20.0) as client:
        info = await _wait_for_ready(client, expected_workers=4)
        await client.post(f"{HUB}/control/reset", json={"full": True})
        stats_before = (await client.get(f"{FAKE_LLM}/stats")).json()
        llm_before = int(stats_before["requests"])
        held_before = int(stats_before.get("held_requests", 0))

        await client.post(f"{FAKE_LLM}/control/hold_chat", json={"count": 2})
        push = (
            await client.post(
                f"{HUB}/control/push_tasks",
                json={"count": 2, "prefix": "sigstop-pre"},
            )
        ).json()

        dl = time.monotonic() + 30.0
        while time.monotonic() < dl:
            hub_state = (await client.get(f"{HUB}/control/state")).json()
            stats_now = (await client.get(f"{FAKE_LLM}/stats")).json()
            if (
                hub_state["ack_total"] >= 2
                and (int(stats_now.get("held_requests", 0)) - held_before) >= 2
            ):
                break
            await asyncio.sleep(0.15)
        else:
            raise RuntimeError("Timed out waiting for sigstop-pre Brain calls")

        leader_worker_id = info["leader"]
        leader_pid = int(leader_worker_id.split("-")[1])
        print(
            json.dumps(
                {
                    "leader_worker_id": leader_worker_id,
                    "leader_pid": leader_pid,
                    "llm_before": llm_before,
                    "pushed": push["pushed"],
                },
                ensure_ascii=False,
            )
        )


async def cmd_stale_leader_verify(args: argparse.Namespace) -> None:
    """Scenario A verify: After SIGCONT of stale leader, push 4 more tasks and assert zero split-brain/dup replies."""
    async with _new_http_client(timeout=20.0) as client:
        await client.post(f"{FAKE_LLM}/control/release_chat")
        await client.post(
            f"{HUB}/control/push_tasks",
            json={"count": 4, "prefix": "sigstop-post"},
        )

        expected_total = 6
        dl = time.monotonic() + 60.0
        hub_state: dict[str, Any] = {}
        while time.monotonic() < dl:
            hub_state = (await client.get(f"{HUB}/control/state")).json()
            if (
                hub_state["ack_total"] >= expected_total
                and hub_state["inbound_replies_total"] >= expected_total
            ):
                break
            await asyncio.sleep(0.25)
        else:
            raise RuntimeError(f"Stale-leader SIGSTOP/SIGCONT scenario incomplete: {hub_state}")

        await asyncio.sleep(2.5)
        hub_state = (await client.get(f"{HUB}/control/state")).json()
        llm_after = (await client.get(f"{FAKE_LLM}/stats")).json()["requests"]
        llm_delta = llm_after - args.llm_before

        workers, hits = await _sample_workers_with_hits(
            client, expected_workers=4, probes=32, strict_200=True, require_all=True
        )
        leaders = [w for w, is_l in workers.items() if is_l]
        assert len(leaders) == 1, workers
        assert leaders[0] != args.old_leader_worker_id, (
            f"Stale resumed leader {args.old_leader_worker_id} unexpectedly holds leadership: {workers}"
        )
        assert args.old_leader_worker_id in workers, (
            f"Expected resumed old leader {args.old_leader_worker_id} to be alive and responding, got {workers}"
        )
        assert workers[args.old_leader_worker_id] is False, workers
        assert hub_state.get("active_sse_streams") == 1, hub_state

        ack_counts = hub_state["ack_counts"]
        reply_counts = hub_state["inbound_replies_by_key"]
        assert len(ack_counts) == expected_total and all(v == 1 for v in ack_counts.values()), ack_counts
        assert len(reply_counts) == expected_total and all(v == 1 for v in reply_counts.values()), reply_counts
        assert hub_state["inbound_replies_total"] == expected_total, hub_state
        # 2 paused before SIGSTOP + 2 completed by new leader + 4 post tasks = 8
        assert llm_delta == 8, f"Expected 8 Brain calls across SIGSTOP/SIGCONT recovery, got {llm_delta}"

        print(
            json.dumps(
                {
                    "check": "stale_live_leader_sigstop_sigcont",
                    "old_leader": args.old_leader_worker_id,
                    "new_leader": leaders[0],
                    "old_leader_abdicated_alive": True,
                    "workers_seen": len(workers),
                    "leader_count": len(leaders),
                    "active_sse_streams": hub_state.get("active_sse_streams"),
                    "total_tasks": expected_total,
                    "unique_replies": len(reply_counts),
                    "total_replies": hub_state["inbound_replies_total"],
                    "brain_llm_calls_delta": llm_delta,
                    "worker_hits": dict(hits),
                },
                ensure_ascii=False,
            )
        )


async def cmd_rate_limit(args: argparse.Namespace) -> None:
    limit = args.limit
    initial_burst = limit * 3
    async with _new_http_client(timeout=20.0) as client:
        await _wait_for_ready(client, expected_workers=4)
        await client.post(f"{HUB}/control/reset", json={"full": True})

        async def send_one(i: int):
            r = await client.post(
                f"{BACKEND}/api/v1/internal/a2a/tasks",
                headers=HEADERS,
                json={"target_agent_id": "peer-alpha", "message": f"rl-{i}"},
            )
            body = r.json() if r.headers.get("content-type", "").startswith("application/json") else None
            wid = _extract_worker_id(r, body)
            return r.status_code, r.headers.get("Retry-After"), wid

        # Part A: Burst initial_burst requests simultaneously, then follow-up bursts (all 429) if needed until all 4 workers appear.
        async def _stagger_send(idx_val: int, j: int):
            await asyncio.sleep((j % 8) * 0.002)
            return await send_one(idx_val + j)

        async with _rotate_accept_queue(client, 16):
            results = list(await asyncio.gather(*(_stagger_send(0, j) for j in range(initial_burst))))
            next_idx = initial_burst
            for _ in range(15):
                seen_workers = {wid for _, _, wid in results if wid}
                if len(seen_workers) >= 4:
                    break
                await asyncio.sleep(0.04)
                more = await asyncio.gather(*(_stagger_send(next_idx, j) for j in range(32)))
                next_idx += 32
                results.extend(more)

        statuses = Counter(code for code, _, _ in results)
        retry_afters = [ra for code, ra, _ in results if code == 429]
        worker_hits = Counter(wid for _, _, wid in results if wid)
        worker_hits_200 = Counter(wid for code, _, wid in results if code == 200 and wid)
        worker_hits_429 = Counter(wid for code, _, wid in results if code == 429 and wid)
        hub_state = (await client.get(f"{HUB}/control/state")).json()

        assert statuses == {200: limit, 429: len(results) - limit}, f"Unexpected rate limit split: {statuses}"
        assert hub_state["outbound_tasks_count"] == limit, hub_state
        assert all(ra and int(ra) >= 1 for ra in retry_afters), retry_afters
        assert len(worker_hits) == 4, f"Expected all 4 workers in rate-limit burst, got {dict(worker_hits)}"

        # Part B: 401 credential reload retry right at the rate-limit boundary (limit-th slot must succeed, (limit+1)-th 429).
        redis_client = aioredis.from_url(os.environ.get("REDIS_URL", "redis://redis:6379"))
        try:
            keys = await redis_client.keys("vman:a2a-rate:*")
            if keys:
                await redis_client.delete(*keys)
        finally:
            await redis_client.aclose()

        await client.post(f"{HUB}/control/reset", json={"full": False})
        _, warm_hits = await _sample_workers_with_hits(
            client, expected_workers=4, probes=32, strict_200=True, require_all=True
        )

        # Spend (limit - 1) slots so exactly 1 slot remains before hitting limit.
        pre_res = await asyncio.gather(*(send_one(1000 + i) for i in range(limit - 1)))
        assert all(code == 200 for code, _, _ in pre_res), pre_res

        # Silently rotate active token in fake-hub and overwrite credentials.json preserving (mtime_ns, ino, size)
        # so whichever worker receives request #limit starts with cached old_token -> 401 -> reloads new_token -> 200.
        rot = (await client.post(f"{HUB}/control/rotate_silent")).json()
        creds_path = Path(os.environ.get("A2A_CREDENTIALS_PATH", "/data/a2a/credentials.json"))
        enc_key = os.environ["SESSION_JWT_SECRET"]
        hub_url = os.environ.get("A2A_HUB_URL", HUB)
        hub_key = os.environ["A2A_HUB_KEY"]
        store = A2ACredentialStore(creds_path, enc_key)
        existing = store.load(expected_hub_url=hub_url, current_hub_key=hub_key)
        assert existing is not None
        orig_stat = creds_path.stat()
        tmp_creds = Path("/tmp/a2a-silent-rot.json")
        tmp_store = A2ACredentialStore(tmp_creds, enc_key)
        tmp_store.save(existing.model_copy(update={"agent_token": rot["agentToken"]}))
        rotated_bytes = tmp_creds.read_bytes()
        tmp_creds.unlink(missing_ok=True)
        assert len(rotated_bytes) == orig_stat.st_size, (len(rotated_bytes), orig_stat.st_size)
        with open(creds_path, "r+b") as fh:
            fh.write(rotated_bytes)
            fh.truncate()
        os.chmod(creds_path, 0o600)
        os.utime(creds_path, ns=(orig_stat.st_atime_ns, orig_stat.st_mtime_ns))

        boundary_status, _, boundary_wid = await send_one(2000)
        over_status, over_ra, over_wid = await send_one(2001)
        boundary_hub_state = (await client.get(f"{HUB}/control/state")).json()

        assert boundary_status == 200, (
            f"Expected 401 retry at {limit}/{limit} boundary to succeed with 200, got {boundary_status}"
        )
        assert over_status == 429 and over_ra and int(over_ra) >= 1, (over_status, over_ra)
        assert boundary_hub_state["outbound_tasks_count"] == limit, boundary_hub_state
        assert any(
            f["endpoint"] == "tasks" and f["token"] == rot["previous_token"]
            for f in boundary_hub_state["auth_failures"]
        ), boundary_hub_state["auth_failures"]
        assert any(
            t["endpoint"] == "tasks" and t["token"] == rot["agentToken"]
            for t in boundary_hub_state["tokens_seen"]
        ), boundary_hub_state["tokens_seen"]

        print(
            json.dumps(
                {
                    "check": "shared_rate_limit",
                    "configured_limit": limit,
                    "total_requests": len(results),
                    "allowed_200": statuses[200],
                    "blocked_429": statuses[429],
                    "hub_tasks_received": hub_state["outbound_tasks_count"],
                    "worker_hits": dict(worker_hits),
                    "worker_hits_200": dict(worker_hits_200),
                    "worker_hits_429": dict(worker_hits_429),
                    "boundary_401_retry": {
                        "warm_workers": len(warm_hits),
                        "boundary_request_status": boundary_status,
                        "boundary_worker_id": boundary_wid,
                        "over_limit_request_status": over_status,
                        "over_limit_retry_after": over_ra,
                        "over_limit_worker_id": over_wid,
                        "hub_auth_failures_recorded": len(boundary_hub_state["auth_failures"]),
                        "hub_tasks_delivered": boundary_hub_state["outbound_tasks_count"],
                    },
                },
                ensure_ascii=False,
            )
        )


async def cmd_cert_rotation(_args: argparse.Namespace) -> None:
    async with _new_http_client(timeout=20.0) as client:
        info = await _wait_for_ready(client, expected_workers=4)
        old_token = info["hub_state"]["active_token"]

        # Warm all processes so non-leaders cache the old credentials in memory
        await _sample_workers_with_hits(client, expected_workers=4, probes=32, strict_200=True, require_all=True)
        await client.post(f"{HUB}/control/rotate_token")

        new_token = None
        deadline = time.monotonic() + 20.0
        while time.monotonic() < deadline:
            hub_state = (await client.get(f"{HUB}/control/state")).json()
            cand = hub_state.get("active_token")
            if cand and cand != old_token and hub_state.get("active_sse_streams", 0) >= 1:
                new_token = cand
                break
            await asyncio.sleep(0.2)
        if not new_token:
            raise RuntimeError("Leader did not rotate and register a new token in time")

        await client.post(f"{HUB}/control/reset", json={"full": False})

        async def call_peers(_i: int = 0):
            r = await client.get(f"{BACKEND}/api/v1/internal/a2a/peers", headers=HEADERS)
            body = r.json() if r.headers.get("content-type", "").startswith("application/json") else {}
            wid = _extract_worker_id(r, body)
            return r.status_code, body.get("is_leader"), wid

        peers_res = await _gather_until_all_workers(client, call_peers, expected_workers=4, batch_size=24)
        task_resp = await client.post(
            f"{BACKEND}/api/v1/internal/a2a/tasks",
            headers=HEADERS,
            json={"target_agent_id": "peer-alpha", "message": "post-rotation"},
        )
        hub_state = (await client.get(f"{HUB}/control/state")).json()
        tokens_used = {entry["token"] for entry in hub_state["tokens_seen"] if entry["endpoint"] in ("peers", "tasks")}
        non_leader_calls = sum(1 for code, is_l, _ in peers_res if code == 200 and is_l is False)
        post_rotation_worker_hits = Counter(wid for _, _, wid in peers_res if wid)

        assert all(code == 200 for code, _, _ in peers_res), peers_res
        assert task_resp.status_code == 200, task_resp.text
        assert len(post_rotation_worker_hits) == 4 and non_leader_calls > 0, (post_rotation_worker_hits, non_leader_calls)
        assert tokens_used == {new_token}, (tokens_used, old_token, new_token)

        # Interleaved read / delete / recreate stress across all 4 workers.
        creds_path = Path(os.environ.get("A2A_CREDENTIALS_PATH", "/data/a2a/credentials.json"))
        valid_bytes = creds_path.read_bytes()

        def _atomic_restore() -> None:
            tmp_path = creds_path.with_name(f".restore.{os.getpid()}.tmp")
            tmp_path.write_bytes(valid_bytes)
            os.chmod(tmp_path, 0o600)
            os.replace(tmp_path, creds_path)

        creds_path.unlink(missing_ok=True)
        missing_res = await _gather_until_all_workers(client, call_peers, expected_workers=4, batch_size=24)
        missing_statuses = Counter(code for code, _, _ in missing_res)
        missing_worker_hits = Counter(wid for _, _, wid in missing_res if wid)
        assert missing_statuses == {503: len(missing_res)}, missing_statuses
        assert len(missing_worker_hits) == 4, missing_worker_hits

        toggle_done = asyncio.Event()
        toggle_counts = {"deletes": 0, "writes": 0}

        async def _writer_loop() -> None:
            try:
                for idx in range(36):
                    if idx % 2 == 0:
                        creds_path.unlink(missing_ok=True)
                        toggle_counts["deletes"] += 1
                    else:
                        _atomic_restore()
                        toggle_counts["writes"] += 1
                    await asyncio.sleep(0.025)
            finally:
                _atomic_restore()
                toggle_done.set()

        async def _reader_wave() -> list[tuple[int, str | None]]:
            out: list[tuple[int, str | None]] = []
            async with _rotate_accept_queue(client, 16):
                for wave in range(30):
                    async def _probe_one(k: int) -> tuple[int, str | None]:
                        await asyncio.sleep((k % 8) * 0.002)
                        if k % 4 == 0:
                            r = await client.post(
                                f"{BACKEND}/api/v1/internal/a2a/tasks",
                                headers=HEADERS,
                                json={"target_agent_id": "peer-alpha", "message": f"interleaved-{wave}-{k}"},
                            )
                        else:
                            r = await client.get(f"{BACKEND}/api/v1/internal/a2a/peers", headers=HEADERS)
                        body = r.json() if r.headers.get("content-type", "").startswith("application/json") else None
                        return r.status_code, _extract_worker_id(r, body)

                    batch = await asyncio.gather(*(_probe_one(k) for k in range(16)))
                    out.extend(batch)
                    if toggle_done.is_set() and len({wid for _, wid in out if wid}) >= 4:
                        break
                    await asyncio.sleep(0.025)
            return out

        _, interleaved_res = await asyncio.gather(_writer_loop(), _reader_wave())
        interleaved_statuses = Counter(code for code, _ in interleaved_res)
        interleaved_worker_hits = Counter(wid for _, wid in interleaved_res if wid)
        assert set(interleaved_statuses.keys()).issubset({200, 503}), interleaved_statuses
        assert interleaved_statuses.get(200, 0) > 0 and interleaved_statuses.get(503, 0) > 0, interleaved_statuses
        assert len(interleaved_worker_hits) == 4, interleaved_worker_hits

        # After atomic restoration, all 4 workers return 200 again.
        restored_workers, restored_hits = await _sample_workers_with_hits(
            client, expected_workers=4, probes=32, strict_200=True, require_all=True
        )
        assert len(restored_workers) == 4

        print(
            json.dumps(
                {
                    "check": "credential_rotation",
                    "old_token": old_token,
                    "new_token": new_token,
                    "peers_200_count": len(peers_res),
                    "non_leader_200_count": non_leader_calls,
                    "post_rotation_worker_hits": dict(post_rotation_worker_hits),
                    "task_post_status": task_resp.status_code,
                    "hub_tokens_observed": sorted(tokens_used),
                    "interleaved_delete_recreate": {
                        "missing_503_count": missing_statuses[503],
                        "missing_worker_hits": dict(missing_worker_hits),
                        "toggle_counts": toggle_counts,
                        "interleaved_statuses": dict(interleaved_statuses),
                        "interleaved_worker_hits": dict(interleaved_worker_hits),
                        "restored_worker_hits": dict(restored_hits),
                    },
                },
                ensure_ascii=False,
            )
        )


async def cmd_inspect_leaders(args: argparse.Namespace) -> None:
    async with _new_http_client(timeout=20.0) as client:
        deadline = time.monotonic() + args.wait_seconds
        last: dict[str, Any] = {}
        while True:
            try:
                workers, peers_hits = await _sample_workers_with_hits(
                    client,
                    expected_workers=args.expect_workers,
                    probes=32,
                    strict_200=True,
                    require_all=False,
                )
            except AssertionError as exc:
                if time.monotonic() >= deadline:
                    raise AssertionError(f"Worker /peers sampling failed: {exc}; last={last}") from exc
                await asyncio.sleep(0.3)
                continue

            hub_state = (await client.get(f"{HUB}/control/state")).json()
            leaders = sorted(w for w, is_l in workers.items() if is_l)
            last = {
                "workers_seen": len(workers),
                "workers": workers,
                "peers_worker_hits": dict(peers_hits),
                "leaders": leaders,
                "leader_count": len(leaders),
                "active_sse_streams": hub_state.get("active_sse_streams", 0),
            }
            if (
                len(workers) == args.expect_workers
                and (args.expect_leaders is None or len(leaders) == args.expect_leaders)
                and (args.expect_streams is None or last["active_sse_streams"] == args.expect_streams)
            ):
                if args.probe_tasks > 0:
                    async def _send_probe(i: int) -> tuple[int, str | None]:
                        r = await client.post(
                            f"{BACKEND}/api/v1/internal/a2a/tasks",
                            headers=HEADERS,
                            json={"target_agent_id": "peer-alpha", "message": f"probe-{i}"},
                        )
                        body = r.json() if r.headers.get("content-type", "").startswith("application/json") else None
                        return r.status_code, _extract_worker_id(r, body)

                    task_res = await _gather_until_all_workers(
                        client,
                        _send_probe,
                        expected_workers=args.expect_workers,
                        batch_size=max(24, args.probe_tasks // 2),
                        max_rounds=15,
                    )
                    task_statuses = Counter(code for code, _ in task_res)
                    tasks_hits = Counter(wid for _, wid in task_res if wid)
                    assert task_statuses == {200: len(task_res)}, (
                        f"Expected all HTTP 200 on /tasks during inspection, got {task_statuses}"
                    )
                    assert len(tasks_hits) == args.expect_workers, (
                        f"Expected all {args.expect_workers} workers on /tasks, got {dict(tasks_hits)}"
                    )
                    last["tasks_worker_hits"] = dict(tasks_hits)
                break
            if time.monotonic() >= deadline:
                raise AssertionError(
                    f"Expected workers={args.expect_workers}, leaders={args.expect_leaders}, "
                    f"streams={args.expect_streams}; got {last}"
                )
            await asyncio.sleep(0.3)
        print(json.dumps(last, ensure_ascii=False))


async def _get_redis_lease_owner(redis_client: aioredis.Redis) -> tuple[str | None, str | None, int]:
    keys = await redis_client.keys("a2a:leader:lease:*")
    if not keys:
        return None, None, -2
    key = keys[0].decode("utf-8", errors="replace") if isinstance(keys[0], bytes) else str(keys[0])
    val = await redis_client.get(keys[0])
    pttl = int(await redis_client.pttl(keys[0]))
    owner = val.decode("utf-8", errors="replace") if isinstance(val, bytes) else (str(val) if val else None)
    return key, owner, pttl


async def cmd_reaper_and_deadline(_args: argparse.Namespace) -> None:
    """Verify periodic orphan reaper recovers stuck local PROCESSING rows and enforces 10-minute retry deadline."""
    from datetime import datetime, timedelta, timezone

    async with _new_http_client(timeout=20.0) as client:
        await _wait_for_ready(client, expected_workers=4)
        await client.post(f"{HUB}/control/reset", json={"full": True})

        # Push one seed task so work_queue.db has the exact live hub_scope and requester_agent_id.
        seed_push = (
            await client.post(
                f"{HUB}/control/push_tasks",
                json={"count": 1, "prefix": "reaper-seed"},
            )
        ).json()
        seed_task_id = str(seed_push["pushed"][0]["taskId"])
        dl_seed = time.monotonic() + 30.0
        while time.monotonic() < dl_seed:
            hub_state = (await client.get(f"{HUB}/control/state")).json()
            if hub_state["ack_total"] >= 1 and hub_state["inbound_replies_total"] >= 1:
                break
            await asyncio.sleep(0.15)
        else:
            raise RuntimeError("Timed out waiting for reaper-seed task")
        await asyncio.sleep(0.4)

        llm_after_seed = (await client.get(f"{FAKE_LLM}/stats")).json()["requests"]
        db_path = Path(os.environ.get("A2A_QUEUE_DB_PATH", "/data/a2a/work_queue.db"))
        redis_client = aioredis.from_url(os.environ.get("REDIS_URL", "redis://redis:6379"))
        try:
            _, current_leader, _ = await _get_redis_lease_owner(redis_client)
        finally:
            await redis_client.aclose()
        assert current_leader, "Expected an active Redis lease owner before reaper test"

        with sqlite3.connect(str(db_path)) as conn:
            conn.row_factory = sqlite3.Row
            seed_row = conn.execute(
                "SELECT hub_scope, requester_agent_id, group_id, context_id FROM a2a_inbox_events WHERE task_id = ?",
                (seed_task_id,),
            ).fetchone()
            assert seed_row is not None
            min_seq_row = conn.execute(
                "SELECT COALESCE(MIN(sequence), 0) AS min_seq FROM a2a_inbox_events WHERE hub_scope = ?",
                (seed_row["hub_scope"],),
            ).fetchone()
            # Keep synthetic sequences strictly negative so get_last_processed_sequence() MAX(sequence) stays at seed_row.
            base_seq = min(0, int(min_seq_row["min_seq"])) - 10

            now_dt = datetime.now(timezone.utc)
            now_iso = now_dt.isoformat()
            expired_iso = (now_dt - timedelta(minutes=15)).isoformat()

            conn.execute(
                """
                INSERT INTO a2a_inbox_events (
                    hub_scope, sequence, task_id, context_id, requester_agent_id, group_id,
                    message, status, ack_dispatched_at, reply_task_id, reply_message,
                    attempts, first_failed_at, processing_owner, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, 'PROCESSING', ?, ?, ?, 0, NULL, ?, ?, ?)
                """,
                (
                    seed_row["hub_scope"],
                    base_seq,
                    "orphan-reaper-task",
                    seed_row["context_id"] or "ctx-orphan",
                    seed_row["requester_agent_id"],
                    seed_row["group_id"] or "",
                    "orphan task prompt",
                    now_iso,
                    "reply-orphan-reaper-fixed",
                    "Orphan Recovered Reply",
                    current_leader,
                    now_iso,
                    now_iso,
                ),
            )
            conn.execute(
                """
                INSERT INTO a2a_inbox_events (
                    hub_scope, sequence, task_id, context_id, requester_agent_id, group_id,
                    message, status, ack_dispatched_at, reply_task_id, reply_message,
                    attempts, first_failed_at, processing_owner, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, 'PROCESSING', ?, ?, ?, 3, ?, ?, ?, ?)
                """,
                (
                    seed_row["hub_scope"],
                    base_seq + 1,
                    "expired-deadline-task",
                    seed_row["context_id"] or "ctx-expired",
                    seed_row["requester_agent_id"],
                    seed_row["group_id"] or "",
                    "expired task prompt",
                    now_iso,
                    "reply-expired-never",
                    "Expired Reply Never Sent",
                    expired_iso,
                    current_leader,
                    expired_iso,
                    now_iso,
                ),
            )
            conn.commit()

        # Periodic orphan sweep (A2A_ORPHAN_SWEEP_INTERVAL_SECONDS=3 in acceptance) runs without any leader change.
        dl = time.monotonic() + 20.0
        orphan_status = None
        expired_status = None
        hub_state: dict[str, Any] = {}
        while time.monotonic() < dl:
            hub_state = (await client.get(f"{HUB}/control/state")).json()
            with sqlite3.connect(str(db_path)) as conn:
                conn.row_factory = sqlite3.Row
                r_orp = conn.execute(
                    "SELECT status FROM a2a_inbox_events WHERE task_id = 'orphan-reaper-task'"
                ).fetchone()
                r_exp = conn.execute(
                    "SELECT status FROM a2a_inbox_events WHERE task_id = 'expired-deadline-task'"
                ).fetchone()
                orphan_status = r_orp["status"] if r_orp else None
                expired_status = r_exp["status"] if r_exp else None
            if (
                orphan_status == "COMPLETED"
                and expired_status == "FAILED"
                and hub_state.get("inbound_replies_by_key", {}).get("reply-orphan-reaper-task") == 1
            ):
                break
            await asyncio.sleep(0.3)
        else:
            raise RuntimeError(
                f"Timed out waiting for reaper/deadline cleanup: orphan={orphan_status}, "
                f"expired={expired_status}, hub_replies={hub_state.get('inbound_replies_by_key')}"
            )

        await asyncio.sleep(1.0)
        hub_state = (await client.get(f"{HUB}/control/state")).json()
        llm_after = (await client.get(f"{FAKE_LLM}/stats")).json()["requests"]
        llm_delta_after_seed = llm_after - llm_after_seed

        assert llm_delta_after_seed == 0, f"Expected 0 extra Brain calls during orphan/deadline sweep, got {llm_delta_after_seed}"
        assert "reply-orphan-reaper-fixed" in hub_state.get("inbound_reply_task_ids", []), hub_state
        assert "reply-expired-deadline-task" not in hub_state.get("inbound_replies_by_key", {}), hub_state
        assert "reply-expired-never" not in hub_state.get("inbound_reply_task_ids", []), hub_state

        print(
            json.dumps(
                {
                    "check": "reaper_and_deadline",
                    "leader_worker_id": current_leader,
                    "orphan_status": orphan_status,
                    "expired_status": expired_status,
                    "orphan_reply_task_id": "reply-orphan-reaper-fixed",
                    "extra_brain_calls": llm_delta_after_seed,
                    "replies_by_key": hub_state.get("inbound_replies_by_key"),
                },
                ensure_ascii=False,
            )
        )


async def cmd_redis_setnx_prepare(_args: argparse.Namespace) -> None:
    """Prepare held Brain request for Redis SET NX same-leader re-acquisition test."""
    async with _new_http_client(timeout=20.0) as client:
        info = await _wait_for_ready(client, expected_workers=4)
        await client.post(f"{HUB}/control/reset", json={"full": True})
        stats_before = (await client.get(f"{FAKE_LLM}/stats")).json()
        llm_before = int(stats_before["requests"])
        held_before = int(stats_before.get("held_requests", 0))

        redis_client = aioredis.from_url(os.environ.get("REDIS_URL", "redis://redis:6379"))
        try:
            _, leader_worker_id, _ = await _get_redis_lease_owner(redis_client)
        finally:
            await redis_client.aclose()
        assert leader_worker_id, "Expected active Redis lease owner before SET NX prepare"

        leader_pid = int(leader_worker_id.split("-")[1])
        other_pids = [
            int(wid.split("-")[1])
            for wid in info["workers"]
            if wid != leader_worker_id
        ]
        assert len(other_pids) == 3, info

        await client.post(f"{FAKE_LLM}/control/hold_chat", json={"count": 1})
        push = (
            await client.post(
                f"{HUB}/control/push_tasks",
                json={"count": 1, "prefix": "setnx-live"},
            )
        ).json()

        dl_hold = time.monotonic() + 25.0
        while time.monotonic() < dl_hold:
            hub_state = (await client.get(f"{HUB}/control/state")).json()
            stats_now = (await client.get(f"{FAKE_LLM}/stats")).json()
            if (
                hub_state["ack_total"] >= 1
                and (int(stats_now.get("held_requests", 0)) - held_before) >= 1
            ):
                break
            await asyncio.sleep(0.15)
        else:
            await client.post(f"{FAKE_LLM}/control/release_chat")
            raise RuntimeError("Timed out waiting for held Brain request before Redis SET NX test")

        print(
            json.dumps(
                {
                    "leader_worker_id": leader_worker_id,
                    "leader_pid": leader_pid,
                    "other_pids": other_pids,
                    "llm_before": llm_before,
                    "pushed": push["pushed"],
                },
                ensure_ascii=False,
            )
        )


async def cmd_redis_setnx_verify(args: argparse.Namespace) -> None:
    """Release held Brain request after same-leader SET NX re-acquisition and verify zero re-calls."""
    async with _new_http_client(timeout=20.0) as client:
        await client.post(f"{FAKE_LLM}/control/release_chat")
        dl_reply = time.monotonic() + 30.0
        hub_state: dict[str, Any] = {}
        while time.monotonic() < dl_reply:
            hub_state = (await client.get(f"{HUB}/control/state")).json()
            if hub_state["ack_total"] >= 1 and hub_state["inbound_replies_total"] >= 1:
                break
            await asyncio.sleep(0.2)
        else:
            raise RuntimeError(f"Timed out waiting for reply after Redis SET NX test: {hub_state}")

        await asyncio.sleep(1.0)
        hub_state = (await client.get(f"{HUB}/control/state")).json()
        llm_after = int((await client.get(f"{FAKE_LLM}/stats")).json()["requests"])
        llm_delta = llm_after - args.llm_before

        assert llm_delta == 1, (
            f"SET NX re-acquisition by same leader {args.leader_worker_id} re-called Brain ({llm_delta} calls)"
        )
        assert len(hub_state["inbound_replies_by_key"]) == 1, hub_state
        assert hub_state["inbound_replies_total"] == 1, hub_state
        workers, _ = await _sample_workers_with_hits(
            client, expected_workers=4, probes=32, strict_200=True, require_all=True
        )
        assert workers.get(args.leader_worker_id) is True, workers

        print(
            json.dumps(
                {
                    "check": "redis_setnx_reacquire",
                    "leader_worker_id": args.leader_worker_id,
                    "reacquired_owner": args.reacquired_owner,
                    "brain_llm_calls_delta": llm_delta,
                    "unique_replies": len(hub_state["inbound_replies_by_key"]),
                    "total_replies": hub_state["inbound_replies_total"],
                    "workers_after": len(workers),
                },
                ensure_ascii=False,
            )
        )


def main() -> None:
    parser = argparse.ArgumentParser()
    sub = parser.add_subparsers(dest="cmd", required=True)

    p_ready = sub.add_parser("ready")
    p_ready.add_argument("--workers", type=int, default=4)

    sub.add_parser("outbound")

    p_in = sub.add_parser("inbound-once")
    p_in.add_argument("--count", type=int, default=50)
    p_in.add_argument("--workers", type=int, default=4)

    sub.add_parser("reply-errors")

    sub.add_parser("failover-prepare")

    p_fv = sub.add_parser("failover-verify")
    p_fv.add_argument("--old-leader-worker-id", required=True)
    p_fv.add_argument("--ttl", type=float, default=6.0)
    p_fv.add_argument("--llm-before", type=int, required=True)
    p_fv.add_argument("--elapsed-before-poll", type=float, default=0.0)
    p_fv.add_argument("--expected-reply-task-ids", default="")
    p_fv.add_argument("--wait-kill-stdin", action="store_true")

    sub.add_parser("mid-brain-prepare")

    p_mbv = sub.add_parser("mid-brain-verify")
    p_mbv.add_argument("--old-leader-worker-id", required=True)
    p_mbv.add_argument("--ttl", type=float, default=6.0)
    p_mbv.add_argument("--llm-before", type=int, required=True)
    p_mbv.add_argument("--wait-kill-stdin", action="store_true")

    sub.add_parser("stale-leader-prepare")

    p_slv = sub.add_parser("stale-leader-verify")
    p_slv.add_argument("--old-leader-worker-id", required=True)
    p_slv.add_argument("--llm-before", type=int, required=True)

    p_rl = sub.add_parser("rate-limit")
    p_rl.add_argument("--limit", type=int, default=12)

    sub.add_parser("cert-rotation")

    p_il = sub.add_parser("inspect-leaders")
    p_il.add_argument("--expect-workers", type=int, default=4)
    p_il.add_argument("--expect-leaders", type=int, default=None)
    p_il.add_argument("--expect-streams", type=int, default=None)
    p_il.add_argument("--probe-tasks", type=int, default=24)
    p_il.add_argument("--wait-seconds", type=float, default=12.0)

    sub.add_parser("reaper-and-deadline")

    sub.add_parser("redis-setnx-prepare")

    p_nxv = sub.add_parser("redis-setnx-verify")
    p_nxv.add_argument("--leader-worker-id", required=True)
    p_nxv.add_argument("--reacquired-owner", required=True)
    p_nxv.add_argument("--llm-before", type=int, required=True)

    args = parser.parse_args()
    handlers = {
        "ready": cmd_ready,
        "outbound": cmd_outbound,
        "inbound-once": cmd_inbound_once,
        "reply-errors": cmd_reply_errors,
        "reaper-and-deadline": cmd_reaper_and_deadline,
        "redis-setnx-prepare": cmd_redis_setnx_prepare,
        "redis-setnx-verify": cmd_redis_setnx_verify,
        "failover-prepare": cmd_failover_prepare,
        "failover-verify": cmd_failover_verify,
        "mid-brain-prepare": cmd_mid_brain_prepare,
        "mid-brain-verify": cmd_mid_brain_verify,
        "stale-leader-prepare": cmd_stale_leader_prepare,
        "stale-leader-verify": cmd_stale_leader_verify,
        "rate-limit": cmd_rate_limit,
        "cert-rotation": cmd_cert_rotation,
        "inspect-leaders": cmd_inspect_leaders,
    }
    asyncio.run(handlers[args.cmd](args))


if __name__ == "__main__":
    main()
