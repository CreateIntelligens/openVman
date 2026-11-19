"""Compare TTS first-audio time: straight to the engine vs. through Backend /api/v1/tts/stream.

The difference is what our relay adds. Token comes from OPENVMAN_TOKEN (never written to disk).
"""

import argparse
import asyncio
import json
import os
import random
import statistics
import time

import httpx

SENTENCES = [
    "您好，歡迎光臨，請問今天想了解哪一款產品呢？",
    "這款水抽浦適合一般住家使用，安裝也很簡單。",
    "如果您需要更大的流量，我建議看看另一個系列。",
    "保固期間內有任何問題，都可以直接聯絡我們的服務中心。",
    "請稍等一下，我幫您查一下目前的庫存狀況。",
    "這個型號的揚程比較高，適合需要往高樓送水的場合。",
]


def text_for(i: int) -> str:
    # 每句不同，避開 TTS 快取。
    return f"{random.choice(SENTENCES)}這是第{i}句。"


async def one(client, mode, args, i):
    text = text_for(i)
    if mode == "direct":
        url = args.direct_url
        payload = {"text": text, "voice": args.voice, "stream": True}
        headers = {}
    else:
        url = args.backend_url.rstrip("/") + "/api/v1/tts/stream"
        payload = {"text": text, "provider": args.provider, "voice": args.voice}
        headers = {"Authorization": f"Bearer {os.environ['OPENVMAN_TOKEN']}"}
    started = time.perf_counter()
    try:
        async with client.stream("POST", url, json=payload, headers=headers) as resp:
            if resp.status_code >= 400:
                await resp.aread()
                return {"ok": False, "status": resp.status_code}
            first = None
            async for chunk in resp.aiter_bytes():
                if chunk and first is None:
                    first = time.perf_counter() - started
            total = time.perf_counter() - started
            return {
                "ok": first is not None, "first": first, "total": total,
                "provider": resp.headers.get("x-tts-provider", ""),
                "fallback": resp.headers.get("x-tts-fallback-reason", ""),
            }
    except Exception as exc:  # noqa: BLE001
        return {"ok": False, "error": type(exc).__name__}


def pct(values, p):
    values = sorted(values)
    return values[min(len(values) - 1, int(len(values) * p))] if values else float("nan")


async def stage(client, mode, rate, seconds, args):
    tasks, i = [], 0
    end = time.perf_counter() + seconds
    while time.perf_counter() < end:
        tasks.append(asyncio.create_task(one(client, mode, args, i)))
        i += 1
        await asyncio.sleep(1 / rate)
    results = await asyncio.gather(*tasks)
    firsts = [r["first"] for r in results if r.get("ok")]
    providers = {}
    for r in results:
        key = r.get("provider") or r.get("status") or r.get("error") or "?"
        providers[key] = providers.get(key, 0) + 1
    return {
        "mode": mode, "rate": rate, "sent": len(results), "ok": len(firsts),
        "first_med": round(statistics.median(firsts), 2) if firsts else None,
        "first_p95": round(pct(firsts, 0.95), 2) if firsts else None,
        "outcomes": providers,
    }


async def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--direct-url",
        required=True,
        help="TTS endpoint to call directly, e.g. http://<host>:8206/api/tts",
    )
    parser.add_argument("--backend-url", default="https://localhost:28787")
    parser.add_argument("--provider", default="gemini-tts")
    parser.add_argument("--voice", default="")
    parser.add_argument("--rates", type=float, nargs="+", default=[2, 5, 10])
    parser.add_argument("--seconds", type=float, default=20)
    parser.add_argument("--modes", nargs="+", default=["direct", "backend"])
    parser.add_argument("--output")
    args = parser.parse_args()
    limits = httpx.Limits(max_connections=500, max_keepalive_connections=100)
    out = []
    async with httpx.AsyncClient(verify=False, timeout=60, limits=limits) as client:
        for rate in args.rates:
            for mode in args.modes:
                row = await stage(client, mode, rate, args.seconds, args)
                print(json.dumps(row, ensure_ascii=False), flush=True)
                out.append(row)
                await asyncio.sleep(5)
    if args.output:
        with open(args.output, "w", encoding="utf-8") as fh:
            json.dump(out, fh, ensure_ascii=False, indent=2)


if __name__ == "__main__":
    asyncio.run(main())
