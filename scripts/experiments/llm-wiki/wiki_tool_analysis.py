"""Preregistered per-domain quality decisions and descriptive Wiki timings.

Only original paired grades are used. Legacy latency/zero-critical gates are
not used to decide whether the Wiki experiment is worth continuing.
"""

import math
import statistics

from compare_followup import compare_records


ARMS = ("main", "main_noise", "qa_full", "wiki_tool")
WIKI_ARMS = ("wiki_tool",)
BASES = ("main", "qa_full")
PHASES = ("selection", "answer", "unclassified")


def _number(value):
    return (not isinstance(value, bool) and isinstance(value, (int, float))
            and math.isfinite(value) and value >= 0)


def _summary(values):
    measured = sorted(value for value in values if value is not None)
    return {
        "expected": len(values), "measured": len(measured),
        "missing": len(values) - len(measured),
        "median": statistics.median(measured) if measured else None,
        "p90": measured[math.ceil(.9 * len(measured)) - 1] if measured else None,
        "p90_method": "nearest_rank",
    }


def _first_text(row, grade):
    latency = row.get("latency")
    value = latency.get("first_text_ms") if isinstance(latency, dict) else None
    if (row.get("error") or grade.get("execution_error")
            or not row["answer"].strip() or not _number(value)):
        return None
    return value


def _phase(event):
    return event.get("phase") if event.get("phase") in PHASES else "unclassified"


def _telemetry(row):
    calls = row.get("llm_calls")
    events = row.get("usage")
    valid_calls = isinstance(calls, list) and all(isinstance(c, dict) for c in calls)
    valid_events = isinstance(events, list) and all(isinstance(e, dict) for e in events)
    phases = {}
    for phase in PHASES:
        phase_calls = [c for c in calls if _phase(c) == phase] if valid_calls else []
        phase_events = [e for e in events if _phase(e) == phase] if valid_events else []
        missing, total = 0, 0
        for event in phase_events:
            usage = event.get("usage")
            tokens = usage.get("input_tokens") if isinstance(usage, dict) else None
            if type(tokens) is not int or tokens < 0:
                missing += 1
            else:
                total += tokens
        if not valid_events and phase_calls:
            missing += len(phase_calls)
        elif not valid_events and phase == "unclassified" and (not valid_calls or not calls):
            missing += 1
        elif valid_events and phase_calls and not phase_events:
            missing += len(phase_calls)
        phases[phase] = {
            "logical_llm_calls": len(phase_calls) if valid_calls else None,
            "input_tokens": None if missing else total,
            "token_missing": missing,
            "usage_event_count": len(phase_events) if valid_events else None,
        }
    complete = all(value["input_tokens"] is not None for value in phases.values())
    return {
        "logical_llm_calls": len(calls) if valid_calls else None,
        "input_tokens": sum(p["input_tokens"] for p in phases.values()) if complete else None,
        "token_missing": sum(p["token_missing"] for p in phases.values()),
        "usage_event_count": len(events) if valid_events else None,
        "phases": phases,
    }


def _paired_latency(candidate, base, keys, timings):
    pairs, missing = [], []
    for cid, rep in keys:
        baseline = timings[cid, rep, base]
        value = timings[cid, rep, candidate]
        item = {"id": cid, "rep": rep, "base_ms": baseline, "candidate_ms": value}
        if baseline is None or value is None:
            missing.append(item)
        else:
            pairs.append({**item, "added_ms": value - baseline})
    values = [pair["added_ms"] for pair in pairs]
    return {
        "base": base, "candidate": candidate, "expected_pairs": len(keys),
        "measured_pairs": len(pairs), "missing_pairs": missing,
        "complete": not missing, "pairs": pairs,
        "median_added_ms": statistics.median(values) if values else None,
        "p90_added_ms": sorted(values)[math.ceil(.9 * len(values)) - 1] if values else None,
        "p90_method": "nearest_rank", "decision_gate": False,
    }


def _regressions(candidate, base, case_ids, grades):
    stable, new_critical = [], []
    for cid in case_ids:
        baseline = [grades[cid, rep, base] for rep in range(3)]
        wiki = [grades[cid, rep, candidate] for rep in range(3)]
        failing = [rep for rep, grade in enumerate(wiki) if not grade["pass"]]
        if all(grade["pass"] for grade in baseline) and len(failing) >= 2:
            stable.append({"id": cid, "failing_reps": failing})
        critical_reps = [rep for rep, grade in enumerate(wiki) if grade["critical"]]
        if not any(grade["critical"] for grade in baseline) and critical_reps:
            new_critical.append({"id": cid, "critical_reps": critical_reps})
    return {"stable_pass_regressions": stable, "new_critical_questions": new_critical}


def analyze(live, judged):
    """Analyze one domain: exactly four arms, 32 questions and three repetitions.

    Inputs use compare_followup's live/judged contracts plus the runner's
    llm_calls, provider usage events and Wiki selection telemetry. No grades
    are changed. Root callers combine domains by requiring both to pass.
    """
    validated = compare_records(live, judged)
    if set(validated["arms"]) != set(ARMS) or validated["question_count"] != 32:
        raise ValueError("Wiki analysis requires four declared arms and 32 questions per domain")
    source = live["records"] if isinstance(live, dict) else live
    records = {(row["id"], row["rep"], row["variant"]): row for row in source}
    grades = {(row["id"], row["rep"], row["variant"]): row for row in judged}
    case_ids = validated["case_ids"]
    keys = [(cid, rep) for cid in case_ids for rep in range(3)]
    timings = {key: _first_text(row, grades[key]) for key, row in records.items()}
    noise = [
        {"id": cid, "rep": rep}
        for cid, rep in keys
        if grades[cid, rep, "main"]["pass"] != grades[cid, rep, "main_noise"]["pass"]
    ]
    per_question = [{
        "id": cid, "arms": {
            arm: {field: [grades[cid, rep, arm][field] for rep in range(3)]
                  for field in ("pass", "critical")}
            for arm in ARMS
        },
    } for cid in case_ids]
    results = {}
    for arm in ARMS:
        original = validated["arms"][arm]
        telemetry = []
        for cid, rep in keys:
            row = records[cid, rep, arm]
            item = {"id": cid, "rep": rep, **_telemetry(row)}
            if arm in WIKI_ARMS:
                selection = row.get("wiki_selection", {})
                selected = selection.get("selected_page_ids")
                elapsed = row.get("wiki_selection_ms")
                item.update(
                    selected_page_ids=selected,
                    selection_ms=elapsed if (_number(elapsed) and not row.get("error")
                                             and not grades[cid, rep, arm].get("execution_error")) else None,
                    embedding_requests=row.get("embedding_calls_during_request", 0),
                )
            telemetry.append(item)
        result = {field: original[field] for field in (
            "denominator", "pass", "failed", "critical", "errors", "error_counts", "per_round",
        )}
        result.update({
            "absolute_first_text_ms": _summary([timings[cid, rep, arm] for cid, rep in keys]),
            "logical_llm_calls": _summary([r["logical_llm_calls"] for r in telemetry]),
            "input_tokens": _summary([r["input_tokens"] for r in telemetry]),
            "token_missing": sum(r["token_missing"] for r in telemetry),
            "phases": {phase: {
                "logical_llm_calls": _summary([r["phases"][phase]["logical_llm_calls"] for r in telemetry]),
                "input_tokens": _summary([r["phases"][phase]["input_tokens"] for r in telemetry]),
                "token_missing": sum(r["phases"][phase]["token_missing"] for r in telemetry),
            } for phase in PHASES},
            "telemetry": telemetry,
            "paired_first_text": {base: _paired_latency(arm, base, keys, timings) for base in BASES},
        })
        if arm in WIKI_ARMS:
            delta = original["pass"] - validated["arms"]["qa_full"]["pass"]
            regressions = {base: _regressions(arm, base, case_ids, grades) for base in BASES}
            gates = {
                "gain_more_than_six": delta > 6,
                "gain_exceeds_main_noise_disagreements": delta > len(noise),
                "no_stable_pass_regression_vs_either_base": all(
                    not value["stable_pass_regressions"] for value in regressions.values()
                ),
                "no_new_critical_vs_either_base": all(
                    not value["new_critical_questions"] for value in regressions.values()
                ),
            }
            embedding_violations = [
                {"id": r["id"], "rep": r["rep"], "value": r["embedding_requests"]}
                for r in telemetry
                if type(r["embedding_requests"]) is not int or r["embedding_requests"] != 0
            ]
            result.update({
                "delta_pass_vs_qa_full": delta, "average_gain_per_round": delta / 3,
                "regressions_vs": regressions, "quality_gates": gates,
                "quality_pass": all(gates.values()),
                "embedding_zero": not embedding_violations,
                "embedding_violations": embedding_violations,
                "selection_ms": _summary([r["selection_ms"] for r in telemetry]),
                "worthy_to_continue": all(gates.values()) and not embedding_violations,
            })
        results[arm] = result
    main_variation = []
    for cid in case_ids:
        for first, second in ((0, 1), (0, 2), (1, 2)):
            before, after = timings[cid, first, "main"], timings[cid, second, "main"]
            delta = None if before is None or after is None else after - before
            main_variation.append({"id": cid, "reps": [first, second], "delta_ms": delta})
    return {
        "question_count": 32, "rounds": 3, "pairs_per_arm": 96,
        "policy": {
            "gain": "wiki pass minus qa_full pass > 6 and > paired main/main_noise label disagreements",
            "regression": "Either main or qa_full passes 3/3; Wiki fails at least 2/3",
            "critical": "Either base has critical 0/3; Wiki has critical >=1/3",
            "latency": "Descriptive only; incomplete/error timings never become zero",
            "tokens": "Sum provider usage events; missing usage is unknown, never zero",
            "multiple_domains": "A Wiki arm must independently pass every domain",
        },
        "main_noise": {
            "pass_label_disagreement_count": len(noise), "disagreement_pairs": noise,
            "paired_first_text": _paired_latency("main_noise", "main", keys, timings),
        },
        "main_self_variation": {
            "pairs": main_variation,
            "signed_delta_ms": _summary([r["delta_ms"] for r in main_variation]),
            "absolute_delta_ms": _summary([
                abs(r["delta_ms"]) if r["delta_ms"] is not None else None for r in main_variation
            ]),
        },
        "per_question": per_question, "arms": results,
        "worthy_to_continue": {arm: results[arm]["worthy_to_continue"] for arm in WIKI_ARMS},
    }
