"""Compare whole-file English ASR: OpenAI vs Gemini generateContent vs Gemini Live fed a whole clip.

Runs the backend's own transcriber functions (this worktree's backend/), so what is measured is
what /api/v1/asr/transcribe would run. See README.md for how to supply credentials.

    python3 scripts/experiments/gemini-asr/bench.py run [--reps 3] [--engines a,b]
    python3 scripts/experiments/gemini-asr/bench.py report results/<file>.json
    python3 scripts/experiments/gemini-asr/bench.py generate-tts   # needs edge-tts >= 7.3
"""

from __future__ import annotations

import argparse
import asyncio
import fnmatch
import json
import os
import re
import statistics
import subprocess
import sys
import time
import types
from datetime import datetime
from pathlib import Path
from unittest.mock import MagicMock

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / "backend"))
# ingestion_audio 間接 import 文件轉檔套件；主機上沒裝，轉寫用不到它。
sys.modules.setdefault("anydoc", types.SimpleNamespace(to_markdown=MagicMock(return_value="")))

from app.gateway import gemini_live_batch, ingestion_audio
from app.gateway import gemini_transcription as gemini

sys.path.insert(0, str(Path(__file__).resolve().parent))
import retired_engines

DATA = Path(os.environ.get("GEMINI_ASR_DATA", Path.home() / "openvman-experiments/gemini-asr"))
AUDIO = DATA / "audio"
SILENCE = DATA / "silence"
RESULTS = DATA / "results"
AUDIO_SUFFIXES = {".wav", ".mp3", ".webm", ".m4a", ".ogg", ".flac"}
ROUTES = ["en"]  # kiosk English mode

# engine id → (label, how to call)
ENGINES = {
    "openai": "OpenAI (ASR_OPENAI_MODEL)",
    "gemini-live-batch": "A: Live, manual activity, 0.3 s lead (shipped engine)",
    "gemini": "B: generateContent gemini-3.5-transcribe (not shipped)",
    "gemini-llm": "B': generateContent gemini-3.5-flash-lite + strict prompt (not shipped)",
    "gemini-live-batch-auto": "A': Live, server VAD + audioStreamEnd (not shipped)",
}
LLM_MODEL = os.environ.get("BENCH_GEMINI_LLM_MODEL", "gemini-3.5-flash-lite")


def _credential() -> str:
    key = os.environ.get("GEMINI_API_KEY", "")
    if not key:
        sys.exit("GEMINI_API_KEY is not set (see README.md)")
    return key


async def _call(engine: str, path: Path, credential: str) -> dict:
    extra: dict = {}
    if engine == "openai":
        text = await ingestion_audio._transcribe_openai(str(path), "bench")
        model = ingestion_audio.get_tts_config().asr_openai_model
    elif engine in ("gemini", "gemini-llm"):
        os.environ["ASR_GEMINI_BATCH_MODEL"] = (
            "gemini-3.5-transcribe" if engine == "gemini" else LLM_MODEL
        )
        result = await retired_engines.generate_content(str(path), ROUTES, credential)
        text, model = result.text, result.model
        extra["usage"] = {
            k: result.usage.get(k)
            for k in ("promptTokenCount", "candidatesTokenCount", "thoughtsTokenCount")
            if result.usage.get(k) is not None
        }
    elif engine == "gemini-live-batch":
        pcm = await asyncio.to_thread(ingestion_audio._decode_pcm16, str(path))
        result = await gemini_live_batch.transcribe_pcm(
            pcm, api_key=credential,
            transcription=gemini.transcription_config(gemini.languages_for(ROUTES)),
            connect_timeout=10,
        )
        text, model = result.text, gemini.live_model()
        extra.update(
            finals=len(result.finals), completed_by=result.completed_by,
            audio_seconds=round(len(pcm) / (2 * gemini.SAMPLE_RATE), 2),
        )
    else:
        result = await retired_engines.live_auto_vad(str(path), ROUTES, credential)
        text, model = result["text"], gemini.live_model()
        extra.update(
            finals=len(result["finals"]), completed_by=result["completed_by"],
            audio_seconds=result["audio_seconds"],
        )
    return {"text": text, "model": model, **extra}


async def _timed(engine: str, path: Path, credential: str) -> dict:
    started = time.monotonic()
    try:
        out = await _call(engine, path, credential)
    except Exception as exc:  # noqa: BLE001 - 記下來繼續跑
        # 只記型別與前 160 字：例外訊息不帶金鑰（函式本身已 from None），仍保守截斷。
        out = {"text": None, "error": f"{type(exc).__name__}: {str(exc)[:160]}"}
    out["latency_s"] = round(time.monotonic() - started, 3)
    return out


# --- scoring ---------------------------------------------------------------------

_ONES = ["zero", "one", "two", "three", "four", "five", "six", "seven", "eight", "nine", "ten", "eleven", "twelve", "thirteen", "fourteen", "fifteen", "sixteen", "seventeen", "eighteen", "nineteen"]
_TENS = ["_", "_", "twenty", "thirty", "forty", "fifty", "sixty", "seventy", "eighty", "ninety"]


def _number_words(token: str) -> str:
    n = int(token)
    if n < 20:
        return _ONES[n]
    if n < 100:
        return _TENS[n // 10] + ("" if n % 10 == 0 else " " + _ONES[n % 10])
    return token


def normalize(text: str) -> str:
    text = text.lower().replace("-", " ").replace("’", "'")
    text = re.sub(r"\b\d{1,2}\b", lambda m: _number_words(m.group()), text)
    text = re.sub(r"[^\w\s']", " ", text)
    return " ".join(text.split())


def wer(reference: str, hypothesis: str) -> float:
    ref, hyp = normalize(reference).split(), normalize(hypothesis).split()
    if not ref:
        return 0.0 if not hyp else 1.0
    row = list(range(len(hyp) + 1))
    for i, r in enumerate(ref, 1):
        prev, row[0] = row[0], i
        for j, h in enumerate(hyp, 1):
            prev, row[j] = row[j], min(row[j] + 1, row[j - 1] + 1, prev + (r != h))
    return row[-1] / len(ref)


# --- audio inventory -------------------------------------------------------------


def _sources() -> dict:
    path = AUDIO / "sources.json"
    return json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}


def source_group(name: str, sources: dict) -> str:
    if name in sources.get("files", {}):
        return sources["files"][name]
    for pattern, group in sources.get("patterns", {}).items():
        if fnmatch.fnmatch(name, pattern):
            return group
    return "real recording"


def _levels(path: Path) -> dict:
    probe = subprocess.run(
        ["ffmpeg", "-hide_banner", "-i", str(path), "-af", "volumedetect", "-f", "null", "-"],
        capture_output=True, text=True, check=False,
    ).stderr
    duration = re.search(r"Duration: (\d+):(\d+):([\d.]+)", probe)
    mean = re.search(r"mean_volume: (-?[\d.]+|-inf) dB", probe)
    return {
        "duration_s": (
            round(int(duration[1]) * 3600 + int(duration[2]) * 60 + float(duration[3]), 2)
            if duration else None
        ),
        "mean_db": float(mean[1]) if mean and mean[1] != "-inf" else None,
    }


def clips() -> list[dict]:
    sources = _sources()
    out = []
    for path in sorted(AUDIO.iterdir()):
        if path.suffix.lower() not in AUDIO_SUFFIXES:
            continue
        ref = path.with_suffix(".txt")
        out.append({
            "file": path.name, "path": str(path),
            "reference": ref.read_text(encoding="utf-8").strip() if ref.exists() else None,
            "source": source_group(path.name, sources),
            **_levels(path),
        })
    return out


def make_silence() -> list[dict]:
    SILENCE.mkdir(parents=True, exist_ok=True)
    specs = {
        "silence_3s.wav": ["-f", "lavfi", "-i", "anullsrc=r=16000:cl=mono", "-t", "3"],
        "low_noise_3s.wav": ["-f", "lavfi", "-i", "anoisesrc=r=16000:a=0.003:c=pink", "-t", "3"],
        "blank_1s.wav": ["-f", "lavfi", "-i", "anullsrc=r=16000:cl=mono", "-t", "1"],
    }
    out = []
    for name, args in specs.items():
        path = SILENCE / name
        if not path.exists():
            subprocess.run(
                ["ffmpeg", "-y", "-loglevel", "error", *args, "-ac", "1",
                 "-c:a", "pcm_s16le", str(path)],
                check=True,
            )
        out.append({"file": name, "path": str(path), "reference": "", "source": "silence",
                    **_levels(path)})
    return out


# --- run & report ----------------------------------------------------------------


async def run(reps: int, engines: list[str], only: str = "*") -> Path:
    credential = _credential()
    items = [c for c in clips() + make_silence() if fnmatch.fnmatch(c["file"], only)]
    runs = []
    for rep in range(reps):
        for item in items:
            for engine in engines:
                out = await _timed(engine, Path(item["path"]), credential)
                runs.append({"file": item["file"], "engine": engine, "rep": rep, **out})
                print(
                    f"rep{rep} {engine:24} {item['file'][:28]:28} {out['latency_s']:6.2f}s "
                    f"{(out.get('text') if out.get('text') is not None else out.get('error'))!r:.70}",
                    flush=True,
                )
    RESULTS.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    path = RESULTS / f"results_{stamp}.json"
    path.write_text(json.dumps({
        "created": stamp, "reps": reps, "routes": ROUTES,
        "engines": {e: ENGINES[e] for e in engines},
        "openai_model": ingestion_audio.get_tts_config().asr_openai_model,
        "live_model": os.environ.get("ASR_GEMINI_STREAM_MODEL", "gemini-3.5-transcribe-live"),
        "llm_model": LLM_MODEL,
        "clips": items, "runs": runs,
    }, ensure_ascii=False, indent=1), encoding="utf-8")
    return path


def _pct(values: list[float], q: float) -> float:
    ordered = sorted(values)
    return ordered[min(len(ordered) - 1, round(q * (len(ordered) - 1)))]


def report(path: Path) -> Path:
    data = json.loads(path.read_text(encoding="utf-8"))
    engines = list(data["engines"])
    speech = [c for c in data["clips"] if c["source"] != "silence"]
    silence = [c for c in data["clips"] if c["source"] == "silence"]
    by = {}
    for r in data["runs"]:
        by.setdefault((r["file"], r["engine"]), []).append(r)

    def scored(clip, engine):
        return [wer(clip["reference"], r["text"]) for r in by.get((clip["file"], engine), [])
                if r.get("text") is not None]

    # 壞音源：每個引擎的中位 WER 都 > 0.5（三家都聽不出參考句），或長度、音量明顯異常。
    for clip in speech:
        medians = [statistics.median(s) for e in engines if (s := scored(clip, e))]
        reasons = []
        if clip["reference"] and medians and min(medians) > 0.5:
            reasons.append("all engines far from reference")
        if (clip.get("duration_s") or 0) < 0.8:
            reasons.append("too short")
        if clip.get("mean_db") is None or clip["mean_db"] < -45:
            reasons.append("too quiet")
        clip["bad_source"] = "; ".join(reasons)

    lines = [f"# Gemini whole-file ASR comparison ({data['created']})", "",
             (f"reps={data['reps']} routes={data['routes']} openai={data['openai_model']} "
              f"live={data['live_model']} llm={data['llm_model']}"), ""]
    lines += ["Engines: " + "; ".join(f"`{e}` = {label}" for e, label in data["engines"].items()), ""]

    groups = sorted({c["source"] for c in speech})
    lines += ["## Summary (clips with reference, bad sources excluded)", "",
              "| engine | group | clips | exact match | mean WER | median latency s | p90 latency s | errors |",
              "|---|---|---|---|---|---|---|---|"]
    for engine in engines:
        for group in [*groups, "ALL"]:
            members = [c for c in speech if c["reference"] and not c["bad_source"]
                       and (group == "ALL" or c["source"] == group)]
            runs = [(c, r) for c in members for r in by.get((c["file"], engine), [])]
            ok = [(c, r) for c, r in runs if r.get("text") is not None]
            if not runs:
                continue
            exact = sum(normalize(c["reference"]) == normalize(r["text"]) for c, r in ok)
            wers = [wer(c["reference"], r["text"]) for c, r in ok]
            lat = [r["latency_s"] for _, r in ok]
            lines.append(
                f"| {engine} | {group} | {len(members)} | {exact}/{len(ok)} "
                f"({exact / max(1, len(ok)):.0%}) | {statistics.mean(wers) if wers else float('nan'):.3f} | "
                f"{statistics.median(lat) if lat else float('nan'):.2f} | "
                f"{_pct(lat, 0.9) if lat else float('nan'):.2f} | {len(runs) - len(ok)} |"
            )
    live_runs = [r for r in data["runs"] if r["engine"].startswith("gemini-live-batch")
                 and r.get("finals") is not None]
    if live_runs:
        lines += ["", "## Live (A) finals per clip and completion signal", "",
                  "| engine | finals=0 | finals=1 | finals>1 | completed_by |", "|---|---|---|---|---|"]
        for engine in [e for e in engines if e.startswith("gemini-live-batch")]:
            rs = [r for r in live_runs if r["engine"] == engine
                  and r["file"] not in {c["file"] for c in silence}]
            counts = [r["finals"] for r in rs]
            done = {}
            for r in rs:
                done[r["completed_by"]] = done.get(r["completed_by"], 0) + 1
            lines.append(f"| {engine} | {counts.count(0)} | {counts.count(1)} | "
                         f"{sum(c > 1 for c in counts)} | {done} |")

    lines += ["", "## Silence (any non-empty output is a failure)", "",
              "| file | engine | outputs | latency s (median) |", "|---|---|---|---|"]
    for clip in silence:
        for engine in engines:
            rs = by.get((clip["file"], engine), [])
            outs = [r["text"] if r.get("text") is not None else f"ERR {r['error']}" for r in rs]
            flag = "**NON-EMPTY** " if any(o for o in outs) else ""
            lat = statistics.median(r["latency_s"] for r in rs) if rs else float("nan")
            lines.append(f"| {clip['file']} | {engine} | {flag}{json.dumps(outs, ensure_ascii=False)} | {lat:.2f} |")

    lines += ["", "## Per clip (median WER over reps / median latency s; A shows finals)", "",
              "| clip | source | dur s | reference | " + " | ".join(engines) + " |",
              "|---|---|---|---|" + "---|" * len(engines)]
    for clip in speech:
        cells = []
        for engine in engines:
            rs = by.get((clip["file"], engine), [])
            ok = [r for r in rs if r.get("text") is not None]
            if not ok:
                cells.append("error")
                continue
            w = statistics.median(wer(clip["reference"] or "", r["text"]) for r in ok)
            lat = statistics.median(r["latency_s"] for r in ok)
            fin = f" f={'/'.join(str(r['finals']) for r in ok)}" if "finals" in ok[0] else ""
            cells.append(f"{w:.2f} / {lat:.2f}{fin}")
        name = clip["file"] + (f" **bad source: {clip['bad_source']}**" if clip["bad_source"] else "")
        lines.append(f"| {name} | {clip['source']} | {clip.get('duration_s')} | "
                     f"{clip['reference']} | " + " | ".join(cells) + " |")

    lines += ["", "## Transcripts (all reps)", ""]
    for clip in speech:
        lines.append(f"- **{clip['file']}** — ref: {clip['reference']}")
        for engine in engines:
            outs = [r["text"] if r.get("text") is not None else f"ERR {r['error']}"
                    for r in by.get((clip["file"], engine), [])]
            lines.append(f"  - {engine}: {json.dumps(outs, ensure_ascii=False)}")

    out = path.with_suffix(".md")
    out.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return out


# --- test audio ------------------------------------------------------------------

TTS_ITEMS = [
    ("tts_restroom_us", "en-US-JennyNeural", "Where is the restroom?"),
    ("tts_saturday_gb", "en-GB-RyanNeural", "What time does the clinic open on Saturday?"),
    ("tts_dermatology_in", "en-IN-NeerjaNeural",
     "Can I make an appointment for dermatology tomorrow morning?"),
    ("tts_parking_us", "en-US-GuyNeural", "How much is the parking fee per hour?"),
    ("tts_pump_gb", "en-GB-SoniaNeural", "Do you have a pump that can lift water twelve meters?"),
    ("tts_lost_card_in", "en-IN-PrabhatNeural", (
        "I lost my health insurance card on the way here. Can I still see the doctor today, "
        "and how do I get a replacement?"
    )),
    ("tts_pharmacy_us", "en-US-AriaNeural", "Is the pharmacy on the first floor or the second floor?"),
    ("tts_xray_gb", "en-GB-RyanNeural", "How long do I have to wait for my X-ray results?"),
]


async def generate_tts() -> None:
    # edge-tts 7.2.x 連線會被 Bing 回 403，要 7.3 以上。
    import edge_tts

    AUDIO.mkdir(parents=True, exist_ok=True)
    for name, voice, text in TTS_ITEMS:
        mp3 = AUDIO / f"{name}.mp3"
        await edge_tts.Communicate(text, voice).save(str(mp3))
        subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-i", str(mp3),
                        "-ac", "1", "-ar", "16000", str(AUDIO / f"{name}.wav")], check=True)
        mp3.unlink()
        (AUDIO / f"{name}.txt").write_text(text + "\n", encoding="utf-8")
        print(name, voice)


def main() -> None:
    parser = argparse.ArgumentParser()
    sub = parser.add_subparsers(dest="command", required=True)
    run_p = sub.add_parser("run")
    run_p.add_argument("--reps", type=int, default=3)
    run_p.add_argument("--engines", default=",".join(ENGINES))
    run_p.add_argument("--only", default="*", help="glob over clip file names")
    report_p = sub.add_parser("report")
    report_p.add_argument("results", type=Path)
    sub.add_parser("generate-tts")
    args = parser.parse_args()
    if args.command == "run":
        engines = [e for e in args.engines.split(",") if e]
        unknown = set(engines) - set(ENGINES)
        if unknown:
            sys.exit(f"unknown engines: {sorted(unknown)}")
        path = asyncio.run(run(args.reps, engines, args.only))
        print("results:", path)
        print("report:", report(path))
    elif args.command == "report":
        print("report:", report(args.results))
    else:
        asyncio.run(generate_tts())


if __name__ == "__main__":
    main()
