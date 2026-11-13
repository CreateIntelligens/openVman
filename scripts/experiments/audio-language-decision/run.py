"""Score clips with Gemini Decisions and apply the production verdict rule.

在 api 容器內執行（需要 GEMINI_API_KEY）：
    python3 run.py <wav 目錄>...
檔名前綴是正確答案：nan_*.wav、zh_*.wav、en_*.wav…（16 kHz 單聲道 WAV）。
"""

import base64
import glob
import json
import os
import sys
import time

import httpx

sys.path.insert(0, "/app")
from memory.audio_language_decision import _QUESTIONS, verdict  # noqa: E402

http = httpx.Client(timeout=30, headers={"x-goog-api-key": os.environ["GEMINI_API_KEY"]})
rows = []
for path in sorted(p for d in sys.argv[1:] for p in glob.glob(os.path.join(d, "*.wav"))):
    truth = os.path.basename(path).split("_")[0]
    started = time.perf_counter()
    response = http.post(
        "https://generativelanguage.googleapis.com/v1beta/decisions",
        json={
            "model": "gemini-decision-1",
            "input": [{"type": "audio", "data": base64.b64encode(open(path, "rb").read()).decode(),
                       "mime_type": "audio/wav"}],
            "questions": _QUESTIONS,
        },
    )
    seconds = time.perf_counter() - started
    scores = {k: round(v["noul"], 2) for k, v in response.json()["answers"].items()}
    rows.append({"clip": os.path.basename(path), "truth": truth, "p": scores, "s": round(seconds, 3)})
    print(rows[-1]["clip"], truth, verdict(scores), scores, round(seconds, 2), flush=True)

decided = [(r["truth"], verdict(r["p"])) for r in rows]
wrong = [(t, v) for t, v in decided if v is not None and (v == "nan") != (t == "nan")]
print(f"Decisions 自己下判斷 {sum(v is not None for _, v in decided)}/{len(rows)}，判錯 {len(wrong)}")
json.dump(rows, open("scores.json", "w"), ensure_ascii=False, indent=1)
