"""Fail QA acceptance when raw-vector research returns disabled documents."""

import argparse
import hashlib
import json
from pathlib import Path

from experiment_io import validate_output


def audit(data, disabled_paths):
    disabled = set(disabled_paths)
    findings = []
    counts = {}
    for case_id, variants in data["questions"].items():
        for variant, evidence in variants.items():
            count = counts.setdefault(variant, {
                "cases": 0, "affected_cases": 0, "disabled_chunks": 0,
            })
            count["cases"] += 1
            hits = [
                {"id": case_id, "variant": variant, "path": row["path"],
                 "src": row.get("src", "original")}
                for row in evidence["results"] + evidence["related"]
                if row.get("path") in disabled
            ]
            count["affected_cases"] += bool(hits)
            count["disabled_chunks"] += len(hits)
            findings.extend(hits)
    return {
        "gate": "No disabled source may enter reference context",
        "disabled_paths": sorted(disabled), "variants": counts,
        "findings": findings,
        "passed": not findings,
        "limitations": [
            "Uses captured project disabled paths, not a claim about earlier state.",
            "Derived wiki chunks lack source dependency metadata; this audit cannot certify them.",
        ],
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--retrieval", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--disabled", nargs="*")
    args = parser.parse_args()
    output = validate_output(args.output, inputs=[args.retrieval])
    data = json.loads(args.retrieval.read_text())
    disabled = args.disabled if args.disabled is not None else data.get("disabled_paths")
    if disabled is None:
        parser.error("Need captured disabled_paths or explicit --disabled")
    report = audit(data, disabled)
    report["retrieval_sha256"] = hashlib.sha256(args.retrieval.read_bytes()).hexdigest()
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(report, ensure_ascii=False, indent=1))
    print(json.dumps(report["variants"], ensure_ascii=False))
    if not report["passed"]:
        raise SystemExit("QA visibility gate failed; evidence saved")


if __name__ == "__main__":
    main()
