"""Compare three paired rounds without changing original grades or inputs.

Question gains are operational thresholds, never p-values or significance
claims. Latency uses candidate-minus-main first-text times with nearest-rank
p90. Execution failures cannot supply a usable timing, even if they contain a
number; an incorrect but successfully generated answer can supply a timing.
"""

import argparse
import hashlib
import json
import math
from pathlib import Path
import statistics

from experiment_io import validate_output


def _index(records, label):
    if not isinstance(records, list) or not records:
        raise ValueError(label + " must be a nonempty record list")
    indexed = {}
    for row in records:
        if not isinstance(row, dict):
            raise ValueError(label + " record must be an object")
        case_id, rep, variant = (row.get(k) for k in ("id", "rep", "variant"))
        if (not isinstance(case_id, str) or not case_id.strip()
                or type(rep) is not int or rep not in range(3)
                or not isinstance(variant, str) or not variant.strip()):
            raise ValueError(label + " has an invalid id/rep/variant")
        key = case_id, rep, variant
        if key in indexed:
            raise ValueError(label + " has a duplicate key: " + repr(key))
        if not isinstance(row.get("answer"), str):
            raise ValueError(label + " answer must be a string")
        indexed[key] = row
    return indexed


def _error_kinds(row, grade):
    kinds = []
    if row.get("error") or grade.get("execution_error"):
        kinds.append("execution")
    if not row["answer"].strip():
        kinds.append("empty_answer")
    for field in ("judge_error", "source_validation_error"):
        if grade.get(field):
            kinds.append(field)
    return kinds


def _first_text(row):
    if row.get("error") or not row["answer"].strip():
        return None
    latency = row.get("latency")
    value = latency.get("first_text_ms") if isinstance(latency, dict) else None
    if (isinstance(value, bool) or not isinstance(value, (int, float))
            or not math.isfinite(value) or value < 0):
        return None
    return value


def _latency_pairs(variant, keys, records, grades, limit):
    pairs, missing = [], []
    for case_id, rep in keys:
        baseline_key, candidate_key = (
            (case_id, rep, "main"), (case_id, rep, variant)
        )
        baseline, candidate = records[baseline_key], records[candidate_key]
        times = []
        for key, row in ((baseline_key, baseline), (candidate_key, candidate)):
            # Judge failures do not erase real generated-response timings.
            value = None if grades[key].get("execution_error") else _first_text(row)
            times.append(value)
        base_ms, candidate_ms = times
        pair = {"id": case_id, "rep": rep}
        if base_ms is None or candidate_ms is None:
            missing.append({**pair, "main_first_text_ms": base_ms,
                            "candidate_first_text_ms": candidate_ms})
        else:
            pairs.append({**pair, "main_first_text_ms": base_ms,
                          "candidate_first_text_ms": candidate_ms,
                          "added_ms": candidate_ms - base_ms})
    values = sorted(pair["added_ms"] for pair in pairs)
    exceeded = [pair for pair in pairs if pair["added_ms"] > limit]
    return {
        "expected_pairs": len(keys), "measured_pairs": len(pairs),
        "missing_pairs": missing, "pairs": pairs,
        "median_added_ms": statistics.median(values) if values else None,
        "p90_added_ms": values[math.ceil(.9 * len(values)) - 1] if values else None,
        "max_added_ms": max(values) if values else None,
        "p90_method": "nearest_rank", "over_limit_pairs": exceeded,
        "complete": not missing,
        "gate": bool(values) and not missing and not exceeded,
    }


def compare_records(live, judged, *, rounds=3, threshold_questions=2,
                    max_added_latency_ms=200):
    """Return original-grade counts, paired regressions and strict gates.

    Accept a live envelope with ``records`` or a record list. Every arm must
    contain the same questions with reps 0, 1, 2; judged keys and answer strings
    must exactly match live. Invalid/inconsistent inputs raise ValueError.
    """
    if type(rounds) is not int or rounds != 3:
        raise ValueError("Follow-up comparisons require exactly three rounds")
    if type(threshold_questions) is not int or threshold_questions < 0:
        raise ValueError("threshold_questions must be a nonnegative integer")
    if (isinstance(max_added_latency_ms, bool)
            or not isinstance(max_added_latency_ms, (int, float))
            or not math.isfinite(max_added_latency_ms)
            or max_added_latency_ms < 0):
        raise ValueError("max_added_latency_ms must be finite and nonnegative")
    envelope = live if isinstance(live, dict) else {}
    records = _index(envelope.get("records") if envelope else live, "live")
    grades = _index(judged, "judged")
    if records.keys() != grades.keys():
        raise ValueError("Live and judged keys must match exactly")
    variants = {key[2] for key in records}
    if "main" not in variants:
        raise ValueError("The main control is required")
    declared = envelope.get("arms")
    if declared is not None and (
        not isinstance(declared, dict) or set(declared) != variants
        or declared.get("main") != {}
    ):
        raise ValueError("Declared arms must match and main controls must be empty")
    main_keys = {(case_id, rep) for case_id, rep, arm in records if arm == "main"}
    case_ids = sorted({case_id for case_id, _ in main_keys})
    expected = {(case_id, rep) for case_id in case_ids for rep in range(rounds)}
    if main_keys != expected:
        raise ValueError("Every main question must have reps 0, 1, 2")
    for variant in variants:
        keys = {(cid, rep) for cid, rep, arm in records if arm == variant}
        if keys != expected:
            raise ValueError("Arm keys differ from main: " + variant)
    for key, row in records.items():
        grade = grades[key]
        if row["answer"] != grade["answer"]:
            raise ValueError("Live/judged answer mismatch: " + repr(key))
        if type(grade.get("pass")) is not bool or type(grade.get("critical")) is not bool:
            raise ValueError("Original pass and critical must be booleans")
        if grade["pass"] and (_error_kinds(row, grade) or grade["critical"]):
            raise ValueError("A passing original grade conflicts with failure: " + repr(key))

    ordered_keys = sorted(expected)
    stable_main = {
        cid for cid in case_ids
        if all(grades[cid, rep, "main"]["pass"] for rep in range(rounds))
    }
    main_round_passes = [
        sum(grades[cid, rep, "main"]["pass"] for cid in case_ids)
        for rep in range(rounds)
    ]
    arms = {}
    for variant in ["main", *sorted(variants - {"main"})]:
        arm_grades = [grades[cid, rep, variant] for cid, rep in ordered_keys]
        errors = {kind: 0 for kind in (
            "execution", "empty_answer", "judge_error", "source_validation_error"
        )}
        error_pairs, regressions, stable_regressions, per_round = [], [], [], []
        for cid, rep in ordered_keys:
            grade = grades[cid, rep, variant]
            kinds = _error_kinds(records[cid, rep, variant], grade)
            if kinds:
                error_pairs.append({"id": cid, "rep": rep, "kinds": kinds})
                for kind in kinds:
                    errors[kind] += 1
            if grades[cid, rep, "main"]["pass"] and not grade["pass"]:
                regressions.append({"id": cid, "rep": rep})
        for cid in sorted(stable_main):
            failing = [rep for rep in range(rounds)
                       if not grades[cid, rep, variant]["pass"]]
            if len(failing) >= 2:
                stable_regressions.append({"id": cid, "failing_reps": failing})
        for rep in range(rounds):
            rows = [grades[cid, rep, variant] for cid in case_ids]
            passed = sum(row["pass"] for row in rows)
            per_round.append({
                "rep": rep, "denominator": len(case_ids), "pass": passed,
                "critical": sum(row["critical"] for row in rows),
                "errors": sum(pair["rep"] == rep for pair in error_pairs),
                "delta_pass_vs_main": passed - main_round_passes[rep],
            })
        delta = sum(row["delta_pass_vs_main"] for row in per_round)
        critical = sum(row["critical"] for row in arm_grades)
        latency = _latency_pairs(variant, ordered_keys, records, grades,
                                 max_added_latency_ms)
        gates = {
            "no_regression": not stable_regressions,
            "no_critical": critical == 0,
            "latency": latency["gate"],
            "gain": delta / rounds > threshold_questions,
        }
        arms[variant] = {
            "denominator": len(expected),
            "pass": sum(row["pass"] for row in arm_grades),
            "failed": sum(not row["pass"] for row in arm_grades),
            "critical": critical, "errors": len(error_pairs),
            "error_counts": errors, "error_pairs": error_pairs,
            "per_round": per_round,
            "delta_vs_main": {
                "per_round_questions": [row["delta_pass_vs_main"] for row in per_round],
                "total_passes": delta, "average_questions_per_round": delta / rounds,
                "operational_small": abs(delta) <= threshold_questions * rounds,
            },
            "main_pass_candidate_fail_pairs": regressions,
            "main_three_of_three_pass_candidate_fail_questions": stable_regressions,
            "paired_first_text_latency": latency, "gates": gates,
            "all_core_gates_pass": all(gates.values()) if variant != "main" else None,
            "is_control": variant == "main",
        }
    return {
        "baseline": "main", "rounds": rounds, "question_count": len(case_ids),
        "case_ids": case_ids, "pairs_per_arm": len(expected),
        "operational_threshold_questions": threshold_questions,
        "max_added_latency_ms": max_added_latency_ms,
        "statistical_interpretation": {
            "not_a_p_value": True, "statistical_significance_claimed": False,
            "note": "Absolute average gain <= threshold is operational-small; no significance test was run.",
        },
        "regression_policy": "Main passes all three; candidate fails at least two of three. Pair failures alone are diagnostic.",
        "grade_policy": "Original pass/critical unchanged; inconsistent passing error rows are rejected.",
        "latency_policy": "All paired timings required; execution failures are missing, not fast responses. Maximum added latency must be <= limit.",
        "arms": arms,
    }


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--live", type=Path, required=True)
    parser.add_argument("--judged", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args(argv)
    try:
        sources = [args.live.resolve(), args.judged.resolve()]
        target = validate_output(args.output, inputs=sources)
        if target.exists():
            raise ValueError("Output already exists; refusing to overwrite")
        data = [path.read_bytes() for path in sources]
        result = compare_records(*(json.loads(raw) for raw in data))
        hashes = {str(path): hashlib.sha256(raw).hexdigest()
                  for path, raw in zip(sources, data)}
        if any(hashlib.sha256(path.read_bytes()).hexdigest() != hashes[str(path)]
               for path in sources):
            raise ValueError("Source inputs changed during analysis")
        result["input_sha256"] = hashes
        # Exclusive creation also protects against a racing writer after validation.
        with target.open("x", encoding="utf-8") as stream:
            json.dump(result, stream, ensure_ascii=False, indent=2, allow_nan=False)
            stream.write("\n")
    except (OSError, TypeError, ValueError) as exc:
        parser.error(str(exc))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
