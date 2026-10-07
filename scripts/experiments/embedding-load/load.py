"""Embedding gateway 壓測：併發 1／4／16／32 各 20 秒，查詢與 16 段長文件混合，最後送一次 64 段×2000 字。

在 api 容器內執行（讀 EMBEDDING_SERVICE_TOKEN）；QSHARE 是查詢比例（預設 0.8，1 為純查詢）：
    docker cp scripts/experiments/embedding-load/load.py openvman-api-1:/tmp/emb_load.py
    docker exec -e QSHARE=1 openvman-api-1 python3 /tmp/emb_load.py http://embedding:8009/embed
VRAM 另在主機上以 nvidia-smi --query-compute-apps=pid,used_memory -lms 500 記錄。
"""
import asyncio, json, os, random, sys, time
import httpx
URL = sys.argv[1]
H = {"Authorization": f"Bearer {os.environ.get('EMBEDDING_SERVICE_TOKEN','')}"}
QUERIES = ["50EUBL 的固體通過粒徑是多少？", "3 吋口徑揚程 20 米以上有哪幾款", "Which pump for basement?", "¿Cuál bomba recomienda?", "護理師夜班交接要注意什麼"]
DOC = ("額定揚程 11 m @ 900 LPM，最大 18 m @ 1600 LPM。" * 30)[:1500]
def body():
    if random.random() < float(os.environ.get("QSHARE", "0.8")):
        return {"texts": [random.choice(QUERIES)], "input_type": "search_query"}, "query"
    n = 16
    return {"texts": [DOC + str(i) for i in range(n)], "input_type": "document", "titles": ["EVAK"] * n}, "doc16"
async def worker(client, stop, out):
    while time.monotonic() < stop:
        b, kind = body(); t = time.perf_counter()
        try:
            r = await client.post(URL, json=b, headers=H, timeout=120); ok = r.status_code == 200
        except Exception as e:
            ok = False
        out.append((kind, (time.perf_counter() - t) * 1000, ok))
async def level(c, secs):
    out = []
    async with httpx.AsyncClient() as client:
        stop = time.monotonic() + secs
        await asyncio.gather(*(worker(client, stop, out) for _ in range(c)))
    res = {"c": c, "n": len(out), "err": sum(not o[2] for o in out), "rps": round(len(out) / secs, 1)}
    for kind in ("query", "doc16"):
        ms = sorted(o[1] for o in out if o[0] == kind and o[2])
        if ms: res[kind] = {"p50": round(ms[len(ms)//2]), "p95": round(ms[int(len(ms)*.95)]), "n": len(ms)}
    print(json.dumps(res), flush=True)
async def big():
    async with httpx.AsyncClient() as client:
        t = time.perf_counter()
        r = await client.post(URL, json={"texts": [("長文件段落。" * 400)[:2000] + str(i) for i in range(64)], "input_type": "document"}, headers=H, timeout=300)
        print(json.dumps({"big64x2000": r.status_code, "ms": round((time.perf_counter()-t)*1000)}), flush=True)
async def main():
    for rnd in (1,):
        print(f"ROUND {rnd} {time.strftime('%H:%M:%S')}", flush=True)
        for c in (1, 4, 16, 32):
            await level(c, 20)
        await big()
        print(f"IDLE {time.strftime('%H:%M:%S')}", flush=True)
        await asyncio.sleep(15)
asyncio.run(main())
