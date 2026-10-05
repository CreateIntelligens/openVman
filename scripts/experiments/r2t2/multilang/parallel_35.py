"""R2T2 串流同時多路：每一路依序送鶴記 20 句（edge 兩種聲音），量沒定稿、錯字率與講完到定稿秒數。

    python3 scripts/experiments/r2t2/multilang/parallel_35.py 2        # .35 同時 2 路（zhen）
    python3 scripts/experiments/r2t2/multilang/parallel_35.py 2 37     # .37 同時 2 路（Chinese）
"""
import asyncio, json, statistics, sys, time, uuid
from pathlib import Path
import websockets
ROOT = Path(__file__).resolve().parents[4]; sys.path.insert(0, str(ROOT)); sys.path.insert(0, str(Path(__file__).parent))
from scripts.experiments.r2t2.run import clips, glossary
from scripts.voice_e2e.run import to_pcm, cer
from r2t2_lang import env

HOST = sys.argv[2] if len(sys.argv) > 2 else "35"
URL, KEY, LANGUAGE = ((env["ASR_R2T2_DEV_STREAM_URL"], env["ASR_R2T2_DEV_SECRET_KEY"], "Chinese") if HOST == "37"
                      else (env["ASR_R2T2_STREAM_URL"], env["ASR_R2T2_SECRET_KEY"], "zhen"))
PROMPT = glossary("proj-0cc5c610b4")

async def one(pcm):
    header = {"channels": 1, "sample_rate": 16000, "requestId": str(uuid.uuid4()), "language": LANGUAGE,
              "output_script": "traditional", "use_vad": True, "secret_key": KEY, "system_prompt": PROMPT}
    # .35 會在句中停頓就切段（reset），一句可能分成好幾段；收到 EOS 後連線關閉為止的段落全收。
    segments, current, final_at, error = [], "", None, None
    async with websockets.connect(URL, open_timeout=10) as ws:
        await ws.send(json.dumps(header)); await asyncio.wait_for(ws.recv(), 10)
        async def reader():
            nonlocal current, final_at, error
            async for raw in ws:
                m = json.loads(raw)
                if m.get("status") == "error":
                    error = str(m.get("msg"))[:80]; return
                msg = m.get("msg", {})
                current += msg.get("text", "")
                if msg.get("reset"):
                    segments.append((msg.get("final_text") or current).strip()); current = ""; final_at = time.monotonic()
        task = asyncio.create_task(reader())
        for i in range(0, len(pcm), 5120):
            await ws.send(pcm[i:i + 5120]); await asyncio.sleep(0.16)
        spoke_end = time.monotonic()
        for _ in range(10):
            await ws.send(b"\0" * 5120); await asyncio.sleep(0.16)
        await ws.send("YOUDAO_ONETIME_ASR_STREAM_EOS")
        try:
            await asyncio.wait_for(task, 20)
        except asyncio.TimeoutError:
            pass
        if current.strip():
            segments.append(current.strip())
        if not segments:
            error = error or "no final in 20s"
    return segments, (final_at - spoke_end) if final_at else None, error

async def lane(n, items, rows):
    for item in items:
        pcm = to_pcm(item["audio"].read_bytes(), 0.0)
        try:
            segments, wait, error = await asyncio.wait_for(one(pcm), 60)
        except Exception as exc:
            segments, wait, error = [], None, f"{type(exc).__name__}"
        text = "".join(segments)
        rows.append({"lane": n, "id": item["id"], "ref": item["ref"], "segments": segments, "out": text, "cer": round(cer(item["ref"], text), 3),
                     "last_final_after_speech_s": round(wait, 2) if wait else None, "error": error})

async def main(parallel):
    items = [c for c in clips() if c["set"] == "heji" and c["voice"].startswith("edge")]
    rows = []
    started = time.monotonic()
    await asyncio.gather(*(lane(n, items[n::1] if parallel == 1 else items, rows) for n in range(parallel)))
    waits = [r["last_final_after_speech_s"] for r in rows if r["last_final_after_speech_s"] is not None]
    summary = {"host": HOST, "parallel": parallel, "sentences": len(rows), "errors": sum(1 for r in rows if r["error"]),
               "mean_cer": round(statistics.mean(r["cer"] for r in rows), 3),
               "truncated(cer>=0.3)": sum(1 for r in rows if r["cer"] >= 0.3),
               "split_into_segments": sum(1 for r in rows if len(r.get("segments", [])) > 1),
               "final_wait_p50_s": round(statistics.median(waits), 2) if waits else None,
               "final_wait_max_s": max(waits) if waits else None, "wall_s": round(time.monotonic() - started, 1)}
    print(json.dumps(summary, ensure_ascii=False), flush=True)
    Path(__file__).with_name(f"parallel_{HOST}_x{parallel}.json").write_text(json.dumps({"summary": summary, "rows": rows}, ensure_ascii=False, indent=1))

if __name__ == "__main__":
    asyncio.run(main(int(sys.argv[1]) if len(sys.argv) > 1 else 1))
