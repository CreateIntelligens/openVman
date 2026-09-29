"""真人語料重跑：Breeze 轉寫與台語判斷（在 backend 容器內執行）。

音檔與 manifest*.json 放在 /tmp/taigi_real；結果寫到 /tmp/taigi_real/real.json。
走正式程式碼路徑：ASR 用 _transcribe_breeze，判斷用 detect_taiwanese（經 Brain）。
"""
import asyncio
import glob
import json
import re
import sys
import time

sys.path.insert(0, "/app")
from app.gateway.ingestion_audio import _transcribe_breeze  # noqa: E402
from app.language_routes import detect_taiwanese  # noqa: E402

ROOT = "/tmp/taigi_real"


def _norm(text: str) -> str:
    return re.sub(r"[^\w]", "", text or "").lower()


def cer(ref: str, hyp: str) -> float:
    ref, hyp = _norm(ref), _norm(hyp)
    if not ref:
        return 0.0
    prev = list(range(len(hyp) + 1))
    for i, rc in enumerate(ref, 1):
        cur = [i]
        for j, hc in enumerate(hyp, 1):
            cur.append(min(prev[j] + 1, cur[j - 1] + 1, prev[j - 1] + (rc != hc)))
        prev = cur
    return prev[-1] / len(ref)


async def _timed(coro):
    t0 = time.perf_counter()
    try:
        result = await coro
    except Exception as exc:  # noqa: BLE001
        result = f"ERROR {type(exc).__name__}: {exc}"
    return result, round(time.perf_counter() - t0, 2)


async def run_one(item: dict) -> dict:
    path = f"{ROOT}/{item['key']}.wav"
    (text, asr_s), (lang, lang_s) = await asyncio.gather(
        _timed(_transcribe_breeze(path, item["key"])),
        _timed(detect_taiwanese(path)),
    )
    out = {**item, "breeze": text, "asr_s": asr_s, "language": lang, "lang_s": lang_s}
    if "ref" in item:
        out["cer"] = round(cer(item["ref"], text), 3)
    return out


async def main() -> None:
    items = []
    for manifest in sorted(glob.glob(f"{ROOT}/manifest*.json")):
        items += json.load(open(manifest, encoding="utf-8"))
    results = []
    for item in items:
        r = await run_one(item)
        results.append(r)
        print(f"{r['key']} {r['language']} {r['lang_s']}s | {r['breeze'][:40]} | {r.get('ref', r.get('ref_tai'))}", flush=True)
    json.dump(results, open(f"{ROOT}/real.json", "w", encoding="utf-8"), ensure_ascii=False, indent=1)


asyncio.run(main())
