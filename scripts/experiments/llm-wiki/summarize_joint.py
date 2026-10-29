"""Bind dynamic retrieval, paired checks and judgments before reporting metrics."""

import argparse
from copy import deepcopy
import hashlib
import itertools
import json
from pathlib import Path
import statistics

from answer_check import literal_audit
from experiment_io import repository_roots, validate_output
from summarize_answer_policy import keyed, metrics, tool_evidence, validate_verdict


def digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def validate_batch(cases, live, grades):
    if (not live.get("config_unchanged") or live["readonly_check"]["changed_paths"]
            or live.get("retrieval_mode") != "dynamic"):
        raise ValueError("Dynamic read-only run required")
    cases_by_id = {c["id"]: c for c in cases}
    if len(cases_by_id) != len(cases):
        raise ValueError("Duplicate cases")
    records, judgments = keyed(live["records"]), keyed(grades)
    variants = {r["variant"] for r in records.values()}
    expected = set(itertools.product(cases_by_id, range(2), variants))
    if set(records) != expected or set(judgments) != expected:
        raise ValueError("Incomplete cases/repetitions/variants")
    for key, row in records.items():
        case, grade = cases_by_id[key[0]], judgments[key]
        if row["q"] != case["q"] or row["history"] != case.get("history", []):
            raise ValueError("Case/history changed")
        messages = row.get("prompt_messages", [])
        if not messages and not row.get("error"):
            raise ValueError("Successful run lacks prompt")
        if messages and messages[-1] != {"role": "user", "content": case["q"]}:
            raise ValueError("Actual prompt changed question")
        system = "\n\n".join(m["content"] for m in messages if m["role"] == "system")
        steps, context, tool_failure = tool_evidence(row)
        if (grade["answer"] != row["answer"] or grade["context"] != context
                or grade["system_context"] != system
                or grade["system_sha256"] != hashlib.sha256(system.encode()).hexdigest()):
            raise ValueError("Judged answer/context/system differs from actual evidence")
        failed = bool(row.get("error") or not row["answer"] or not steps or tool_failure)
        if failed != ("execution_error" in grade):
            raise ValueError("Execution failures omitted from denominator")
        if (not row.get("source_access_gate") or row.get("unauthorized_sources")) and not grade["critical"]:
            raise ValueError("Unauthorized source must be critical")
        traces = row.get("retrieval_trace", [])
        if not failed and len(traces) != len(steps):
            raise ValueError("Missing actual dynamic search trace")
        if any(t["profile"] != row["variant"] or t["selected_chars"] > 8000 for t in traces):
            raise ValueError("Wrong dynamic profile or exceeded context budget")
        validate_verdict(grade)
    if len(live["errors"]) != sum(bool(r.get("error")) for r in records.values()):
        raise ValueError("Execution error list differs from records")
    return records, judgments


def validate_replay(original, checked):
    if checked["check_readonly"]["changed_paths"]:
        raise ValueError("Check mutated production")
    original_records = keyed(original["records"])
    for key, row in keyed(checked["records"]).items():
        source = original_records[key]
        check = row["answer_check"]
        draft = (source["answer_check"]["original_answer"]
                 if checked.get("check_restore_drafts") and "answer_check" in source else source["answer"])
        if (row["precheck_answer"] != draft
                or check["original_answer"] != draft
                or row["answer"] != check["final_answer"]
                or row["prompt_messages"] != source["prompt_messages"]
                or row["retrieval_trace"] != source["retrieval_trace"]
                or tool_evidence(row)[0] != tool_evidence(source)[0]):
            raise ValueError("Replay changed original answer, prompt or retrieval")
        if check.get("checked_answer"):
            repair = check["repair"]
            proof = repair["verification"]
            if (proof.get("error") or proof["action"] != "accept"
                    or proof["original_answer"] != repair["draft"]
                    or check["checked_answer"] != repair["draft"]
                    or proof["final_answer"] != row["answer"]):
                raise ValueError("Repair was not independently verified")
            evidence = [item for step in row["tool_steps"] for field in ("results", "related")
                        for item in json.loads(step["result"])["data"].get(field, [])]
            if (literal_audit(proof, repair["draft"], evidence, row["prompt_messages"][0]["content"])
                    or any(span["status"] == "unsupported" for span in proof["spans"])):
                raise ValueError("Published repair lacks literal proof")
    for field in ("project_id", "persona_id", "production_code_sha256", "dynamic_source_sha256",
                  "inputs_sha256", "answer_policy", "history_policy", "context_policy"):
        if original[field] != checked[field]:
            raise ValueError("Replay provenance differs")


def apply_overrides(batches, review, paths):
    if review.get("input_sha256") != {str(p): digest(p) for p in paths}:
        raise ValueError("Review must bind exactly all batch inputs")
    result = deepcopy(batches)
    seen = set()
    for change in review["overrides"]:
        key = (change["id"], change["rep"], change["variant"])
        identity = (change["batch"], key)
        if identity in seen:
            raise ValueError("Duplicate review override")
        seen.add(identity)
        row = result[change["batch"]][key]
        if (row["pass"], row["critical"]) != (change["old_pass"], change["old_critical"]):
            raise ValueError("Review old labels differ")
        if not change.get("reason"):
            raise ValueError("Review reason required")
        row.update({"pass": change["new_pass"], "critical": change["new_critical"]})
        if (row.get("unauthorized_sources") or row.get("source_access_gate") is False) and not row["critical"]:
            raise ValueError("Review cannot remove a source-access failure")
        validate_verdict(row)
    return result


def summarize(rows, records):
    summary = {}
    for variant in sorted({r["variant"] for r in rows.values()}):
        selected = [r for r in rows.values() if r["variant"] == variant]
        actual = [r for r in records.values() if r["variant"] == variant]
        summary[variant] = metrics(selected)
        summary[variant].update(
            unauthorized_sources=sum(bool(r["unauthorized_sources"]) for r in actual),
            context_chars_median=statistics.median(sum(len(i["text"]) for step in r["tool_steps"]
                for field in ("results", "related")
                for i in json.loads(step["result"])["data"][field]) for r in actual),
            budget_violations=sum(
                sum(len(i["text"]) for field in ("results", "related")
                    for i in json.loads(step["result"])["data"][field]) > 8000
                for r in actual for step in r["tool_steps"]),
            answers_over_80_codepoints=sum(len(r["answer"]) > 80 for r in actual),
        )
    return summary


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--batch", nargs=4, action="append", required=True,
                        metavar=("LABEL", "CASES", "LIVE", "JUDGED"))
    parser.add_argument("--replay", nargs=2, action="append", default=[],
                        metavar=("ORIGINAL_LABEL", "CHECKED_LABEL"))
    parser.add_argument("--review", type=Path)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    paths, lives, records, judgments = set(), {}, {}, {}
    for label, cases_file, live_file, grade_file in args.batch:
        if label in lives:
            parser.error("Duplicate batch label")
        files = [Path(p).resolve() for p in (cases_file, live_file, grade_file)]
        cases, live, grades = (json.loads(p.read_text()) for p in files)
        for mapping in (live.get("inputs_sha256", {}), live.get("check_input_sha256", {}), live.get("post_validation_input_sha256", {}), live.get("component_runs_sha256", {}), live.get("point_fix_input_sha256", {}), live.get("draft_source_sha256", {})):
            for source, expected in mapping.items():
                if digest(source) != expected:
                    raise ValueError("Live input changed since run")
        summary_file = files[-1].with_suffix(".summary.json")
        grade_summary = json.loads(summary_file.read_text())
        for source, expected in grade_summary["input_sha256"].items():
            if digest(source) != expected:
                raise ValueError("Judge input changed since grading")
        records[label], judgments[label] = validate_batch(cases, live, grades)
        lives[label] = live
        paths.update(files + [summary_file])
    for original, checked in args.replay:
        validate_replay(lives[original], lives[checked])
    output = validate_output(args.output, inputs=paths | ({args.review} if args.review else set()),
                             roots=repository_roots())
    raw = {label: summarize(rows, records[label]) for label, rows in judgments.items()}
    reviewed = apply_overrides(judgments, json.loads(args.review.read_text()), paths) if args.review else judgments
    data = {"raw": raw, "reviewed": {label: summarize(rows, records[label]) for label, rows in reviewed.items()},
            "input_sha256": {str(p): digest(p) for p in sorted(paths)},
            "review_sha256": digest(args.review) if args.review else None,
            "scope": "Experimental dynamic agent runs and paired check replay; not HTTP/voice/UI acceptance"}
    output.write_text(json.dumps(data, ensure_ascii=False, indent=1))
    print(json.dumps(data["reviewed"], ensure_ascii=False))


if __name__ == "__main__":
    main()
