"""Host-side orchestrator for the 7 A2A multi-process acceptance checks.

Runs in the isolated `scripts/experiments/brain-worker-split/` Compose stack
(`COMPOSE_PROJECT_NAME=openvman-a2a-mp-acceptance`), never touching prod/dev
containers or volumes, and tears down the stack cleanly when finished.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
import subprocess
import sys
import time

WORKDIR = Path(__file__).resolve().parent
PROJECT_NAME = "openvman-a2a-mp-acceptance"


def _run(cmd: list[str], env: dict[str, str], *, check: bool = True) -> subprocess.CompletedProcess[str]:
    proc = subprocess.run(
        cmd,
        cwd=WORKDIR,
        env=env,
        text=True,
        capture_output=True,
    )
    if check and proc.returncode != 0:
        raise RuntimeError(
            f"Command failed ({proc.returncode}): {' '.join(cmd)}\n"
            f"STDOUT:\n{proc.stdout}\nSTDERR:\n{proc.stderr}"
        )
    return proc


def _compose(env: dict[str, str], *args: str, check: bool = True) -> subprocess.CompletedProcess[str]:
    return _run(["docker", "compose", "-f", "compose.yaml", *args], env, check=check)


def _client(env: dict[str, str], *args: str) -> dict:
    proc = _compose(
        env,
        "run",
        "--rm",
        "--no-deps",
        "-T",
        "--entrypoint",
        "python",
        "client",
        "/experiments/a2a_multiprocess_checks.py",
        *args,
    )
    lines = [line.strip() for line in proc.stdout.splitlines() if line.strip()]
    return json.loads(lines[-1])


def _get_embedding_token() -> str:
    tok = os.environ.get("EMBEDDING_TEST_TOKEN", "").strip()
    if tok:
        return tok
    proc = subprocess.run(
        [
            "docker",
            "exec",
            "openvman-embedding-1",
            "python",
            "-c",
            "import os; print(os.environ.get('EMBEDDING_BEARER_TOKEN', ''))",
        ],
        text=True,
        capture_output=True,
        check=True,
    )
    return proc.stdout.strip()


def _base_env(
    token: str,
    *,
    workers: int = 4,
    rate_limit: int = 300,
    lease_ttl: int = 8,
    orphan_sweep_seconds: int = 3,
) -> dict[str, str]:
    env = os.environ.copy()
    env.update(
        {
            "COMPOSE_PROJECT_NAME": PROJECT_NAME,
            "EMBEDDING_TEST_TOKEN": token,
            "WORKER_COUNT": "2",
            "BACKEND_WORKERS": str(workers),
            "FAKE_TTS_URL": "",
            "TTS_EDGE_ENABLED": "false",
            "A2A_ENABLED": "true",
            "A2A_MAX_TASKS_PER_MINUTE": str(rate_limit),
            "A2A_LEADER_LEASE_TTL_SECONDS": str(lease_ttl),
            "A2A_ORPHAN_SWEEP_INTERVAL_SECONDS": str(orphan_sweep_seconds),
            "UVICORN_TIMEOUT_WORKER_HEALTHCHECK": "30",
        }
    )
    return env


def _wait_redis_lease_window(env: dict[str, str], ttl: int) -> None:
    """Wait until current lease has <= (ttl - 1.5)s left so kill -9 completes within TTL."""
    deadline = time.monotonic() + ttl + 2.0
    last_pttl = None
    while time.monotonic() < deadline:
        proc = _compose(
            env,
            "exec",
            "-T",
            "redis",
            "redis-cli",
            "--raw",
            "EVAL",
            "local ks = redis.call('keys', 'a2a:leader:lease:*'); if #ks == 0 then return -1 end; return redis.call('pttl', ks[1])",
            "0",
            check=False,
        )
        if proc.returncode == 0 and proc.stdout.strip().lstrip("-").isdigit():
            pttl_ms = int(proc.stdout.strip())
            last_pttl = pttl_ms
            if 500 <= pttl_ms <= int((ttl - 1.5) * 1000):
                return
        time.sleep(0.2)
    raise RuntimeError(f"Timed out waiting for Redis lease PTTL window (ttl={ttl}s, last_pttl={last_pttl})")


def _run_kill_handshake(env: dict[str, str], leader_pid: int, *verify_args: str) -> dict:
    """Start verifier container, wait for READY_FOR_KILL, SIGKILL leader within PTTL window, return JSON output."""
    verifier = subprocess.Popen(
        [
            "docker",
            "compose",
            "-f",
            "compose.yaml",
            "run",
            "--rm",
            "--no-deps",
            "-T",
            "--entrypoint",
            "python",
            "client",
            "/experiments/a2a_multiprocess_checks.py",
            *verify_args,
        ],
        cwd=WORKDIR,
        env=env,
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    assert verifier.stdout is not None and verifier.stdin is not None
    ready_line = verifier.stdout.readline().strip()
    if ready_line != "READY_FOR_KILL":
        verifier.kill()
        rem_out, rem_err = verifier.communicate()
        raise RuntimeError(
            f"{verify_args[0]} failed before handshake: line={ready_line!r}\n"
            f"STDOUT:\n{rem_out}\nSTDERR:\n{rem_err}"
        )
    kill_proc = _compose(
        env,
        "exec",
        "-T",
        "split-backend",
        "python",
        "-c",
        (
            "import os, signal, time, redis\n"
            "r = redis.from_url(os.environ['REDIS_URL'])\n"
            "ks = r.keys('a2a:leader:lease:*')\n"
            "if not ks:\n"
            "    raise RuntimeError('Missing Redis leader lease key before kill')\n"
            "deadline = time.monotonic() + 10.0\n"
            "matched = False\n"
            "while time.monotonic() < deadline:\n"
            "    pttl = r.pttl(ks[0])\n"
            "    if 5800 <= pttl <= 6400:\n"
            "        matched = True\n"
            "        break\n"
            "    time.sleep(0.05)\n"
            "if not matched:\n"
            "    raise RuntimeError(f'Timed out waiting for Redis lease PTTL window (last_pttl={r.pttl(ks[0])})')\n"
            "t = time.time()\n"
            f"os.kill({leader_pid}, signal.SIGKILL)\n"
            "print(f'{t:.6f}')\n"
        ),
    )
    kill_epoch = float(kill_proc.stdout.strip().splitlines()[-1])
    verifier.stdin.write(f"{kill_epoch:.6f}\n")
    verifier.stdin.flush()
    verifier.stdin.close()
    rem_out = verifier.stdout.read()
    rem_err = verifier.stderr.read() if verifier.stderr else ""
    verifier.wait(timeout=120)
    if verifier.returncode != 0:
        raise RuntimeError(
            f"{verify_args[0]} failed ({verifier.returncode}):\nSTDOUT:\n{rem_out}\nSTDERR:\n{rem_err}"
        )
    verify_lines = [line.strip() for line in rem_out.splitlines() if line.strip()]
    return json.loads(verify_lines[-1])


def main() -> None:
    token = _get_embedding_token()
    results: dict[str, object] = {}

    env = _base_env(token, workers=4, rate_limit=2000, lease_ttl=8)
    try:
        _compose(env, "down", "-v", check=False)
        _compose(env, "up", "-d", "fake-hub", "split-backend")
        _client(env, "ready", "--workers", "4")

        # 1. 送出端點
        results["1_outbound"] = _client(env, "outbound")
        print("PASS 1_outbound:", json.dumps(results["1_outbound"], ensure_ascii=False), flush=True)

        # 2. 收進來只處理一次 (50 tasks)
        results["2_inbound_once"] = _client(env, "inbound-once", "--count", "50", "--workers", "4")
        print("PASS 2_inbound_once:", json.dumps(results["2_inbound_once"], ensure_ascii=False), flush=True)

        # 2b. 假 Hub 對回覆注入 429 (指數退避) / 503 / 401，驗證回覆皆送達且不重呼 Brain
        results["2b_reply_errors"] = _client(env, "reply-errors")
        print("PASS 2b_reply_errors:", json.dumps(results["2b_reply_errors"], ensure_ascii=False), flush=True)

        # 2c. 週期性孤兒回收 + 10 分鐘總期限過期轉 FAILED
        results["2c_reaper_and_deadline"] = _client(env, "reaper-and-deadline")
        print("PASS 2c_reaper_and_deadline:", json.dumps(results["2c_reaper_and_deadline"], ensure_ascii=False), flush=True)

        # 3. leader 失效（Hub 已收下回覆並在 mark_outbound_sent 前 kill leader，驗證重送使用相同 taskId 與 idempotencyKey）
        prep = _client(env, "failover-prepare")
        results["3_leader_failover"] = _run_kill_handshake(
            env,
            int(prep["leader_pid"]),
            "failover-verify",
            "--old-leader-worker-id",
            prep["leader_worker_id"],
            "--ttl",
            "8",
            "--llm-before",
            str(prep["llm_before"]),
            "--expected-reply-task-ids",
            ",".join(prep.get("processing_reply_task_ids", [])),
            "--wait-kill-stdin",
        )
        print("PASS 3_leader_failover:", json.dumps(results["3_leader_failover"], ensure_ascii=False), flush=True)

        # 3b. Brain 呼叫到一半 leader 被殺（reply_message IS NULL），驗證 Brain 呼叫數與只送出一則回覆
        prep_mb = _client(env, "mid-brain-prepare")
        results["3b_mid_brain_kill_recovery"] = _run_kill_handshake(
            env,
            int(prep_mb["leader_pid"]),
            "mid-brain-verify",
            "--old-leader-worker-id",
            prep_mb["leader_worker_id"],
            "--ttl",
            "8",
            "--llm-before",
            str(prep_mb["llm_before"]),
            "--wait-kill-stdin",
        )
        print(
            "PASS 3b_mid_brain_kill_recovery:",
            json.dumps(results["3b_mid_brain_kill_recovery"], ensure_ascii=False),
            flush=True,
        )

        # 3c. 還活著的過時 leader：SIGSTOP 超過 TTL 待新 leader 上位後 SIGCONT 恢復
        prep_stale = _client(env, "stale-leader-prepare")
        stale_pid = int(prep_stale["leader_pid"])
        stale_wid = str(prep_stale["leader_worker_id"])
        stop_proc = _compose(
            env,
            "exec",
            "-T",
            "split-backend",
            "python",
            "-c",
            (
                "import os, signal, time, redis\n"
                "r = redis.from_url(os.environ['REDIS_URL'])\n"
                f"os.kill({stale_pid}, signal.SIGSTOP)\n"
                "deadline = time.monotonic() + 25.0\n"
                "new_owner = ''\n"
                "try:\n"
                "    while time.monotonic() < deadline:\n"
                "        ks = r.keys('a2a:leader:lease:*')\n"
                "        if ks:\n"
                "            val = r.get(ks[0])\n"
                "            if val:\n"
                "                cand = val.decode('utf-8', errors='replace')\n"
                f"                if cand and cand != {stale_wid!r}:\n"
                "                    new_owner = cand\n"
                "                    break\n"
                "        time.sleep(0.15)\n"
                "finally:\n"
                f"    os.kill({stale_pid}, signal.SIGCONT)\n"
                "if not new_owner:\n"
                "    raise RuntimeError('No new leader acquired lease while old leader SIGSTOPped')\n"
                "print(new_owner)\n"
            ),
        )
        results["3c_stale_live_leader"] = _client(
            env,
            "stale-leader-verify",
            "--old-leader-worker-id",
            stale_wid,
            "--llm-before",
            str(prep_stale["llm_before"]),
        )
        results["3c_stale_live_leader"]["observed_redis_owner_before_sigcont"] = (
            stop_proc.stdout.strip().splitlines()[-1]
        )
        print(
            "PASS 3c_stale_live_leader:",
            json.dumps(results["3c_stale_live_leader"], ensure_ascii=False),
            flush=True,
        )

        # 5. 憑證換發
        results["5_cert_rotation"] = _client(env, "cert-rotation")
        print("PASS 5_cert_rotation:", json.dumps(results["5_cert_rotation"], ensure_ascii=False), flush=True)

        # 6. Redis 中斷與恢復
        _compose(env, "stop", "redis")
        down_state = _client(
            env,
            "inspect-leaders",
            "--expect-workers",
            "4",
            "--expect-leaders",
            "0",
            "--expect-streams",
            "0",
            "--probe-tasks",
            "40",
            "--wait-seconds",
            "15",
        )
        _compose(env, "start", "redis")
        recovered_state = _client(
            env,
            "inspect-leaders",
            "--expect-workers",
            "4",
            "--expect-leaders",
            "1",
            "--expect-streams",
            "1",
            "--probe-tasks",
            "40",
            "--wait-seconds",
            "15",
        )
        results["6_redis_outage_and_recovery"] = {
            "during_outage": down_state,
            "after_recovery": recovered_state,
        }
        print(
            "PASS 6_redis_outage_and_recovery:",
            json.dumps(results["6_redis_outage_and_recovery"], ensure_ascii=False),
            flush=True,
        )

        # 6b. Redis SET NX 同 leader 重新搶回租約時，進行中的 Brain 呼叫不被取消
        prep_nx = _client(env, "redis-setnx-prepare")
        nx_leader_wid = str(prep_nx["leader_worker_id"])
        nx_other_pids = [int(p) for p in prep_nx["other_pids"]]
        nx_proc = _compose(
            env,
            "exec",
            "-T",
            "split-backend",
            "python",
            "-c",
            (
                "import os, signal, time, urllib.request, redis\n"
                "r = redis.from_url(os.environ['REDIS_URL'])\n"
                f"other_pids = {nx_other_pids!r}\n"
                "for p in other_pids:\n"
                "    os.kill(p, signal.SIGSTOP)\n"
                "reacquired = ''\n"
                "try:\n"
                "    ks = r.keys('a2a:leader:lease:*')\n"
                "    if ks:\n"
                "        r.delete(*ks)\n"
                "    deadline = time.monotonic() + 12.0\n"
                "    while time.monotonic() < deadline:\n"
                "        ks = r.keys('a2a:leader:lease:*')\n"
                "        if ks:\n"
                "            val = r.get(ks[0])\n"
                "            if val:\n"
                "                reacquired = val.decode('utf-8', errors='replace')\n"
                "                break\n"
                "        time.sleep(0.05)\n"
                "finally:\n"
                "    for p in other_pids:\n"
                "        os.kill(p, signal.SIGCONT)\n"
                "    urllib.request.urlopen(\n"
                "        urllib.request.Request('http://fake-llm:8080/control/release_chat', method='POST'),\n"
                "        timeout=5,\n"
                "    ).read()\n"
                f"if reacquired != {nx_leader_wid!r}:\n"
                "    raise RuntimeError(f'Expected same leader reacquire, got {reacquired!r}')\n"
                "print(reacquired)\n"
            ),
        )
        reacq_owner = nx_proc.stdout.strip().splitlines()[-1]
        results["6b_redis_setnx_reacquire"] = _client(
            env,
            "redis-setnx-verify",
            "--leader-worker-id",
            nx_leader_wid,
            "--reacquired-owner",
            reacq_owner,
            "--llm-before",
            str(prep_nx["llm_before"]),
        )
        print(
            "PASS 6b_redis_setnx_reacquire:",
            json.dumps(results["6b_redis_setnx_reacquire"], ensure_ascii=False),
            flush=True,
        )

        # 4. 送出限流 (N=12 across 4 processes)
        _compose(
            env,
            "exec",
            "-T",
            "redis",
            "redis-cli",
            "EVAL",
            "for _,k in ipairs(redis.call('keys', 'vman:a2a-rate:*')) do redis.call('del', k) end; return 1",
            "0",
        )
        env_rl = _base_env(token, workers=4, rate_limit=12, lease_ttl=8)
        _compose(env_rl, "up", "-d", "split-backend")
        results["4_rate_limit"] = _client(env_rl, "rate-limit", "--limit", "12")
        print("PASS 4_rate_limit:", json.dumps(results["4_rate_limit"], ensure_ascii=False), flush=True)

        # 7. 單一 process smoke (BACKEND_WORKERS=1)
        env_single = _base_env(token, workers=1, rate_limit=2000, lease_ttl=8)
        _compose(env_single, "up", "-d", "split-backend")
        results["7_single_process_smoke"] = _client(env_single, "inbound-once", "--count", "5", "--workers", "1")
        print(
            "PASS 7_single_process_smoke:",
            json.dumps(results["7_single_process_smoke"], ensure_ascii=False),
            flush=True,
        )
    finally:
        _compose(env, "down", "-v", check=False)

    print("ALL_ACCEPTANCE_SUMMARY:", json.dumps(results, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
