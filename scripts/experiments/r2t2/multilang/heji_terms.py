"""鶴記 10 題型號題（edge 兩種聲音，共 20 句），三家串流同一時間比：Gemini 3.5、R2T2 .37、R2T2 .35。一次一路。"""
import asyncio, json, sys, uuid
from pathlib import Path
import websockets
ROOT = Path(__file__).resolve().parents[4]; sys.path.insert(0, str(ROOT)); sys.path.insert(0, str(Path(__file__).parent))
from scripts.experiments.r2t2.run import clips, glossary
from scripts.voice_e2e.run import to_pcm, cer, terms_heard
from gemini_lang import stream as gemini_stream
from r2t2_lang import env
terms_prompt = glossary("proj-0cc5c610b4")

async def r2t2(pcm, url, key, language, prompt):
    header = {"channels": 1, "sample_rate": 16000, "requestId": str(uuid.uuid4()), "language": language,
              "output_script": "traditional", "use_vad": True, "secret_key": key, "system_prompt": prompt}
    text = ""
    async with websockets.connect(url, open_timeout=10) as ws:
        await ws.send(json.dumps(header)); await asyncio.wait_for(ws.recv(), 10)
        async def reader():
            nonlocal text
            async for raw in ws:
                msg = json.loads(raw).get("msg", {})
                if not isinstance(msg, dict): return
                if msg.get("reset"):
                    text = msg.get("final_text") or text + msg.get("text", ""); return
                text += msg.get("text", "")
        task = asyncio.create_task(reader())
        for i in range(0, len(pcm), 5120):
            await ws.send(pcm[i:i + 5120]); await asyncio.sleep(0.16)
        for _ in range(10):
            await ws.send(b"\0" * 5120); await asyncio.sleep(0.16)
        await ws.send("YOUDAO_ONETIME_ASR_STREAM_EOS")
        try: await asyncio.wait_for(task, 15)
        except asyncio.TimeoutError: pass
    return text

ENGINES = {
    "gemini(zh,en,es)": lambda pcm: gemini_stream(pcm, ["zh-TW", "en-US", "es-ES"]),
    ".37 Chinese+詞表": lambda pcm: r2t2(pcm, env["ASR_R2T2_DEV_STREAM_URL"], env["ASR_R2T2_DEV_SECRET_KEY"], "Chinese", terms_prompt),
    ".35 zhen+詞表": lambda pcm: r2t2(pcm, env["ASR_R2T2_STREAM_URL"], env["ASR_R2T2_SECRET_KEY"], "zhen", terms_prompt),
}

async def main():
    items = [c for c in clips() if c["set"] == "heji" and c["voice"].startswith("edge")]
    stats = {name: {"cer": [], "terms": 0, "terms_total": 0} for name in ENGINES}
    rows = []
    for item in items:
        pcm = to_pcm(item["audio"].read_bytes(), 0.0)
        for name, run in ENGINES.items():
            out = await run(pcm)
            c = cer(item["ref"], out); got = terms_heard(item["terms"], out)
            s = stats[name]; s["cer"].append(c); s["terms"] += len(got); s["terms_total"] += len(item["terms"])
            rows.append({"id": item["id"], "voice": item["voice"], "engine": name, "ref": item["ref"], "out": out, "cer": round(c, 3), "terms": f"{len(got)}/{len(item['terms'])}"})
            print(json.dumps(rows[-1], ensure_ascii=False), flush=True)
    for name, s in stats.items():
        print("SUMMARY", name, "CER", round(sum(s["cer"]) / len(s["cer"]), 3), "terms", f"{s['terms']}/{s['terms_total']}", flush=True)
    (Path(__file__).with_name("heji_terms_results.json")).write_text(json.dumps(rows, ensure_ascii=False, indent=1))
asyncio.run(main())
