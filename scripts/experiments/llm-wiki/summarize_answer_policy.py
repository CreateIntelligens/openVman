"""Validate paired answer-policy evidence without certifying production readiness.

Each domain has control_live.json, candidate_live.json and the corresponding
*_judged.json lists. Optional review.json binds both judged files with
input_sha256 (live hashes may also be supplied), and contains overrides with
profile, id, rep, variant, old/new_pass, old/new_critical and reason.
"""

import argparse
from copy import deepcopy
import hashlib
import itertools
import json
from pathlib import Path
import re
import statistics

from answer_policy import EVIDENCE_V1, policy_metadata
from experiment_io import repository_roots, validate_output


PROFILES = {"control": "production", "candidate": "evidence_v1"}
DOMAINS = ("hospital", "heji")
VARIANT = "safe_mixed"
CLOCK = re.compile(r"(?<!\S)- current_time: (\d{4}-\d{2}-\d{2}) "
                   r"((?:[01]\d|2[0-3]):[0-5]\d:[0-5]\d)"
                   r" ([A-Z][A-Z0-9+:-]* \((?:Monday|Tuesday|Wednesday|Thursday|"
                   r"Friday|Saturday|Sunday)\))(?=\s|$)")


def digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def read_json(path):
    try:
        return json.loads(Path(path).read_text())
    except (OSError, ValueError) as exc:
        raise ValueError(f"Missing or invalid evidence: {path}") from exc


def keyed(rows):
    result = {}
    for row in rows:
        key = (row["id"], row["rep"], row["variant"])
        if key in result:
            raise ValueError("Duplicate answer keys")
        if type(row["rep"]) is not int:
            raise ValueError("Repetition must be an integer")
        result[key] = row
    return result


def input_sources(live, evidence_path, expected_cases):
    sources = {}
    cases = None
    retrieval = None
    for name, expected in live["inputs_sha256"].items():
        path = Path(name)
        if not path.is_absolute():
            raise ValueError("Input evidence must name absolute source paths")
        if digest(path) != expected:
            raise ValueError(f"Input hash mismatch: {path}")
        sources[str(path)] = expected
        value = read_json(path)
        if isinstance(value, list) or isinstance(value, dict) and "cases" in value:
            if cases is not None:
                raise ValueError("Ambiguous cases source")
            cases = value if isinstance(value, list) else value["cases"]
        elif isinstance(value, dict) and "questions" in value:
            if retrieval is not None:
                raise ValueError("Ambiguous retrieval source")
            retrieval = value
        else:
            raise ValueError(f"Unknown live input source: {evidence_path}: {path}")
    if cases is None or retrieval is None:
        raise ValueError("Cases and retrieval sources are required")
    by_id = {case["id"]: case for case in cases}
    if len(by_id) != len(cases) or len(cases) != expected_cases:
        raise ValueError("Cases source has duplicate IDs or unexpected case count")
    if retrieval.get("project_id") != live["project_id"]:
        raise ValueError("Retrieval project mismatch")
    for case_id in by_id:
        if VARIANT not in retrieval["questions"].get(case_id, {}):
            raise ValueError("Retrieval does not cover every case")
    return by_id, sources


def tool_evidence(row):
    steps, context, failed = [], [], False
    for step in row["tool_steps"]:
        result = json.loads(step["result"])
        failed |= result.get("status") != "ok"
        data = result.get("data", {})
        # Call IDs and timing are incidental; actual returned content is not.
        content = {key: data.get(key, []) for key in ("results", "related", "queries")}
        if any(not isinstance(value, list) for value in content.values()):
            raise ValueError("Invalid tool result data")
        steps.append(content)
        context.extend(item["text"] for item in content["results"] + content["related"])
    return steps, "\n\n".join(context) or "（沒有找到資料）", failed


def validate_verdict(row):
    if type(row["pass"]) is not bool or type(row["critical"]) is not bool:
        raise ValueError("Verdict labels must be booleans")
    if row["pass"] and (row["critical"] or "execution_error" in row or "judge_error" in row):
        raise ValueError("Critical or failed execution/judge cannot pass")


def validate_profile(live, grades, profile, cases):
    if live.get("config_unchanged") is not True or live["readonly_check"]["changed_paths"] != []:
        raise ValueError("Read-only manifest/config verification failed")
    if not isinstance(live["readonly_check"].get("file_count"), int):
        raise ValueError("Missing read-only manifest count")
    if live["answer_policy"] != policy_metadata(PROFILES[profile]):
        raise ValueError("Unexpected answer policy")
    records, judgments = keyed(live["records"]), keyed(grades)
    expected = set(itertools.product(cases, range(2), (VARIANT,)))
    if set(records) != expected or set(judgments) != expected:
        raise ValueError("Incomplete case/repetition/variant distribution")
    execution_count = 0
    for key, row in records.items():
        case, grade = cases[key[0]], judgments[key]
        if row["q"] != case["q"] or row["history"] != case.get("history", []):
            raise ValueError("Question/history differs from cases source")
        if row["answer_policy"] != live["answer_policy"]:
            raise ValueError("Per-answer policy differs from live metadata")
        messages = row.get("prompt_messages", [])
        if not messages or messages[0].get("role") != "system":
            raise ValueError("Missing actual production prompt")
        if messages[-1] != {"role": "user", "content": case["q"]}:
            raise ValueError("Current question changed in prompt")
        steps, context, tool_failure = tool_evidence(row)
        system = "\n\n".join(m["content"] for m in messages if m.get("role") == "system")
        if grade["answer"] != row["answer"]:
            raise ValueError("Judged answer differs from live answer")
        if grade.get("context") != context or grade.get("system_context") != system:
            raise ValueError("Judged context/system differs from actual live evidence")
        if grade.get("system_sha256") != hashlib.sha256(system.encode()).hexdigest():
            raise ValueError("Judged system hash mismatch")
        failed = bool(row.get("error") or tool_failure or not row["answer"] or not steps)
        execution_count += failed
        if failed != ("execution_error" in grade):
            raise ValueError("Execution-error accounting differs from live evidence")
        validate_verdict(grade)
    if len(live["errors"]) != sum(bool(row.get("error")) for row in records.values()):
        raise ValueError("Live execution error list does not match records")
    return records, judgments, execution_count


def compare_profiles(lives, records):
    for field in ("project_id", "persona_id", "inputs_sha256", "production_code_sha256",
                  "workspace_documents", "configured_chain", "answer_policy_source_sha256",
                  "runtime_sha256", "runner_sha256", "disabled_paths"):
        if field not in lives["control"] or not lives["control"][field] and field != "disabled_paths":
            raise ValueError(f"Missing control provenance: {field}")
        if lives["control"][field] != lives["candidate"].get(field):
            raise ValueError(f"Control/candidate provenance differs: {field}")
    for key, control in records["control"].items():
        candidate = records["candidate"][key]
        if tool_evidence(control)[0] != tool_evidence(candidate)[0]:
            raise ValueError("Control/candidate actual tool context differs")
        expected = deepcopy(control["prompt_messages"])
        expected[0]["content"] += "\n\n" + EVIDENCE_V1
        actual = deepcopy(candidate["prompt_messages"])
        for messages in (expected, actual):
            messages[0]["content"] = CLOCK.sub(
                lambda match: f"- current_time: {match[1]} HH:MM:SS {match[3]}",
                messages[0]["content"],
            )
        if actual != expected:
            raise ValueError("Candidate prompt changed beyond the fixed evidence policy")


def metrics(rows):
    rows = list(rows)
    return {"count": len(rows), "passed": sum(r["pass"] for r in rows),
            "critical": sum(r["critical"] for r in rows),
            "execution_errors": sum("execution_error" in r for r in rows),
            "judge_errors": sum("judge_error" in r for r in rows)}


def paired(judgments):
    pairs = [(a["pass"], judgments["candidate"][key]["pass"])
             for key, a in judgments["control"].items()]
    return {"count": len(pairs), "pass_to_fail": pairs.count((True, False)),
            "fail_to_pass": pairs.count((False, True)),
            "both_pass": pairs.count((True, True)), "both_fail": pairs.count((False, False))}


def reply_lengths(records):
    lengths = [len(row["answer"]) for row in records.values()]
    return {"count": len(lengths), "min": min(lengths), "max": max(lengths),
            "mean": round(statistics.mean(lengths), 2), "median": statistics.median(lengths),
            "over_80_codepoints": sum(length > 80 for length in lengths),
            "over_80_keys": [{"id": key[0], "rep": key[1], "variant": key[2]}
                             for key, row in records.items() if len(row["answer"]) > 80]}


def apply_review(judgments, review, paths):
    hashes = review["input_sha256"]
    required = {f"{profile}_judged.json" for profile in PROFILES}
    if not required <= set(hashes) or not set(hashes) <= set(paths):
        raise ValueError("Review must bind both raw judgments and only known raw files")
    for name, expected in hashes.items():
        if digest(paths[name]) != expected:
            raise ValueError("Review input hash mismatch")
    result, seen = deepcopy(judgments), set()
    for change in review["overrides"]:
        key = (change["id"], change["rep"], change["variant"])
        profile = change["profile"]
        identity = (profile, key)
        if identity in seen:
            raise ValueError("Duplicate review override")
        seen.add(identity)
        if profile not in result or key not in result[profile]:
            raise ValueError("Review references unknown answer")
        row = result[profile][key]
        if any(type(change[field]) is not bool for field in
               ("old_pass", "new_pass", "old_critical", "new_critical")):
            raise ValueError("Review labels must be booleans")
        if (row["pass"], row["critical"]) != (change["old_pass"], change["old_critical"]):
            raise ValueError("Review old values differ from raw judgment")
        if not isinstance(change.get("reason"), str) or not change["reason"].strip():
            raise ValueError("Review override requires a reason")
        row.update({"pass": change["new_pass"], "critical": change["new_critical"]})
        validate_verdict(row)
    return result


def summarize_domain(root, case_count):
    paths = {f"{p}_{kind}.json": root / f"{p}_{kind}.json"
             for p in PROFILES for kind in ("live", "judged")}
    lives, judgments, records, sources = {}, {}, {}, {}
    for profile in PROFILES:
        live_path = paths[f"{profile}_live.json"]
        live = read_json(live_path)
        cases, inputs = input_sources(live, live_path, case_count)
        sources.update(inputs)
        rows, grades, _ = validate_profile(
            live, read_json(paths[f"{profile}_judged.json"]), profile, cases,
        )
        lives[profile], records[profile], judgments[profile] = live, rows, grades
    compare_profiles(lives, records)
    result = {"raw": {p: metrics(rows.values()) for p, rows in judgments.items()},
              "paired_raw": paired(judgments), "review_status": "unreviewed",
              "case_count": case_count, "repetitions": 2, "variant": VARIANT,
              "models": {p: sorted({m for r in rows.values() for m in r["models"]})
                         for p, rows in records.items()},
              "configured_chain": lives["control"]["configured_chain"],
              "project_id": lives["control"]["project_id"],
              "production_code_sha256": lives["control"]["production_code_sha256"],
              "workspace_documents": lives["control"]["workspace_documents"],
              "policy": lives["candidate"]["answer_policy"]}
    result["reply_length_codepoints"] = {p: reply_lengths(rows) for p, rows in records.items()}
    result["reply_length_scope"] = (
        "Independent Unicode codepoint observations, including whitespace and punctuation; "
        "not content pass labels, English word counts, actual 20-second speech timing, "
        "or complete operational formatting/voice acceptance."
    )
    result["execution_clocks"] = {
        p: sorted({match[0] for row in rows.values()
                   for match in CLOCK.finditer(row["prompt_messages"][0]["content"])})
        for p, rows in records.items()
    }
    result["clock_scope"] = "Execution clock advanced naturally; time was not frozen. Only HH:MM:SS may differ."
    review_path = root / "review.json"
    if review_path.exists():
        review = read_json(review_path)
        reviewed = apply_review(judgments, review, paths)
        result.update(reviewed={p: metrics(rows.values()) for p, rows in reviewed.items()},
                      paired_reviewed=paired(reviewed), review_status="reviewed",
                      review_scope=review.get("review_scope", "Only explicitly supplied overrides"))
        paths["review.json"] = review_path
    result["evidence_sha256"] = {str(path): digest(path) for path in paths.values()}
    result["evidence_sha256"].update(sources)
    return result


def summarize(root, holdout_root=None):
    batches = {"main": (Path(root), 32)}
    if holdout_root is not None:
        batches["holdout"] = (Path(holdout_root), 12)
    result = {"batches": {}, "status": "NOT_CERTIFIED", "readiness_reasons": [],
              "scope": ("Paired production prompt/agent/provider runs with injected retrieval "
                        "snapshots. No gold/rubric is added to answering prompts. Not HTTP, "
                        "UI, media, project isolation or deployment certification."),
              "judge_model": "Not recorded in raw judgments; consult judge sidecar provenance."}
    for name, (directory, count) in batches.items():
        directory = directory.resolve()
        if any(directory == r or r in directory.parents for r in repository_roots()):
            raise ValueError("Evidence roots must stay outside repositories")
        result["batches"][name] = {}
        for domain in DOMAINS:
            data = summarize_domain(directory / domain, count)
            result["batches"][name][domain] = data
            if data["review_status"] == "unreviewed":
                result["readiness_reasons"].append(f"{name}/{domain}: unreviewed")
            score = data.get("reviewed", data["raw"])["candidate"]
            if score["passed"] != score["count"] or score["critical"] or score["execution_errors"] or score["judge_errors"]:
                result["readiness_reasons"].append(f"{name}/{domain}: candidate failures remain")
    if holdout_root is None:
        result["readiness_reasons"].append("Independent holdout evidence not supplied")
    if result["readiness_reasons"]:
        result["status"] = "NOT_READY"
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, required=True)
    parser.add_argument("--holdout-root", type=Path)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    inputs = [p for root in (args.root, args.holdout_root) if root is not None
              for p in root.rglob("*.json")]
    output = validate_output(args.output, inputs=inputs)
    if output.exists():
        parser.error("Output exists; choose another path")
    try:
        result = summarize(args.root, args.holdout_root)
        sources = [Path(name) for batch in result["batches"].values()
                   for domain in batch.values() for name in domain["evidence_sha256"]]
        validate_output(output, inputs=sources)
    except (KeyError, TypeError, OSError, ValueError) as exc:
        parser.error(f"NOT_READY: {exc}")
    output.parent.mkdir(parents=True, exist_ok=True)
    with output.open("x") as stream:
        stream.write(json.dumps(result, ensure_ascii=False, indent=2) + "\n")
    print(json.dumps({"status": result["status"], "output": str(output)}))


if __name__ == "__main__":
    main()
