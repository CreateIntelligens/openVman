"""OOM 恢復實驗：另一個程式佔滿 GPU 約 10 秒時，每 3 秒送一個請求，看 gateway 多久恢復。

先在主機開佔用 GPU 的容器（見 README），再執行：
    docker exec openvman-api-1 python3 /tmp/oom_probe.py http://embedding:8009/embed
"""
import json, os, sys, time, httpx
H = {"Authorization": f"Bearer {os.environ.get('EMBEDDING_SERVICE_TOKEN','')}"}
DOC = ("額定揚程 11 m @ 900 LPM。" * 200)[:2000]
def send(kind):
    b = {"texts": ["50EUBL 粒徑"], "input_type": "search_query"} if kind == "q" else {"texts": [DOC + str(i) for i in range(16)], "input_type": "document"}
    t = time.perf_counter()
    try:
        r = httpx.post(sys.argv[1], json=b, headers=H, timeout=60)
        att = r.json().get("detail", "")[:90] if r.status_code != 200 else ""
        return r.status_code, round((time.perf_counter() - t) * 1000), att
    except Exception as e:
        return "EXC", 0, repr(e)[:90]
start = time.time()
for kind, at in [("q", 3), ("d", 5), ("d", 8)] + [("q", 12 + 3 * i) for i in range(30)]:
    while time.time() - start < at: time.sleep(0.1)
    print(f"t={at:>3}s {kind}", *send(kind), flush=True)
