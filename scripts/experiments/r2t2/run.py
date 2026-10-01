"""Confucius4-R2T2（Qwen3-ASR）對比 Breeze：同一批音檔，帶不帶專案詞表。

在 repo 根目錄、主機上執行（需要 docker compose 進 api 容器讀詞表）：

    python3 scripts/experiments/r2t2/run.py

音檔：
- 鶴記 10 題 × 4 種合成聲音（scripts/voice_e2e/.cache，先跑過 voice_e2e 才有）
- 台語連續劇真人 75 句（/srv/818data，scripts/voice_e2e/cases/taigi-drama.json）

兩邊都直接打 /transcribe（一次一句、不並行），R2T2 的詞表放 context、Breeze 放 prompt。
結果寫到 scripts/experiments/r2t2/results.json。
"""

from __future__ import annotations

import hashlib
import json
import subprocess
import sys
import time
from pathlib import Path

import httpx

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT))

from scripts.voice_e2e.run import cer, terms_heard, to_pcm, wav_bytes  # noqa: E402

R2T2_URL = "http://10.9.0.35:8040/transcribe"
BREEZE_URL = "http://10.9.0.37:8801/transcribe"
CASES = ROOT / "scripts" / "voice_e2e" / "cases"
CACHE = ROOT / "scripts" / "voice_e2e" / ".cache"
OUT = Path(__file__).with_name("results.json")


def glossary(project_id: str) -> str:
    code = (
        "import sys; sys.path.insert(0, '/app'); "
        "from core.asr_glossary import asr_terms; "
        f"print(asr_terms({project_id!r}))"
    )
    result = subprocess.run(
        ["docker", "compose", "exec", "-T", "api", "python3", "-c", code],
        capture_output=True, text=True, cwd=ROOT, check=True,
    )
    return result.stdout.strip()


def clips() -> list[dict]:
    heji = json.loads((CASES / "heji.json").read_text(encoding="utf-8"))
    items = []
    for voice in heji["voices"]:
        provider, _, voice_id = voice.partition(":")
        for case in heji["cases"]:
            key = hashlib.sha256(f"{provider}|{voice_id}|{case['text']}".encode()).hexdigest()[:24]
            items.append({
                "set": "heji", "id": case["id"], "voice": voice, "ref": case["text"],
                "terms": case["terms"], "audio": CACHE / f"{key}.audio",
            })
    taigi = json.loads((CASES / "taigi-drama.json").read_text(encoding="utf-8"))
    for case in taigi["cases"]:
        items.append({
            "set": "taigi", "id": case["id"], "voice": "recording", "ref": case["text"],
            "terms": [], "audio": Path(case["audio"]),
        })
    return items


def ask(client: httpx.Client, engine: str, wav: bytes, terms: str) -> dict:
    files = {"file": ("speech.wav", wav, "audio/wav")}
    if engine == "r2t2":
        url, data = R2T2_URL, {"language": "Chinese", "context": terms}
    else:
        url, data = BREEZE_URL, ({"prompt": terms} if terms else None)
    started = time.monotonic()
    try:
        response = client.post(url, files=files, data=data)
        response.raise_for_status()
        text = str(response.json().get("text", "")).strip()
    except Exception as exc:  # noqa: BLE001 - 一句失敗照樣跑完
        return {"error": f"{type(exc).__name__}: {exc}"[:200]}
    return {"text": text, "ms": round((time.monotonic() - started) * 1000)}


def main() -> None:
    terms = glossary("proj-0cc5c610b4")
    print("詞表:", terms[:80], "…")
    rows = []
    with httpx.Client(timeout=120) as client:
        items = clips()
        for n, item in enumerate(items, 1):
            wav = wav_bytes(to_pcm(item["audio"].read_bytes(), 0.0))
            row = {k: v for k, v in item.items() if k != "audio"}
            # 台語題庫不是鶴記的內容，帶鶴記詞表沒有意義，只測不帶。
            settings = ("plain", "glossary") if item["set"] == "heji" else ("plain",)
            for engine in ("r2t2", "breeze"):
                for setting in settings:
                    result = ask(client, engine, wav, terms if setting == "glossary" else "")
                    if "text" in result:
                        result["cer"] = round(cer(item["ref"], result["text"]), 3)
                        result["terms_ok"] = len(terms_heard(item["terms"], result["text"])) == len(item["terms"])
                    row[f"{engine}_{setting}"] = result
            rows.append(row)
            print(f"{n:3}/{len(items)} {item['set']:5} {item['id']:18} "
                  f"r2t2={row['r2t2_plain'].get('text', row['r2t2_plain'].get('error'))!r:.40} "
                  f"breeze={row['breeze_plain'].get('text', row['breeze_plain'].get('error'))!r:.40}", flush=True)
    OUT.write_text(json.dumps(rows, ensure_ascii=False, indent=1), encoding="utf-8")
    summarize(rows)


def summarize(rows: list[dict]) -> None:
    print("\n題庫  聲音                    引擎_設定          題數 失敗 平均錯字率 專有名詞 p50ms p90ms")
    groups: dict[tuple, list] = {}
    for row in rows:
        voice = row["voice"] if row["set"] == "heji" else "recording"
        for key, result in row.items():
            if key.startswith(("r2t2_", "breeze_")):
                groups.setdefault((row["set"], voice, key), []).append((row, result))
    for (set_name, voice, key), pairs in sorted(groups.items()):
        ok = [(r, x) for r, x in pairs if "text" in x]
        ms = sorted(x["ms"] for _, x in ok) or [0]
        with_terms = [x for r, x in ok if r["terms"]]
        print(f"{set_name:5} {voice[:22]:22} {key:18} {len(pairs):4} {len(pairs) - len(ok):4} "
              f"{sum(x['cer'] for _, x in ok) / max(len(ok), 1):10.3f} "
              f"{sum(x['terms_ok'] for x in with_terms):>4}/{len(with_terms):<3} "
              f"{ms[len(ms) // 2]:5} {ms[int(len(ms) * 0.9)]:5}")


if __name__ == "__main__":
    main()
