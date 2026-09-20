"""Evaluate the frozen fixture using the installed gateway; stdout is JSON."""

import argparse
from collections import Counter
import hashlib
import importlib.util
import json
import math
from pathlib import Path
import statistics
import time

from config import get_settings

parser = argparse.ArgumentParser()
parser.add_argument("--module", type=Path, required=True)
args = parser.parse_args()
root = Path(__file__).resolve().parent
raw = (root / "cases.jsonl").read_bytes()
cases = [json.loads(line) for line in raw.decode().splitlines()]
assert len(cases) == len({case["id"] for case in cases}) == 64
assert Counter(case["expected"] for case in cases) == dict.fromkeys(
    ("chat", "knowledge", "web", "clarify"), 16,
)
spec = importlib.util.spec_from_file_location("evaluated_intent_shadow", args.module)
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)
cfg = get_settings().model_copy(update={"intent_shadow_timeout_seconds": .5})
classifier = module.EmbeddingIntentClassifier(cfg)
rows = []
try:
    start = time.monotonic()
    classifier.classify("暖機用問候", [])
    warmup_ms = (time.monotonic() - start) * 1000
    for case in cases:
        start = time.monotonic()
        try:
            result = classifier.classify(case["state"]["message"], case["state"]["history"])
            rows.append({"id": case["id"], "expected": case["expected"], **result,
                         "elapsed_ms": (time.monotonic() - start) * 1000})
        except Exception as exc:
            rows.append({"id": case["id"], "expected": case["expected"],
                         "suggestion": "error", "error_type": type(exc).__name__,
                         "elapsed_ms": (time.monotonic() - start) * 1000})
finally:
    classifier.close()
labels = list(module.PROTOTYPES)
confusion = {gold: {prediction: 0 for prediction in [*labels, "error"]} for gold in labels}
for row in rows:
    confusion[row["expected"]][row["suggestion"]] += 1
latencies = sorted(row["elapsed_ms"] for row in rows)
correct = sum(row["expected"] == row["suggestion"] for row in rows)
print(json.dumps({
    "fixture_sha256": hashlib.sha256(raw).hexdigest(),
    "classifier_sha256": hashlib.sha256(args.module.read_bytes()).hexdigest(),
    "prototype_version": module.PROTOTYPE_VERSION,
    "prototype_sha256": hashlib.sha256(json.dumps(module.PROTOTYPES, ensure_ascii=False, sort_keys=True).encode()).hexdigest(),
    "count": len(rows), "correct": correct, "accuracy": correct / len(rows),
    "confusion": confusion, "warmup_ms": warmup_ms,
    "p50_ms": statistics.median(latencies),
    "p95_ms": latencies[math.ceil(len(rows) * .95) - 1],
    "knowledge_to_chat": confusion["knowledge"]["chat"],
    "errors": sum(row["suggestion"] == "error" for row in rows),
    "note": "Independent synthetic phrases, not production traffic or calibrated confidence; no prototype tuning after evaluation.",
    "rows": rows,
}, ensure_ascii=False, indent=2))
