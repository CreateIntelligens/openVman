"""Verify completed QA evidence and summarize acceptance without hiding failures."""

import argparse
from collections import defaultdict
import copy
import hashlib
import json
from pathlib import Path

from experiment_io import validate_output


LIVE_BATCHES = {
    "hospital_live": (128, "hospital_live_eval_v2"),
    "heji_live": (128, "heji_live_eval_v2"),
    "boundary_live": (44, "boundary_live_eval_v2"),
    "chain_live": (24, "chain_live_eval_v2"),
    "chain_confirmation_live": (6, "chain_confirmation_eval"),
    "heji_confirmation_live": (12, "heji_confirmation_eval"),
    "boundary_confirmation_live": (6, "boundary_confirmation_eval"),
    "hospital_confirmation_live": (24, "hospital_confirmation_eval"),
    "heji_specs_confirmation_live": (18, "heji_specs_confirmation_eval"),
}
OFFLINE_BATCHES = {
    "hospital_offline": 384, "heji_offline": 384,
    "boundary_offline": 44, "heji_confirmation_offline": 9,
}


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def unique_keys(rows):
    keys = {(r["id"], r["rep"], r["variant"]) for r in rows}
    if len(keys) != len(rows):
        raise ValueError("Duplicate answer keys")
    return keys


def metrics(rows):
    groups = defaultdict(lambda: {"count": 0, "passed": 0, "critical": 0,
                                  "execution_errors": 0, "judge_errors": 0})
    for row in rows:
        group = groups[row["variant"]]
        group["count"] += 1
        group["passed"] += bool(row["pass"])
        group["critical"] += bool(row["critical"])
        group["execution_errors"] += "execution_error" in row
        group["judge_errors"] += "judge_error" in row
    return dict(groups)


def reviewed_rows(rows, review, raw_path):
    if digest(raw_path) != review["raw_results_sha256"]:
        raise ValueError("Manual review does not match raw evidence")
    adjusted = copy.deepcopy(rows)
    lookup = {(r["id"], r["rep"], r["variant"]): r for r in adjusted}
    for change in review["overrides"]:
        row = lookup[(change["id"], change["rep"], change["variant"])]
        if row["pass"] != change["old_pass"] or row["critical"] != change["old_critical"]:
            raise ValueError("Override old values differ from raw judgment")
        row.update({"pass": change["new_pass"], "critical": change["new_critical"]})
    return adjusted


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    required = [args.root / f"{name}.json" for name in (
        list(LIVE_BATCHES) + [grade for _, grade in LIVE_BATCHES.values()]
        + list(OFFLINE_BATCHES)
        + ["hospital_review", "heji_review", "live_manual_review", "heji_visibility"]
    )]
    required.append(args.root / "compile/REVIEW.json")
    output = validate_output(args.output, inputs=required)
    missing = [str(p) for p in required if not p.is_file()]
    if missing:
        raise SystemExit(f"Incomplete evidence: {missing}")
    summary = {"offline": {}, "live": {},
               "evidence_sha256": {p.name: digest(p) for p in required}}
    live_review = json.loads((args.root / "live_manual_review.json").read_text())
    for filename, expected in live_review["input_sha256"].items():
        if digest(args.root / filename) != expected:
            raise ValueError("Live manual review input changed")
    for name, expected in OFFLINE_BATCHES.items():
        path = args.root / f"{name}.json"
        rows = json.loads(path.read_text())
        unique_keys(rows)
        if len(rows) != expected:
            raise ValueError(f"Missing offline answers: {name}")
        result = {"raw": metrics(rows)}
        domain = name.removesuffix("_offline")
        if domain in ("hospital", "heji"):
            review = json.loads((args.root / f"{domain}_review.json").read_text())
            result["reviewed"] = metrics(reviewed_rows(rows, review, path))
            result["review_scope"] = review["review_scope"]
        summary["offline"][name] = result
    for name, (expected, graded_name) in LIVE_BATCHES.items():
        data = json.loads((args.root / f"{name}.json").read_text())
        rows = json.loads((args.root / f"{graded_name}.json").read_text())
        if len(data["records"]) != expected or unique_keys(rows) != unique_keys(data["records"]):
            raise ValueError(f"Missing live answers or judgments: {name}")
        if not data["config_unchanged"] or data["readonly_check"]["changed_paths"]:
            raise ValueError("Project state changed")
        corrected = copy.deepcopy(rows)
        lookup = {(r["id"], r["rep"], r["variant"]): r for r in corrected}
        domain = name.removesuffix("_live")
        if domain in ("hospital", "heji"):
            for change in live_review["critical_reviews"]:
                if change["domain"] == domain:
                    lookup[(change["id"], change["rep"], change["variant"])].update(
                        change["overrides"]
                    )
        summary["live"][name] = {
            "raw": metrics(rows), "reviewed": metrics(corrected),
            "execution_error_count": len(data["errors"]),
            "readonly_check": data["readonly_check"],
            "models": sorted({m for r in data["records"] for m in r["models"]}),
        }
    summary["live_answer_count"] = sum(count for count, _ in LIVE_BATCHES.values())
    summary["offline_answer_count"] = sum(OFFLINE_BATCHES.values())
    summary["live_execution_errors"] = sum(
        r["execution_error_count"] for r in summary["live"].values()
    )
    summary["visibility"] = json.loads((args.root / "heji_visibility.json").read_text())["variants"]
    reasons = []
    if summary["visibility"]["mixed_multi"]["disabled_chunks"]:
        reasons.append("Disabled document references in raw-vector candidate.")
    if summary["live"]["chain_confirmation_live"]["reviewed"]["mixed_multi"]["critical"]:
        reasons.append("Compiled poison repeated as a fact by production agent.")
    if any(r["critical"] for name in ("hospital_live", "heji_live")
           for r in summary["live"][name]["reviewed"].values()):
        reasons.append("Safety-relevant number/condition/source errors under production prompts.")
    compile_review = json.loads((args.root / "compile/REVIEW.json").read_text())
    if any(r["class"] in ("stale_deleted_page", "mixed_source_and_stale_wiki")
           for r in compile_review["high_risk_confirmed"]):
        reasons.append("Stale artifacts and non-atomic compilation on source changes.")
    boundary = summary["live"]["boundary_confirmation_live"]["reviewed"]
    if any(r["passed"] != r["count"] for r in boundary.values()):
        reasons.append("Long previous-query truncation and recurrent empty model replies.")
    summary["acceptance_reasons"] = reasons
    summary["acceptance"] = "NO_GO" if reasons else "NOT_CERTIFIED"
    summary["scope_limit"] = (
        "Production prompt/agent/provider tested with injected retrieval snapshots; "
        "not HTTP, decision classification, project-key isolation, media, voice or UI E2E. "
        "Manual review covers failures/critical and stated samples, not every passed answer."
    )
    output.write_text(json.dumps(summary, ensure_ascii=False, indent=1))
    print(json.dumps({k: summary[k] for k in (
        "acceptance", "live_answer_count", "offline_answer_count", "live_execution_errors",
    )}))


if __name__ == "__main__":
    main()
