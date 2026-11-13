"""Authenticated Backend -> split Brain -> fake LLM acceptance and open-loop load."""

from __future__ import annotations

import argparse
import asyncio
import json
import math
import os
import statistics
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path

import httpx
from extra_acceptance import (
    verify_backup,
    verify_enrich_history,
    verify_import_during_chat,
    verify_metrics,
    verify_project_skill,
    verify_settings,
)

PROJECT = "synthetic-worker-split"
BACKEND = "http://split-backend:8200"
ADMIN = "http://split-admin:8100"
CHAT = "http://split-chat:8100"
INTERNAL_HEADERS = {"X-Internal-Token": "synthetic-worker-internal-token"}
PASSWORD = "Synthetic-Worker-Only-2026"
QUESTION = "請簡短介紹服務中心的週末預約諮詢服務"


async def wait_ready(client):
    """Retry startup probes only; never retry a real chat or acceptance action."""
    async def probe(base):
        deadline = time.monotonic() + 180
        last_error = "not probed"
        while time.monotonic() < deadline:
            try:
                response = await client.get(base + "/brain/health/ready", timeout=5)
                if response.status_code == 200:
                    return
                if response.status_code not in (502, 503, 504):
                    response.raise_for_status()
                last_error = f"HTTP {response.status_code}"
            except (httpx.ConnectError, httpx.TimeoutException, httpx.RemoteProtocolError) as error:
                last_error = type(error).__name__
            await asyncio.sleep(1)
        raise RuntimeError(f"isolated Brain readiness timed out: {base}: {last_error}")

    await asyncio.gather(probe(ADMIN), probe(CHAT))


async def login(client):
    deadline = time.monotonic() + 180
    last_error = None
    while time.monotonic() < deadline:
        try:
            response = await client.post(BACKEND + "/api/v1/auth/login", json={"username": "worker-load", "password": PASSWORD})
            response.raise_for_status()
            return {"Authorization": "Bearer " + response.json()["token"]}
        except (httpx.HTTPError, ValueError, KeyError) as error:
            last_error = type(error).__name__
            await asyncio.sleep(1)
    raise RuntimeError(f"isolated Backend did not become available: {last_error}")


async def chat_request(client, headers, *, message=QUESTION, session_id=None, staged=False):
    session_id = session_id or "workerload-" + uuid.uuid4().hex
    payload = {"project_id": PROJECT, "persona_id": "default", "session_id": session_id, "message": message}
    if staged:
        payload.update({"turn_id": uuid.uuid4().hex, "turn_revision": 1})
    started = time.perf_counter()
    first_sentence = None
    done = None
    try:
        # New sockets also exercise multiple uvicorn workers during small smoke runs.
        async with client.stream("POST", BACKEND + "/api/v1/chat/stream", headers={**headers, "Connection": "close"}, json=payload) as response:
            response.raise_for_status()
            event = ""
            data = []
            async for line in response.aiter_lines():
                if line.startswith("event:"):
                    event = line[6:].strip()
                elif line.startswith("data:"):
                    data.append(line[5:].lstrip())
                elif not line and data:
                    body = json.loads("\n".join(data))
                    if event == "error":
                        raise RuntimeError(f"SSE error: {body}")
                    if event == "sentence" and body.get("text") and first_sentence is None:
                        first_sentence = time.perf_counter() - started
                    if event == "done":
                        done = body
                    data = []
            if first_sentence is None or done is None or not done.get("reply"):
                raise RuntimeError("stream ended without first sentence and successful done")
        return {"ok": True, "session_id": session_id, "first_sentence": first_sentence, "elapsed": time.perf_counter() - started, "reply": done["reply"], "turn_id": payload.get("turn_id")}
    except Exception as error:  # noqa: BLE001 - Keep all per-request failures in the report.
        return {"ok": False, "session_id": session_id, "elapsed": time.perf_counter() - started, "error": f"{type(error).__name__}: {error}"}


async def acceptance(client, headers):
    checks = []
    response = await client.post(BACKEND + "/api/v1/chat/stream", json={"project_id": PROJECT, "message": QUESTION}, headers={"Authorization": "Bearer invalid-synthetic-token"})
    assert response.status_code == 401, ("auth boundary", response.status_code)
    checks.append("unauthenticated chat rejected")
    for base in (ADMIN, CHAT):
        response = await client.get(base + "/brain/health/ready")
        response.raise_for_status()
    admin_projects = await client.get(ADMIN + "/brain/projects", headers=INTERNAL_HEADERS)
    admin_projects.raise_for_status()
    chat_projects = await client.get(CHAT + "/brain/projects", headers=INTERNAL_HEADERS)
    assert chat_projects.status_code == 404, ("chat management route", chat_projects.status_code)
    checks.append("admin routes present only on admin")
    registered = await client.get(BACKEND + "/api/v1/projects", headers=headers)
    registered.raise_for_status()
    assert any(project.get("project_id") == PROJECT for project in registered.json().get("projects", [])), registered.text
    checks.append("synthetic private project registered to the test ROOT and visible through Backend")

    response = await client.post(BACKEND + "/api/v1/search", headers=headers, json={"project_id": PROJECT, "query": QUESTION, "top_k": 3, "table": "knowledge", "query_type": "hybrid"})
    response.raise_for_status()
    assert response.json().get("results"), "synthetic knowledge was not retrieved"
    checks.append("real embedding and LanceDB retrieval returned seeded knowledge")

    turn = await chat_request(client, headers, staged=True)
    assert turn["ok"], turn
    response = await client.post(BACKEND + "/api/v1/chat/accept", headers=headers, json={"project_id": PROJECT, "persona_id": "default", "session_id": turn["session_id"], "turn_id": turn["turn_id"], "turn_revision": 1})
    response.raise_for_status()
    history = await client.get(BACKEND + "/api/v1/chat/history", headers=headers, params={"project_id": PROJECT, "session_id": turn["session_id"]})
    history.raise_for_status()
    assert len(history.json().get("history", [])) >= 2, history.text
    checks.append("SSE generation, cross-connection turn accept and persisted history")

    query = {"scope": "shared", "project_id": PROJECT}
    toggled = False
    try:
        response = await client.patch(BACKEND + "/api/v1/skills/worker_probe/toggle", headers=headers, params=query)
        response.raise_for_status()
        assert response.json()["enabled"] is False
        toggled = True
        disabled = await asyncio.gather(*(chat_request(client, headers, message="請回答隔離技能狀態") for _ in range(16)))
        assert all(result["ok"] and "已停用" in result["reply"] for result in disabled), disabled
        checks.append("admin skill disabled: 16 independent Backend chat connections saw it immediately")
    finally:
        if toggled:
            response = await client.patch(BACKEND + "/api/v1/skills/worker_probe/toggle", headers=headers, params=query)
            response.raise_for_status()
            assert response.json()["enabled"] is True
    enabled = await chat_request(client, headers, message="請回答隔離技能狀態")
    assert enabled["ok"] and "已啟用" in enabled["reply"], enabled
    checks.append("admin skill re-enabled and visible in next chat")
    checks.append(await verify_settings(client, headers, backend=BACKEND, admin=ADMIN, chat=CHAT, project=PROJECT, internal_headers=INTERNAL_HEADERS))
    checks.append(await verify_import_during_chat(client, headers, backend=BACKEND, project=PROJECT, request_chat=chat_request))
    checks.append(await verify_enrich_history(client, headers, backend=BACKEND, project=PROJECT, internal_headers=INTERNAL_HEADERS))
    checks.append(await verify_backup(client, headers, backend=BACKEND, project=PROJECT, expected_session=turn["session_id"]))
    checks.append(await verify_metrics(client, headers, chat=CHAT, internal_headers=INTERNAL_HEADERS, request_chat=chat_request))
    checks.append(await verify_project_skill(client, headers, backend=BACKEND, project=PROJECT))
    return checks


def summarize(name, results, scheduling_seconds):
    first = sorted(result["first_sentence"] for result in results if result["ok"])
    summary = {"scenario": name, "requests": len(results), "success": len(first), "failures": len(results) - len(first), "scheduling_seconds": scheduling_seconds, "first_sentence_median": statistics.median(first) if first else None, "first_sentence_p95": first[max(0, math.ceil(len(first) * .95) - 1)] if first else None, "request_elapsed_max": max((result["elapsed"] for result in results), default=0)}
    print(json.dumps(summary, ensure_ascii=False), flush=True)
    return {**summary, "results": results}


async def sustained(client, headers, rate, seconds):
    started = time.perf_counter()
    tasks = []
    count = max(1, round(rate * seconds))
    for index in range(count):
        await asyncio.sleep(max(0, started + index / rate - time.perf_counter()))
        tasks.append(asyncio.create_task(chat_request(client, headers)))
    results = await asyncio.gather(*tasks)
    return summarize(f"rate-{rate}", results, seconds)


async def run(args):
    report = {"workers": int(os.environ.get("WORKER_COUNT", "4")), "thread_pool_size": int(os.environ.get("WORKER_THREAD_POOL_SIZE", "0")), "timestamp": datetime.now(timezone.utc).isoformat(), "project": PROJECT, "synthetic_llm_first_content_seconds": .8, "load_only": args.load_only, "settle_seconds": args.settle_seconds, "scenarios": []}
    output = Path(args.output or f"/results/workers-{report['workers']}-{datetime.now(timezone.utc):%Y%m%dT%H%M%SZ}.json")
    output.parent.mkdir(parents=True, exist_ok=True)
    failure = None
    try:
        limits = httpx.Limits(max_connections=256, max_keepalive_connections=0)
        async with httpx.AsyncClient(timeout=90, limits=limits, trust_env=False) as client:
            await wait_ready(client)
            headers = await login(client)
            if not args.load_only:
                report["acceptance"] = await acceptance(client, headers)
                print(json.dumps({"acceptance": report["acceptance"]}, ensure_ascii=False), flush=True)
            else:
                report["acceptance"] = "skipped: --load-only preserves the current dataset"
            if not args.smoke_only:
                if args.settle_seconds:
                    print(json.dumps({"stage": "before-load", "settle_seconds": args.settle_seconds}), flush=True)
                    await asyncio.sleep(args.settle_seconds)
                warm = await asyncio.gather(*(chat_request(client, headers) for _ in range(report["workers"] * 2)))
                assert all(result["ok"] for result in warm), warm
                for rate in args.rates:
                    report["scenarios"].append(await sustained(client, headers, rate, args.seconds))
                burst = await asyncio.gather(*(chat_request(client, headers) for _ in range(args.burst)))
                report["scenarios"].append(summarize(f"burst-{args.burst}", burst, 0))
                assert all(scenario["failures"] == 0 for scenario in report["scenarios"]), "one or more requests failed"
                if args.enforce_targets:
                    for scenario in report["scenarios"]:
                        target = 5 if scenario["scenario"] == "burst-100" else 2 if scenario["scenario"] in ("rate-5", "rate-10") else None
                        if target is not None:
                            assert scenario["first_sentence_median"] <= target, f"{scenario['scenario']} exceeds {target}s median target"
            stats = await client.get("http://fake-llm:8080/stats")
            stats.raise_for_status()
            report["fake_llm"] = stats.json()
            assert report["fake_llm"]["streams"] > 0
    except Exception as error:  # noqa: BLE001 - Persist the acceptance failure before exiting.
        failure = error
        report["error"] = f"{type(error).__name__}: {error}"
    finally:
        output.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
        print(json.dumps({"result_file": str(output), "ok": failure is None}, ensure_ascii=False), flush=True)
    if failure is not None:
        raise failure


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--seconds", type=float, default=30)
    parser.add_argument("--rates", type=int, nargs="+", default=[3, 5, 10])
    parser.add_argument("--burst", type=int, default=100)
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--smoke-only", action="store_true")
    mode.add_argument("--load-only", action="store_true", help="Skip acceptance fixtures; keep readiness/login and run only load")
    parser.add_argument("--settle-seconds", type=float, default=0, help="Explicit delay before warmup/load; does not claim admin background jobs are idle")
    parser.add_argument("--enforce-targets", action="store_true")
    parser.add_argument("--output")
    arguments = parser.parse_args()
    if arguments.seconds <= 0 or any(rate <= 0 for rate in arguments.rates) or arguments.burst <= 0 or arguments.settle_seconds < 0:
        parser.error("seconds, rates and burst must be positive; settle-seconds must be nonnegative")
    asyncio.run(run(arguments))
