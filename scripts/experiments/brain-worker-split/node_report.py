"""Break a `burst_nodes.py` run into per-step timings and summarize container resources.

    python3 node_report.py run.json --brain <chat container> [--resources monitor.jsonl] \
        [--containers backend,api-chat,...] [--out report.json]

Brain log lines carry `trace_id` and `ts_ms` (epoch ms); `done` gives each question's
`trace_id`, so client timestamps and Brain steps share one clock (same host).
"""

from __future__ import annotations

import argparse
import json
import math
import statistics
import subprocess
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path


def pct(values: list[float], p: float) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    return ordered[max(0, math.ceil(len(ordered) * p) - 1)]


def summary(values: list[float]) -> dict:
    values = [v for v in values if v is not None]
    if not values:
        return {"n": 0}
    return {
        "n": len(values),
        "median": round(statistics.median(values), 3),
        "p95": round(pct(values, 0.95), 3),
        "max": round(max(values), 3),
    }


def brain_events(container: str, since: float, until: float) -> dict[str, list[dict]]:
    iso = lambda t: datetime.fromtimestamp(t, timezone.utc).isoformat()  # noqa: E731
    output = subprocess.run(
        ["docker", "logs", "--since", iso(since), "--until", iso(until), container],
        capture_output=True, text=True, check=False,
    )
    by_trace: dict[str, list[dict]] = defaultdict(list)
    for line in (output.stdout + output.stderr).splitlines():
        start = line.find("{")
        if start < 0 or "trace_id" not in line:
            continue
        try:
            event = json.loads(line[start:])
        except ValueError:
            continue
        if event.get("trace_id") and event.get("ts_ms"):
            by_trace[event["trace_id"]].append(event)
    return by_trace


def brain_steps(events: list[dict]) -> dict:
    """Seconds (epoch) or durations for one turn, from its Brain log events."""
    def begin(event):  # an event is logged when its step ends
        return (event["ts_ms"] - float(event.get("elapsed_ms") or 0)) / 1000

    steps: dict = {"brain_start": min(begin(event) for event in events)}
    rag = [event for event in events if str(event.get("node", "")).startswith("rag_")]
    if rag:
        steps["knowledge_seconds"] = max(e["ts_ms"] for e in rag) / 1000 - min(begin(e) for e in rag)
    for event in events:
        node, name = event.get("node"), event.get("event")
        if node == "chat_turn_decision":
            steps["decision_seconds"] = float(event.get("elapsed_ms") or 0) / 1000
        elif node == "chat_prepare":
            steps["prepare_seconds"] = float(event.get("elapsed_ms") or 0) / 1000
        elif name == "llm_route_attempt" and event.get("mode") == "nonstream":
            steps["llm_tool_rounds_seconds"] = steps.get("llm_tool_rounds_seconds", 0) + float(event.get("latency_ms") or 0) / 1000
            steps["llm_tool_rounds"] = steps.get("llm_tool_rounds", 0) + 1
        elif name == "llm_route_attempt" and event.get("mode") == "stream" and event.get("first_token_ms") is not None:
            steps.setdefault("llm_first_token", begin(event) + float(event["first_token_ms"]) / 1000)
            steps.setdefault("llm_model", f"{event.get('provider')}:{event.get('model')}")
        elif name == "chat_complete":
            steps["brain_complete"] = event["ts_ms"] / 1000
    return steps


def resources(path: Path, since: float, until: float, prefixes: list[str]) -> dict:
    rows = []
    for line in path.read_text(encoding="utf-8").splitlines():
        row = json.loads(line)
        if since <= row["t"] <= until:
            rows.append(row)
    result: dict = {"samples": len(rows)}
    host = [row["host_busy_cores"] for row in rows]
    if host:
        result["host_cores"] = {"avg": round(statistics.mean(host), 2), "peak": max(host)}
    host_rows = [row["host"] for row in rows if "host" in row]
    if host_rows:
        result["host"] = {
            key: {"avg": round(statistics.mean(r[key] for r in host_rows), 2), "peak": max(r[key] for r in host_rows)}
            for key in host_rows[0]
        }
    for gpu in sorted({key for row in rows for key in row if key.startswith("gpu")}):
        samples = [row[gpu] for row in rows if gpu in row]
        result[gpu] = {
            "util_pct": {"avg": round(statistics.mean(s[0] for s in samples), 1), "peak": max(s[0] for s in samples)},
            "mem_gib": {"avg": round(statistics.mean(s[1] for s in samples), 2), "peak": max(s[1] for s in samples)},
        }
    names = sorted({key for row in rows for key in row if key not in ("t", "host_busy_cores", "host") and not key.startswith("gpu")})
    for name in names:
        if prefixes and not any(prefix in name for prefix in prefixes):
            continue
        samples = [row[name] for row in rows if name in row]
        cpu = [s[0] for s in samples]
        mem = [s[1] for s in samples]
        entry = {
            "cpu_cores": {"avg": round(statistics.mean(cpu), 2), "peak": max(cpu)},
            "mem_gib": {"avg": round(statistics.mean(mem), 2), "peak": max(mem)},
        }
        if samples and len(samples[0]) >= 4:
            rx = [s[2] for s in samples]
            tx = [s[3] for s in samples]
            entry["rx_mbps"] = {"avg": round(statistics.mean(rx), 2), "peak": max(rx)}
            entry["tx_mbps"] = {"avg": round(statistics.mean(tx), 2), "peak": max(tx)}
        result[name] = entry
    return result


STEPS = [
    ("client_to_brain", "送出 → Brain 開始處理（nginx＋Backend＋轉送）"),
    ("prepare", "Brain 前置（安全檢查、讀 session、決策、組提示詞）"),
    ("decision", "當輪決策（含在前置內）"),
    ("llm_tool_rounds", "LLM 判斷輪（決定查知識庫，非串流）"),
    ("knowledge", "知識庫檢索（embedding＋向量＋關鍵字＋圖譜）"),
    ("llm_first_token_after_send", "送出 → LLM 寫回答的首字"),
    ("first_sentence", "送出 → 前端收到文字第一句"),
    ("tts_send_delay", "第一句 → 送出 TTS 請求"),
    ("tts_first_audio", "TTS 請求 → 收到第一段音訊"),
    ("heard", "送出 → 前端收到第一段音訊（聽到第一句）"),
    ("done", "送出 → 回答完整結束"),
    ("heard_end", "送出 → 整段回答唸完（users_e2e.py 才有）"),
    ("brain_total", "Brain 開始 → Brain 寫完這輪"),
]


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("run")
    parser.add_argument("--brain", required=True, help="Brain chat container name")
    parser.add_argument("--resources")
    parser.add_argument("--containers", default="", help="comma-separated name fragments to report")
    parser.add_argument("--out")
    args = parser.parse_args()

    run = json.loads(Path(args.run).read_text(encoding="utf-8"))
    records = run["records"]
    since, until = run["started"] - 5, run["finished"] + 5
    traces = brain_events(args.brain, since, until)

    values: dict[str, list[float]] = defaultdict(list)
    matched = 0
    for record in records:
        if not record.get("ok"):
            continue
        send = record["send"]
        values["first_sentence"].append(record.get("first_sentence", send) - send if "first_sentence" in record else None)
        values["done"].append(record["done"] - send)
        if "heard_end" in record:
            values["heard_end"].append(record["heard_end"] - send)
        if "tts_first_byte" in record:
            values["heard"].append(record["tts_first_byte"] - send)
            values["tts_first_audio"].append(record["tts_first_byte"] - record["tts_send"])
            values["tts_send_delay"].append(record["tts_send"] - record["first_sentence"])
        events = traces.get(record.get("trace_id", ""))
        if not events:
            continue
        matched += 1
        steps = brain_steps(events)
        values["client_to_brain"].append(steps["brain_start"] - send)
        for key in ("prepare", "decision", "knowledge", "llm_tool_rounds"):
            if f"{key}_seconds" in steps:
                values[key].append(steps[f"{key}_seconds"])
        if "llm_first_token" in steps:
            values["llm_first_token_after_send"].append(steps["llm_first_token"] - send)
        if "brain_complete" in steps:
            values["brain_total"].append(steps["brain_complete"] - steps["brain_start"])

    report = {
        "label": run.get("label"), "base": run["base"], "project": run["project"],
        "count": run["count"], "window": run["window"], "tts_provider": run.get("tts_provider"),
        "started": run["started"], "finished": run["finished"],
        "ok": sum(1 for r in records if r.get("ok")),
        "heard_ok": sum(1 for r in records if "tts_first_byte" in r),
        "tts_providers": sorted({r.get("tts_provider", "") for r in records if r.get("tts_provider")}),
        "errors": [r.get("error") or r.get("tts_error") for r in records if r.get("error") or r.get("tts_error")][:10],
        "brain_traces_matched": matched,
        "steps": {key: {"label": label, **summary(values.get(key, []))} for key, label in STEPS},
    }
    if args.resources:
        prefixes = [p for p in args.containers.split(",") if p]
        report["resources"] = resources(Path(args.resources), run["started"] - 1, run["finished"] + 2, prefixes)
    text = json.dumps(report, ensure_ascii=False, indent=1)
    if args.out:
        Path(args.out).write_text(text, encoding="utf-8")
    print(f"{report['label']}: ok {report['ok']}/{report['count']}, heard {report['heard_ok']}, traces {matched}")
    for key, label in STEPS:
        s = report["steps"][key]
        if s.get("n"):
            print(f"  {label}: {s['median']:.2f} / {s['p95']:.2f} s (n={s['n']})")


if __name__ == "__main__":
    main()
