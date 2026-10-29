"""Revalidate saved checker responses without new facts, retrieval or model calls."""

import argparse
from copy import deepcopy
import hashlib
import json
from pathlib import Path

from answer_check import (
    finalize_verdict,
    parse_reply,
    resolved_language,
    valid_verdict,
)
from live_agent_stress import HERE, output_path


def reprocess_row(original):
    row = deepcopy(original)
    check = row.get("answer_check")
    if not check or check.get("error") == "scope_check_failed" or not check.get("attempts"):
        return row
    repair_error = bool(check.get("repair") and check.get("error") in (
        "repair_generation_failed", "repair_verification_failed"))
    if check.get("repair") and not repair_error:
        return row
    answer = check["original_answer"]
    evidence = [item for step in row["tool_steps"] for field in ("results", "related")
                for item in json.loads(step["result"])["data"].get(field, [])]
    system = row["prompt_messages"][0]["content"]
    language = resolved_language("", system)
    for index, attempt in enumerate(check["attempts"]):
        try:
            verdict = parse_reply(attempt["response_content"])
            if not valid_verdict(verdict, answer, evidence, system):
                continue
        except (KeyError, TypeError, ValueError):
            continue
        finalized = finalize_verdict(verdict, answer, language)
        if repair_error and finalized["action"] != "accept":
            continue
        row["previous_check"] = check
        row["answer_check"] = {
            "original_answer": answer, "scope": check["scope"],
            "scope_attempts": check["scope_attempts"], "attempts": check["attempts"],
            "post_validation": "Saved response revalidated; no new model call",
            "selected_attempt": index,
            **finalized,
        }
        row["answer"] = row["answer_check"]["final_answer"]
        if row.get("error") and (row["error"]["type"] == "AnswerCheckFailed" or
                row["error"]["message"] == "Answer evidence check failed; attempts retained"):
            row["previous_check_error"] = row["error"]
            row["error"] = None
        break
    return row


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--live", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    target = output_path(args.output, [args.live])
    data = json.loads(args.live.read_text())
    if not data.get("config_unchanged") or data["readonly_check"]["changed_paths"]:
        parser.error("Original run did not pass read-only verification")
    data["records"] = [reprocess_row(row) for row in data["records"]]
    data["errors"] = [{"id": r["id"], "error": r["error"]} for r in data["records"] if r.get("error")]
    data["post_validation_input_sha256"] = {str(args.live): hashlib.sha256(args.live.read_bytes()).hexdigest()}
    data["post_validation_source_sha256"] = {
        name: hashlib.sha256((HERE / name).read_bytes()).hexdigest()
        for name in ("answer_check.py", "reprocess_checks.py")}
    data["post_validation_scope"] = "Same saved model responses; literal citation/schema validation only"
    target.write_text(json.dumps(data, ensure_ascii=False, indent=1))
    print(json.dumps({"count": len(data["records"]), "errors": len(data["errors"]), "output": str(target)}))


if __name__ == "__main__":
    main()
