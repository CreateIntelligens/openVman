"""Package stored lint findings for source-owner review, never clinical approval.

CLI inputs are original/lint rows, stored findings and optional plant metadata.
Output contains private source text and must remain outside repositories. No
model or remote service is called. Every finding and its original fields survive;
source differences identify fixtures, not the presence of a ref in plants.json.
"""

import argparse
from collections import Counter
import hashlib
import json
from pathlib import Path

from experiment_io import validate_output


def row_map(rows):
    result = {}
    if not isinstance(rows, list):
        raise ValueError("Rows must be a list")
    for row in rows:
        if not isinstance(row, dict) or not all(k in row for k in ("file", "index", "q", "a")):
            raise ValueError("Row fields missing")
        if not all(isinstance(row[k], str) for k in ("file", "q", "a")):
            raise ValueError("Row content must be strings")
        ref = row["file"] + "#" + str(row["index"])
        if ref in result:
            raise ValueError("Duplicate row reference")
        result[ref] = row
    return result


def review_packet(original, lint_rows, findings):
    originals, tested = row_map(original), row_map(lint_rows)
    if not isinstance(findings, list):
        raise ValueError("Findings must be a list")
    packet = []
    for index, finding in enumerate(findings):
        if not isinstance(finding, dict) or not isinstance(finding.get("ids"), list):
            raise ValueError("Each finding must contain ids")
        refs = finding["ids"]
        if not refs or not all(isinstance(ref, str) and ref for ref in refs):
            raise ValueError("Finding references must be nonempty strings")
        unknown = sorted({r for r in refs if r not in originals or r not in tested})
        changed = sorted({r for r in refs if r in originals and r in tested
                          and (originals[r]["q"], originals[r]["a"]) != (tested[r]["q"], tested[r]["a"])})
        disposition = "unresolved_reference" if unknown else "synthetic_fixture" if changed else "review_required"
        packet.append({
            "review_id":f"LINT-{index + 1:04d}", "finding":finding,
            "original_sources":{r:originals[r] for r in refs if r in originals},
            "lint_sources":{r:tested[r] for r in refs if r in tested},
            "changed_refs":changed, "unknown_refs":unknown,
            "disposition":disposition, "approved":False,
        })
    return {"scope":"Private review packet; no medical or business fact automatically approved",
            "findings":packet, "counts":dict(Counter(r["disposition"] for r in packet))}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ("original-rows", "lint-rows", "findings", "output"):
        parser.add_argument("--" + name, type=Path, required=True)
    parser.add_argument("--plants", type=Path)
    args = parser.parse_args()
    inputs = [args.original_rows, args.lint_rows, args.findings]
    if args.plants:
        inputs.append(args.plants)
    output = validate_output(args.output, inputs=inputs)
    if output.exists():
        parser.error("Choose a new review output path")
    bodies = {p:p.read_bytes() for p in inputs}
    packet = review_packet(*[json.loads(bodies[p]) for p in inputs[:3]])
    packet["input_sha256"] = {str(p):hashlib.sha256(bodies[p]).hexdigest() for p in inputs}
    if args.plants:
        packet["plant_metadata"] = json.loads(bodies[args.plants])
    if any(p.read_bytes() != body for p, body in bodies.items()):
        raise ValueError("Review inputs changed; no packet published")
    with output.open("x") as stream:
        stream.write(json.dumps(packet, ensure_ascii=False, indent=2) + "\n")
    print(json.dumps({"findings":len(packet["findings"]), "counts":packet["counts"]}))


if __name__ == "__main__":
    main()
