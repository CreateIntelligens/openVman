"""Reproducible offline baselines; execute all file I/O in experiment container."""

import asyncio
import hashlib
import importlib.util
import json
import math
from pathlib import Path
import statistics
import sys
import time

ROOT = Path(__file__).resolve().parent
PROTOTYPES = {
    "chat": ["嗨，祝你有美好的一天！", "真開心可以和你分享生活中的小事。", "多謝你的協助，再見。"],
    "knowledge": ["依公司內部規章，新進員工如何申請門禁卡？", "請查本專案技術文件中的部署架構。", "本中心的到宅服務需要準備哪些申請文件？"],
    "web": ["請搜尋今日國際股市最新消息。", "請開啟 https://example.org/ 並摘要該網頁。", "請查交通部網站目前公布的最新交通管制資訊。"],
    "clarify": ["請處理那個東西。", "他現在怎樣了？", "我要問一下這件事。"],
}


def metrics(rows, labels):
    confusion = {gold: {pred: 0 for pred in labels} for gold in labels}
    for row in rows:
        confusion[row["expected"]][row["predicted"]] += 1
    values = sorted(row["latency_ms"] for row in rows)
    return {
        "count": len(rows),
        "correct": sum(row["expected"] == row["predicted"] for row in rows),
        "accuracy": sum(row["expected"] == row["predicted"] for row in rows) / len(rows),
        "confusion_rows_gold_columns_predicted": confusion,
        "latency_ms": {"mean": statistics.mean(values), "median": statistics.median(values), "p95_nearest_rank": values[math.ceil(len(values) * .95) - 1]},
        "rows": rows,
    }


async def prepare():
    raw = (ROOT / "cases.jsonl").read_bytes()
    cases = [json.loads(line) for line in raw.decode().splitlines()]
    path = ROOT.parents[2] / "backend/app/guard_agent.py"
    spec = importlib.util.spec_from_file_location("baseline_guard", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    guard = module.GuardAgent()
    rows = []
    for case in cases:
        if case["task"] != "interrupt":
            continue
        start = time.perf_counter()
        predicted = await guard.classify(case["state"])
        elapsed = (time.perf_counter() - start) * 1000
        rows.append({"id": case["id"], "expected": case["expected"], "predicted": predicted, "latency_ms": elapsed})
    assert len(rows) == 16
    return {
        "fixture_sha256": hashlib.sha256(raw).hexdigest(),
        "guard_source_sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
        "guard": {**metrics(rows, ["STOP", "IGNORE"]), "latency_scope": "single awaited classify call; excludes import and initialization"},
        "prototypes": PROTOTYPES,
        "routing_cases": [case for case in cases if case["task"] == "routing"],
    }


# Sent as source to the existing API container; its credentials never leave it.
RUNNER = r'''
import json
import math
import os
import sys
import time
import urllib.request
from datetime import datetime, timezone

payload = json.load(sys.stdin)
base = os.environ["EMBEDDING_SERVICE_URL"].rstrip("/")
token = os.environ["EMBEDDING_SERVICE_TOKEN"]
identity = None

def embed(texts):
    body = {"texts": texts, "input_type": "symmetric"}
    if identity:
        body["identity"] = identity
    request = urllib.request.Request(base + "/embed", data=json.dumps(body).encode(), headers={"Content-Type": "application/json", "Authorization": "Bearer " + token})
    started = time.perf_counter()
    with urllib.request.urlopen(request, timeout=120) as response:
        data = json.load(response)
    elapsed = (time.perf_counter() - started) * 1000
    if len(data["vectors"]) != len(texts):
        raise ValueError("Embedding vector count mismatch")
    return data, elapsed

def normalize(vector):
    norm = math.sqrt(sum(value * value for value in vector))
    if not norm:
        raise ValueError("Zero embedding vector")
    return [value / norm for value in vector]

def serialize(state):
    return json.dumps(state, ensure_ascii=False, separators=(",", ":"))

labels = list(payload["prototypes"])
texts = [serialize({"history": [], "message": text}) for label in labels for text in payload["prototypes"][label]]
data, warmup_ms = embed(texts)
identity = data["embedding_spec"]["identity"]
centroids = {}
for index, label in enumerate(labels):
    vectors = data["vectors"][index * 3:(index + 1) * 3]
    centroids[label] = normalize([sum(column) / len(vectors) for column in zip(*vectors)])
rows = []
for case in payload.pop("routing_cases"):
    data_case, elapsed = embed([serialize(case["state"])])
    if data_case["embedding_spec"]["identity"] != identity:
        raise ValueError("Embedding identity drift")
    vector = normalize(data_case["vectors"][0])
    if any(len(centroid) != len(vector) for centroid in centroids.values()):
        raise ValueError("Embedding dimension mismatch")
    scores = {label: sum(a * b for a, b in zip(vector, centroid)) for label, centroid in centroids.items()}
    rows.append({"id": case["id"], "expected": case["expected"], "predicted": max(scores, key=scores.get), "scores": scores, "latency_ms": elapsed})
payload["embedding"] = {
    "rows": rows,
    "embedding_spec": data["embedding_spec"],
    "prototype_batch_latency_ms": warmup_ms,
    "prototype_batch_count": len(texts),
    "latency_scope": "32 sequential individual HTTP requests; includes request, network, server, JSON decode; excludes centroid scoring; 12-prototype batch timed separately",
    "method": "mean of 3 independent prototype vectors per class, normalized centroid, cosine nearest centroid; input JSON includes history and message; symmetric embedding identity locked after prototypes",
}
payload["recorded_at_utc"] = datetime.now(timezone.utc).isoformat()
print(json.dumps(payload, ensure_ascii=False))
'''


def main():
    mode = sys.argv[1]
    if mode == "prepare":
        print(json.dumps(asyncio.run(prepare()), ensure_ascii=False))
    elif mode == "runner-source":
        print(RUNNER)
    elif mode == "finish":
        result = json.load(sys.stdin)
        embedding = result["embedding"]
        embedding.update(metrics(embedding["rows"], list(PROTOTYPES)))
        assert embedding["count"] == 32
        output = ROOT / "results/baselines.json"
        output.parent.mkdir(exist_ok=True)
        output.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        print(json.dumps({name: {key: result[name][key] for key in ["count", "correct", "accuracy", "latency_ms", "confusion_rows_gold_columns_predicted"]} for name in ["guard", "embedding"]}, ensure_ascii=False, indent=2))
    else:
        raise SystemExit("Use prepare, runner-source, or finish")


if __name__ == "__main__":
    main()
