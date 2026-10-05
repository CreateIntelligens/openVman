"""r2t2asr 請求：.37 zhen 自動判斷 (2) 台語 75 句判成什麼語言 (3) 同一條連線同語言連講 3 句，第二句起串流字幕品質。"""
import asyncio, json, statistics, sys, uuid
from collections import Counter
from pathlib import Path
import websockets
ROOT = Path("/home/human/openVman"); sys.path.insert(0, str(ROOT)); sys.path.insert(0, str(ROOT / "scripts/experiments/r2t2/multilang"))
sys.argv = ["x", "37"]
from r2t2_lang import env, CASES, synth
from scripts.experiments.r2t2.run import clips
from scripts.voice_e2e.run import to_pcm, cer
URL, KEY = env["ASR_R2T2_DEV_STREAM_URL"], env["ASR_R2T2_DEV_SECRET_KEY"]
assert "10.9.0.37" in URL
OUT = Path(__file__).with_name("auto_37_results.json")

async def session(pcm, language="zhen"):
    header = {"channels": 1, "sample_rate": 16000, "requestId": str(uuid.uuid4()), "language": language,
              "output_script": "traditional", "use_vad": True, "secret_key": KEY, "system_prompt": ""}
    segs, current = [], ""
    async with websockets.connect(URL, open_timeout=10) as ws:
        await ws.send(json.dumps(header)); await asyncio.wait_for(ws.recv(), 10)
        async def reader():
            nonlocal current
            async for raw in ws:
                msg = json.loads(raw).get("msg")
                if not isinstance(msg, dict): continue
                current += msg.get("text", "")
                if msg.get("reset"):
                    segs.append({"stream": current.strip(), "final": (msg.get("final_text") or current).strip(), "language": msg.get("language")})
                    current = ""
        task = asyncio.create_task(reader())
        for i in range(0, len(pcm), 5120):
            await ws.send(pcm[i:i + 5120]); await asyncio.sleep(0.16)
        for _ in range(10):
            await ws.send(b"\0" * 5120); await asyncio.sleep(0.16)
        await ws.send("YOUDAO_ONETIME_ASR_STREAM_EOS")
        await asyncio.sleep(4); task.cancel()
    return segs

async def main():
    result = {"consecutive": [], "taigi": []}
    gap = b"\0" * (16000 * 2 * 2)  # 2 秒靜音隔開句子
    gate = asyncio.Semaphore(6)

    async def consecutive(lang, voice, texts):
        pcms = [await asyncio.to_thread(synth, voice, t) for t in texts]
        async with gate:
            segs = await session(gap.join(pcms))
        for i, s in enumerate(segs):
            ref = texts[i] if i < len(texts) else ""
            result["consecutive"].append({"lang": lang, "idx": i + 1, "ref": ref, **s, "stream_cer": round(cer(ref, s["stream"]), 3), "final_cer": round(cer(ref, s["final"]), 3)})
        print("done consecutive", lang, flush=True)

    async def taigi(item):
        pcm = to_pcm(Path(item["audio"]).read_bytes(), 0.0)
        async with gate:
            try:
                segs = await asyncio.wait_for(session(pcm), 90)
            except Exception as exc:
                segs = [{"stream": "", "final": f"<{type(exc).__name__}>", "language": None}]
        out = "".join(s["final"] for s in segs)
        result["taigi"].append({"id": item["id"], "ref": item["ref"], "out": out, "languages": [s["language"] for s in segs], "cer": round(cer(item["ref"], out), 3)})
        print("done taigi", len(result["taigi"]), flush=True)

    await asyncio.gather(
        *(consecutive(lang, voice, texts) for lang, (name, voice, texts) in CASES.items()),
        *(taigi(item) for item in clips() if item["set"] == "taigi"),
    )
    t = result["taigi"]
    result["taigi_summary"] = {"sentences": len(t), "mean_cer": round(statistics.mean(r["cer"] for r in t), 3),
                               "languages": Counter(l for r in t for l in r["languages"])}
    print(json.dumps(result["taigi_summary"], ensure_ascii=False), flush=True)
    OUT.write_text(json.dumps(result, ensure_ascii=False, indent=1))
asyncio.run(main())
