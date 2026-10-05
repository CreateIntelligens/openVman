"""經過正式路徑（nginx → backend /api/v1/asr/stream → 帳號選的 R2T2）測多語串流。

測試帳號的辨識偏好要先設成要測的串流引擎。每句一條連線，像前台一樣送 100 ms 的 PCM。

    python3 scripts/experiments/r2t2/multilang/e2e_stream.py zh,en,es
"""
import asyncio, json, ssl, sys
from pathlib import Path
import websockets
ROOT = Path(__file__).resolve().parents[4]; sys.path.insert(0, str(ROOT)); sys.path.insert(0, str(Path(__file__).parent))
from scripts.voice_e2e.run import mint_token
from r2t2_lang import CASES, synth

PROJECT = "dev-c0c8fdff34"
TOKEN = mint_token("voice-e2e-test", 30)
CTX = ssl.create_default_context(); CTX.check_hostname = False; CTX.verify_mode = ssl.CERT_NONE

async def stream(pcm, routes):
    url = f"wss://localhost:8787/api/v1/asr/stream?project_id={PROJECT}&language_routes={routes}"
    finals = []
    async with websockets.connect(url, additional_headers={"Authorization": f"Bearer {TOKEN}"}, ssl=CTX, open_timeout=10) as ws:
        ready = json.loads(await asyncio.wait_for(ws.recv(), 10))
        if ready.get("type") != "ready":
            return f"<{ready}>"
        async def reader():
            async for raw in ws:
                m = json.loads(raw)
                if m.get("type") == "final": finals.append(m["text"])
                if m.get("type") == "error": finals.append(f"<error {m.get('code')}>"); return
        task = asyncio.create_task(reader())
        for i in range(0, len(pcm), 3200):
            await ws.send(pcm[i:i + 3200]); await asyncio.sleep(0.1)
        for _ in range(12):
            await ws.send(b"\0" * 3200); await asyncio.sleep(0.1)
        await ws.send(json.dumps({"type": "end"}))
        await asyncio.sleep(5)
        task.cancel()
    return " | ".join(finals) or "<no final>"

async def main(route_sets):
    for routes in route_sets:
        for lang in ("zh", "en", "es"):
            _, voice, texts = CASES[lang]
            if "," not in routes and routes != lang:
                continue
            for t in texts:
                pcm = await asyncio.to_thread(synth, voice, t)
                print(json.dumps({"routes": routes, "lang": lang, "ref": t, "out": await stream(pcm, routes)}, ensure_ascii=False), flush=True)

if __name__ == "__main__":
    asyncio.run(main(sys.argv[1:] or ["zh,en,es"]))
