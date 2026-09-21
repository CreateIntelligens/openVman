"""Repeat and permute frozen SemIf routing inputs without tuning prompts."""

import argparse
from collections import Counter, defaultdict
import hashlib
import itertools
from importlib.metadata import version
import json
import math
from pathlib import Path
import random
import statistics
import sys
import time
import urllib.request

from run import MODEL, OPTIONS, QUESTIONS, REVISION, ROOT, UPSTREAM, write_json

REPEATS = 3
SEED = 20260920
SOURCE_HASHES = {
    "core.py": "c33dc41a789c39c095c85c1d23d09690dee3726d737bc3dbd051a4f97115e486",
    "direct.py": "2c89209787b1b51e5f8f8062b4f602da4c82ba7efad50a4df0863b04aef70c9f",
}


def summarize(rows: list[dict], metadata: dict) -> dict:
    groups = defaultdict(list)
    by_case = defaultdict(list)
    by_order = defaultdict(list)
    for row in rows:
        groups[(row["id"], row["order_index"])].append(row)
        by_case[row["id"]].append(row)
        by_order[row["order_index"]].append(row)
    assert len(rows) == metadata["planned_predictions"]
    assert len(groups) == 32 * 24
    assert all(len(group) == REPEATS for group in groups.values())
    assert all(len({row["prompt_sha256"] for row in group}) == 1
               for group in groups.values())
    repeat_flips = []
    probability_delta = 0.0
    logit_delta = 0.0
    for (case_id, order_index), group in sorted(groups.items()):
        predictions = [row["predicted"] for row in group]
        if len(set(predictions)) > 1:
            repeat_flips.append({
                "id": case_id, "order_index": order_index,
                "predictions": predictions,
            })
        for key in ("probabilities", "option_logits"):
            delta = max(
                max(values) - min(values)
                for values in zip(*(row[key] for row in group))
            )
            if key == "probabilities":
                probability_delta = max(probability_delta, delta)
            else:
                logit_delta = max(logit_delta, delta)
    case_results = []
    for case_id, group in sorted(by_case.items()):
        first = [row for row in group if row["repeat"] == 0]
        counts = Counter(row["predicted"] for row in first)
        case_results.append({
            "id": case_id, "expected": group[0]["expected"],
            "first_repeat_label_counts": dict(counts),
            "distinct_labels_across_orders": len(counts),
            "correct_orders": sum(row["predicted"] == row["expected"]
                                  for row in first),
        })
    orders = []
    for order_index, group in sorted(by_order.items()):
        first = [row for row in group if row["repeat"] == 0]
        orders.append({
            "order_index": order_index, "option_ids": first[0]["option_ids"],
            "first_repeat_correct": sum(row["predicted"] == row["expected"]
                                        for row in first),
            "all_repeats_correct": sum(row["predicted"] == row["expected"]
                                       for row in group),
        })
    times = sorted(row["total_seconds"] * 1000 for row in rows)
    correct = sum(row["predicted"] == row["expected"] for row in rows)
    return {
        "metadata": metadata,
        "count": len(rows), "correct": correct,
        "accuracy": correct / len(rows),
        "identical_input_groups": len(groups),
        "repeat_flip_groups": repeat_flips,
        "max_repeat_probability_delta": probability_delta,
        "max_repeat_logit_delta": logit_delta,
        "order_sensitive_cases": sum(
            row["distinct_labels_across_orders"] > 1 for row in case_results
        ),
        "always_correct_cases": sum(
            row["correct_orders"] == 24 for row in case_results
        ),
        "first_repeat_worst_order_correct": min(
            row["first_repeat_correct"] for row in orders
        ),
        "first_repeat_best_order_correct": max(
            row["first_repeat_correct"] for row in orders
        ),
        "winner_positions": dict(Counter(
            row["winner_position"] for row in rows
        )),
        "tied_top_scores": sum(row["top_tied"] for row in rows),
        "p50_ms": statistics.median(times),
        "p95_ms": times[math.ceil(len(times) * .95) - 1],
        "cases": case_results, "orders": orders,
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--summarize-only", action="store_true")
    args = parser.parse_args()
    output = ROOT / "results" / "stability"
    if args.summarize_only:
        rows = [json.loads(line) for line in
                (output / "predictions.jsonl").read_text().splitlines()]
        metadata = json.loads((output / "metadata.json").read_text())
        write_json(output / "summary.json", summarize(rows, metadata))
        return
    output.mkdir(parents=True, exist_ok=True)
    if (output / "predictions.jsonl").exists():
        raise RuntimeError("Existing predictions must not be overwritten")
    package = Path("/tmp/semif-upstream/semif_phase1")
    package.mkdir(parents=True, exist_ok=True)
    (package / "__init__.py").write_text("")
    for name, expected in SOURCE_HASHES.items():
        url = (
            f"https://raw.githubusercontent.com/TheoLeeCJ/SemIf/{UPSTREAM}"
            f"/src/semif_phase1/{name}"
        )
        data = urllib.request.urlopen(url, timeout=60).read()
        if hashlib.sha256(data).hexdigest() != expected:
            raise RuntimeError("Upstream source hash mismatch")
        (package / name).write_bytes(data)
    sys.path.insert(0, str(package.parent))
    from semif_phase1.direct import score
    import torch
    import transformers
    from transformers import (
        AutoConfig,
        AutoTokenizer,
        BitsAndBytesConfig,
        Qwen3_5ForCausalLM,
    )

    torch.set_num_threads(2)
    torch.manual_seed(SEED)
    cases_path = ROOT / "cases.jsonl"
    cases = [json.loads(line) for line in cases_path.read_text().splitlines()]
    cases = [row for row in cases if row["task"] == "routing"]
    assert len(cases) == len({row["id"] for row in cases}) == 32
    orders = list(itertools.permutations(OPTIONS["routing"]))
    rng = random.Random(SEED)
    schedule = []
    for repeat in range(REPEATS):
        jobs = [(repeat, index, case) for index in range(len(orders))
                for case in cases]
        rng.shuffle(jobs)
        schedule.extend(jobs)
    metadata = {
        "model": MODEL, "revision": REVISION, "upstream_commit": UPSTREAM,
        "upstream_sha256": SOURCE_HASHES,
        "fixture_sha256": hashlib.sha256(cases_path.read_bytes()).hexdigest(),
        "runner_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
        "run_module_sha256": hashlib.sha256((ROOT / "run.py").read_bytes()).hexdigest(),
        "bitsandbytes": version("bitsandbytes"),
        "torch": torch.__version__, "transformers": transformers.__version__,
        "quantization": "bitsandbytes NF4 double quant, BF16 compute",
        "gpu": torch.cuda.get_device_name(),
        "question": QUESTIONS["routing"], "options": OPTIONS["routing"],
        "repeats": REPEATS, "seed": SEED,
        "planned_predictions": len(schedule),
        "schedule": [[repeat, index, case["id"]]
                     for repeat, index, case in schedule],
        "note": (
            "Initial frozen prompt; one model load; fresh direct scoring. "
            "Seed shuffles job order; no answer sampling. Development fixture, "
            "not independent traffic. Do not select the best permutation."
        ),
    }
    free, _ = torch.cuda.mem_get_info()
    metadata["free_vram_before_load_gib"] = free / 2**30
    if free < 4 * 2**30:
        raise RuntimeError("Less than 4 GiB free; refusing model load")
    write_json(output / "metadata.json", metadata)
    print("Frozen schedule:", len(schedule), "predictions", flush=True)
    config = AutoConfig.from_pretrained(MODEL, revision=REVISION).get_text_config()
    tokenizer = AutoTokenizer.from_pretrained(MODEL, revision=REVISION)
    started = time.perf_counter()
    model, loading = Qwen3_5ForCausalLM.from_pretrained(
        MODEL, config=config, revision=REVISION, dtype=torch.bfloat16,
        device_map={"": "cuda"}, output_loading_info=True,
        quantization_config=BitsAndBytesConfig(
            load_in_4bit=True, bnb_4bit_quant_type="nf4",
            bnb_4bit_compute_dtype=torch.bfloat16,
            bnb_4bit_use_double_quant=True,
        ),
    )
    if any(loading.get(key) for key in
           ("missing_keys", "mismatched_keys", "error_msgs", "unexpected_keys")):
        raise RuntimeError(str(loading))
    model.eval()
    metadata["load_seconds"] = time.perf_counter() - started
    torch.cuda.reset_peak_memory_stats()
    score(model, tokenizer, {
        "id": "warmup", "state": cases[0]["state"],
        "question": QUESTIONS["routing"], "options": OPTIONS["routing"],
    }, {})
    results = []
    with (output / "predictions.jsonl").open("x") as handle:
        for repeat, order_index, case in schedule:
            options = list(orders[order_index])
            result = score(model, tokenizer, {
                "id": case["id"], "state": case["state"],
                "question": QUESTIONS["routing"], "options": options,
            }, {})
            probabilities = result["probabilities"]
            assert len(probabilities) == len(options)
            assert all(math.isfinite(value) and 0 <= value <= 1
                       for value in probabilities)
            assert math.isclose(sum(probabilities), 1, abs_tol=1e-6)
            winner = max(range(len(options)), key=probabilities.__getitem__)
            result.update(
                execution_index=len(results),
                repeat=repeat, order_index=order_index,
                expected=case["expected"], predicted=options[winner]["id"],
                winner_position=winner,
                margin=sorted(probabilities, reverse=True)[0]
                - sorted(probabilities, reverse=True)[1],
                top_tied=probabilities.count(probabilities[winner]) > 1,
            )
            results.append(result)
            handle.write(json.dumps(result, ensure_ascii=False) + "\n")
            handle.flush()
            if len(results) % 64 == 0:
                print(f"Progress {len(results)}/{len(schedule)}", flush=True)
    metadata["peak_allocated_gib"] = torch.cuda.max_memory_allocated() / 2**30
    metadata["peak_reserved_gib"] = torch.cuda.max_memory_reserved() / 2**30
    write_json(output / "metadata.json", metadata)
    summary = summarize(results, metadata)
    write_json(output / "summary.json", summary)
    print(json.dumps({key: value for key, value in summary.items()
                      if key not in {"metadata", "cases", "orders"}},
                     ensure_ascii=False, indent=2), flush=True)


if __name__ == "__main__":
    main()
