"""R2T2 串流（WebSocket /asr_stream_api_v1）：準確度、講完到斷句的延遲、同時多路。

在 repo 根目錄、主機上執行：

    python3 scripts/experiments/r2t2/stream.py            # 鶴記 40 句，帶／不帶詞表
    python3 scripts/experiments/r2t2/stream.py --parallel 3   # 同時 3 路

照 R2T2 規格每 0.16 秒送 5120 bytes（16 kHz PCM16），握手帶 system_prompt（詞表）。
講完後送 1.5 秒靜音讓它的 VAD 斷句（約 0.7 秒停頓），記第一個 reset=true 的時間。
對照組是 Gemini Live：scripts/voice_e2e 9-30 同一批音檔的串流結果。
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
import time
import uuid
from pathlib import Path

import websockets

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT))

from scripts.experiments.r2t2.run import clips, glossary  # noqa: E402
from scripts.voice_e2e.run import to_pcm  # noqa: E402

URL = "ws://10.9.0.35:8040/asr_stream_api_v1"
EOS = "YOUDAO_ONETIME_ASR_STREAM_EOS"
CHUNK = 5120
STEP = 0.16
OUT = Path(__file__).with_name("stream_results.json")


def voiced_seconds(pcm: bytes, threshold: int = 500) -> float:
    """Where the last audible sample is: synthesized clips end with silence of varying length."""
    import array

    samples = array.array("h", pcm)
    for index in range(len(samples) - 1, -1, -1):
        if abs(samples[index]) > threshold:
            return (index + 1) / 16000
    return 0.0


async def stream_one(pcm: bytes, system_prompt: str, url: str = URL) -> dict:
    header = {"requestId": str(uuid.uuid4()), "language": "zhen", "use_vad": True, "secret_key": "test0102"}
    if system_prompt:
        header["system_prompt"] = system_prompt
    pieces: list[str] = []
    finals: list[str] = []
    first_reset = None
    first_text = None
    async with websockets.connect(url, max_size=None) as ws:
        await ws.send(json.dumps(header))

        async def reader():
            nonlocal first_reset, first_text
            async for raw in ws:
                msg = json.loads(raw)
                body = msg.get("msg") or {}
                if body.get("text"):
                    pieces.append(body["text"])
                    first_text = first_text or time.monotonic()
                # .37 版斷句時多回 final_text（整句重新辨識）：以它為定稿。
                if body.get("reset") and body.get("final_text"):
                    finals.append(body["final_text"])
                if body.get("reset") and first_reset is None and (pieces or finals):
                    first_reset = time.monotonic()

        task = asyncio.create_task(reader())
        started = time.monotonic()
        silence = b"\0" * CHUNK
        for chunk in [pcm[i:i + CHUNK] for i in range(0, len(pcm), CHUNK)]:
            await ws.send(chunk.ljust(CHUNK, b"\0"))
            await asyncio.sleep(STEP)
        # 照實際時間送，所以最後一個有聲音的取樣就落在 started + voiced 秒。
        spoke_until = started + voiced_seconds(pcm)
        for _ in range(10):
            await ws.send(silence)
            await asyncio.sleep(STEP)
        await ws.send(EOS)
        try:
            await asyncio.wait_for(task, timeout=6)
        except asyncio.TimeoutError:
            task.cancel()
    return {
        "text": "".join(finals) or "".join(pieces),
        "delta_text": "".join(pieces),
        "reset_ms": round((first_reset - spoke_until) * 1000) if first_reset else None,
    }


async def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--parallel", type=int, default=1)
    parser.add_argument("--url", default=URL)
    parser.add_argument("--tag", default="", help="結果檔名後綴，例如 37")
    args = parser.parse_args()
    terms = glossary("proj-0cc5c610b4")
    items = [item for item in clips() if item["set"] == "heji"]
    gate = asyncio.Semaphore(args.parallel)
    rows: list[dict] = []

    async def run(item, setting):
        async with gate:
            pcm = to_pcm(item["audio"].read_bytes(), 0.0)
            result = await stream_one(pcm, terms if setting == "glossary" else "", args.url)
            row = {k: v for k, v in item.items() if k != "audio"} | {"setting": setting, **result}
            rows.append(row)
            print(f"{item['id']:18} {item['voice'][:24]:24} {setting:8} reset={result['reset_ms']}ms {result['text']!r:.50}",
                  flush=True)

    settings = ("plain", "glossary") if args.parallel == 1 else ("glossary",)
    await asyncio.gather(*(run(item, s) for item in items for s in settings))
    suffix = (f"_{args.tag}" if args.tag else "") + (f"_parallel{args.parallel}" if args.parallel > 1 else "")
    out = OUT.with_name(f"stream_results{suffix}.json")
    out.write_text(json.dumps(rows, ensure_ascii=False, indent=1), encoding="utf-8")


if __name__ == "__main__":
    asyncio.run(main())
