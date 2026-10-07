"""兩個 gateway 對同一批文字（同時送出、會被合批）算出的向量是否一致。

    docker exec openvman-api-1 python3 /tmp/same_vectors.py http://embedding:8009/embed http://<另一台>:8009/embed
"""
import asyncio, os, sys

import httpx
H = {"Authorization": f"Bearer {os.environ.get('EMBEDDING_SERVICE_TOKEN','')}"}
TEXTS = [("50EUBL 的固體通過粒徑是多少？", "search_query"), ("Which pump for basement?", "search_query"), ("額定揚程 11 m @ 900 LPM" * 40, "document"), ("hola", "query"), ("護理師夜班交接", "search_query")] * 4
async def one(client, url, t, kind):
    r = await client.post(url, json={"texts": [t], "input_type": kind}, headers=H, timeout=60)
    return r.json()["vectors"][0]
async def main():
    async with httpx.AsyncClient() as c:
        old = await asyncio.gather(*(one(c, sys.argv[1], t, k) for t, k in TEXTS))
        new = await asyncio.gather(*(one(c, sys.argv[2], t, k) for t, k in TEXTS))
    cos = [sum(a*b for a, b in zip(x, y)) for x, y in zip(old, new)]
    print("min cos old vs new (concurrent, merged)", round(min(cos), 6), "n", len(cos))
asyncio.run(main())
