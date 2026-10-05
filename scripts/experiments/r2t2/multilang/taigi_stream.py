"""台語連續劇真人 75 句：R2T2 串流（.35 zhen、.37 Chinese）輸出跟華語字幕比錯字率，一次一路。

10/1 的批次結果：R2T2 錯字率 0.81（寫成台語漢字）、Breeze 0.36（翻成華語）。
"""
import asyncio, json, statistics, sys, uuid
from pathlib import Path
import websockets
ROOT = Path(__file__).resolve().parents[4]; sys.path.insert(0, str(ROOT)); sys.path.insert(0, str(Path(__file__).parent))
from scripts.experiments.r2t2.run import clips
from scripts.voice_e2e.run import to_pcm, cer
from r2t2_lang import env

TARGETS = {
    ".35 zhen": (env["ASR_R2T2_DEV_STREAM_URL"], env["ASR_R2T2_DEV_SECRET_KEY"], "zhen"),
    ".37 Chinese": (env["ASR_R2T2_STREAM_URL"], env["ASR_R2T2_SECRET_KEY"], "Chinese"),
}

async def one(pcm, url, key, language):
    header = {"channels": 1, "sample_rate": 16000, "requestId": str(uuid.uuid4()), "language": language,
              "output_script": "traditional", "use_vad": True, "secret_key": key, "system_prompt": ""}
    segments, current = [], ""
    async with websockets.connect(url, open_timeout=10) as ws:
        await ws.send(json.dumps(header)); await asyncio.wait_for(ws.recv(), 10)
        async def reader():
            nonlocal current
            async for raw in ws:
                msg = json.loads(raw).get("msg")
                if not isinstance(msg, dict): continue
                current += msg.get("text", "")
                if msg.get("reset"):
                    segments.append((msg.get("final_text") or current).strip()); current = ""
        task = asyncio.create_task(reader())
        for i in range(0, len(pcm), 5120):
            await ws.send(pcm[i:i + 5120]); await asyncio.sleep(0.16)
        for _ in range(10):
            await ws.send(b"\0" * 5120); await asyncio.sleep(0.16)
        await ws.send("YOUDAO_ONETIME_ASR_STREAM_EOS")
        await asyncio.sleep(4); task.cancel()
    return "".join(segments) + current

async def main():
    # 握手帶 output_script=traditional，.35／.37 都直接出繁體，不另外轉。
    items = [c for c in clips() if c["set"] == "taigi"]
    rows = []
    for item in items:
        pcm = to_pcm(Path(item["audio"]).read_bytes(), 0.0)
        for name, (url, key, language) in TARGETS.items():
            try:
                out = await asyncio.wait_for(one(pcm, url, key, language), 90)
            except Exception as exc:
                out = f"<{type(exc).__name__}>"
            rows.append({"id": item["id"], "engine": name, "ref": item["ref"], "out": out, "cer": round(cer(item["ref"], out), 3)})
    summary = {name: round(statistics.mean(r["cer"] for r in rows if r["engine"] == name), 3) for name in TARGETS}
    print(json.dumps({"sentences": len(items), "mean_cer_vs_mandarin_subtitle": summary}, ensure_ascii=False), flush=True)
    Path(__file__).with_name("taigi_stream_results.json").write_text(json.dumps({"summary": summary, "rows": rows}, ensure_ascii=False, indent=1))

if __name__ == "__main__":
    asyncio.run(main())
