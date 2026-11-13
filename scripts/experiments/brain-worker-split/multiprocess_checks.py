"""Check Backend state that must be shared when it runs several processes.

在 client 容器裡執行（Backend 要用 BACKEND_WORKERS 大於 1 啟動）。每個請求都開新連線，
才會被分到不同 process：
- 錯的解鎖密碼送 6 次，第 6 次要被鎖（上限 5 次），不能因為落在不同 process 各算各的。
- 同時送 /metrics 要分到多個 process；連抓 Prometheus，總請求數只能往上加，不能隨抓到的 process 跳動。
注意：測試帳號的解鎖密碼會被鎖 5 分鐘。
"""

from __future__ import annotations

import asyncio
import json
import re

import httpx

BACKEND = "http://split-backend:8200"
PASSWORD = "Synthetic-Worker-Only-2026"
CLOSE = {"Connection": "close"}


def _http_total(text: str) -> float:
    return sum(
        float(match.group(1))
        for match in re.finditer(r'^http_requests_total\{[^}]*\} ([0-9.e+]+)$', text, re.M)
    )


async def main() -> None:
    async with httpx.AsyncClient(timeout=30, trust_env=False) as client:
        login = await client.post(BACKEND + "/api/v1/auth/login", json={"username": "worker-load", "password": PASSWORD}, headers=CLOSE)
        login.raise_for_status()
        auth = {"Authorization": "Bearer " + login.json()["token"], **CLOSE}

        statuses = []
        for _ in range(6):
            response = await client.post(BACKEND + "/api/v1/auth/verify-password", json={"password": "wrong"}, headers=auth)
            statuses.append(response.status_code)
        assert statuses == [400] * 5 + [429], statuses

        # 一個接一個送時，閒著的同一個 process 會一直搶到連線；同時送才分得開。
        pids, totals = set(), []
        for _ in range(6):
            answers = await asyncio.gather(*(client.get(BACKEND + "/metrics", headers=CLOSE) for _ in range(40)))
            pids.update(answer.json().get("scope", {}).get("pid") for answer in answers)
            totals.append(_http_total((await client.get(BACKEND + "/metrics/prometheus", headers=CLOSE)).text))
        assert len(pids) > 1, f"all /metrics answers came from one process: {pids}"
        assert totals == sorted(totals) and totals[-1] > 0, totals
        # 監控端點本身不計數；送 40 個會計數的請求，不管抓取落在哪個 process 都要剛好多 40。
        before = _http_total((await client.get(BACKEND + "/metrics/prometheus", headers=CLOSE)).text)
        await asyncio.gather(*(client.get(BACKEND + "/api/v1/projects", headers=auth) for _ in range(40)))
        after = [_http_total((await client.get(BACKEND + "/metrics/prometheus", headers=CLOSE)).text) for _ in range(4)]
        assert all(value == before + 40 for value in after), (before, after)
        totals += [before] + after
        print(json.dumps({
            "verify_password_statuses": statuses,
            "metrics_answered_by_processes": len(pids),
            "prometheus_http_requests_total": [totals[0], totals[-1]],
        }))


if __name__ == "__main__":
    asyncio.run(main())
