"""Replay recorded product tools offline; audit query meaning separately.

Only tool_audit.json is written. The real parser/engine functions are compiled
from the current checkout without loading workspace helpers or agent services.
Natural-language expectations below are manually transcribed from the frozen
questions, not inferred from the returned products or answer grades.
"""

import argparse
import ast
from collections import Counter
import hashlib
import json
from pathlib import Path
import sys
from types import ModuleType

import yaml


ROOT = Path(__file__).resolve().parent
REPO = ROOT.parents[4]
MODULES = (
    "brain/api/knowledge/product_catalog.py",
    "brain/api/knowledge/product_filter.py",
    "brain/api/tools/builtin/product_tools.py",
)


def rule(field, op, value):
    return (field, op, value)


# These are the user's conditions, including converted numeric thresholds.
RULES = {
    "F01": [rule("outlet_inch", "eq", 3), rule("phase", "member", 3),
            rule("hp", "lte", 5), rule("max_flow_lpm", "gte", 600)],
    "F02": [rule("phase", "member", 1), rule("outlet_inch", "eq", 2),
            rule("hp", "lte", 2), rule("max_flow_lpm", "gte", 500)],
    "F03": [rule("solids_mm", "gte", 65), rule("hp", "lte", 7.5),
            rule("max_flow_lpm", "gte", 1000)],
    "F04": [rule("phase", "member", 3), rule("outlet_inch", "eq", 4),
            rule("kw", "eq", 3.7), rule("max_flow_lpm", "gte", 1000)],
    "F05": [rule("phase", "member", 3), rule("outlet_inch", "eq", 3),
            rule("kw", "lte", 5.5), rule("max_flow_lpm", "gte", 1200)],
    "F06": [rule("series", "eq", "EUS"),
            rule("rated_flow_lpm", "gte", 250)],
    "F07": [rule("series", "eq", "HIPPO"), rule("outlet_inch", "eq", 2)],
    "F08": [rule("series", "in", ("DIVA", "DIVA PRO"))],
    "F09": [rule("hp", "eq", 3),
            rule("series", "in", ("STEEL", "HIPPO DN", "LEOPARD"))],
    "F10": [],
    "F11": {
        "甲": [rule("phase", "member", 1), rule("outlet_inch", "eq", 3),
               rule("hp", "lte", 2), rule("max_flow_lpm", "gte", 500)],
        "乙": [rule("phase", "member", 3), rule("outlet_inch", "eq", 4),
               rule("kw", "lte", 3.7), rule("solids_mm", "gte", 40),
               rule("max_flow_lpm", "gte", 1000)],
    },
    "F12": [rule("kw", "lte", 11), rule("rated_head_m", "gte", 15),
            rule("rated_flow_lpm", "gte", 1500)],
    "F14": [rule("current_1ph_a", "lte", 6),
            rule("weight_1ph_kg", "lte", 15), rule("solids_mm", "gte", 6)],
    "F15": [rule("phase", "member", 3), rule("hp", "lte", 10),
            rule("max_head_m", "gte", 18), rule("solids_mm", "gte", 68)],
    "F16": [rule("series", "in", ("EUSR", "ALLIGATOR"))],
}
SORTS = {
    "F07": [("max_flow_lpm", "desc"), ("weight_1ph_kg", "asc")],
    "F08": [("max_flow_lpm", "desc"), ("max_head_m", "asc"),
            ("outlet_inch", "asc"), ("series", "asc")],
    "F10": [("max_head_m", "desc")],
}
DIRECT_LOOKUPS = {"F13", "F17", "F20"}
ABSENT_FIELDS = {"F18": "price", "F19": "warranty"}


def digest(data):
    return hashlib.sha256(data).hexdigest()


def read_json(name):
    return json.loads((ROOT / name).read_text())


def current_functions():
    module = ModuleType("_offline_product_tool_audit")
    sys.modules[module.__name__] = module
    for relative in MODULES:
        path = REPO / relative
        tree = ast.parse(path.read_text(), filename=relative)
        if relative.endswith("product_catalog.py"):
            tree.body = [node for node in tree.body if not (
                isinstance(node, ast.ImportFrom)
                and node.module in ("knowledge.doc_meta", "knowledge.workspace")
            )]
        elif relative.endswith("product_filter.py"):
            tree.body = [node for node in tree.body if not (
                isinstance(node, ast.ImportFrom)
                and node.module == "knowledge.product_catalog"
            )]
        else:
            tree.body = [node for node in tree.body if (
                isinstance(node, ast.FunctionDef)
                and node.name in ("_scalar", "_condition", "_limit", "_to_query")
            ) or (isinstance(node, ast.ImportFrom)
                  and node.module == "__future__")]
        exec(compile(tree, relative, "exec"), module.__dict__)
    return module


def frozen_catalog(module, snapshot):
    files = snapshot["files"]
    definition = yaml.safe_load(files["knowledge/products/_catalog.yaml"])
    fields = module._parse_fields(definition["fields"])
    products = []
    for path in sorted(files):
        if not path.startswith("knowledge/products/") or not path.endswith(".md"):
            continue
        data = module._frontmatter(files[path])
        values = {name: module._check_value(spec, data.get(name))
                  for name, spec in fields.items()}
        products.append(module.Product(path=path, values=values))
    if len(products) != 117:
        raise ValueError(f"凍結筆記數量應117，實際{len(products)}")
    return module.ProductCatalog(
        title=definition["title"], key=definition["key"], fields=fields,
        notes=definition.get("notes", "").strip(), products=products,
    )


def value_diffs(expected, actual, path="$", differences=None):
    if differences is None:
        differences = []
    if isinstance(expected, dict) and isinstance(actual, dict):
        for key in sorted(expected.keys() | actual.keys()):
            if key not in expected or key not in actual:
                differences.append({"path": path + "." + key,
                                    "expected": expected.get(key),
                                    "actual": actual.get(key)})
            else:
                value_diffs(expected[key], actual[key], path + "." + key,
                            differences)
    elif isinstance(expected, list) and isinstance(actual, list):
        if len(expected) != len(actual):
            differences.append({"path": path + ".length",
                                "expected": len(expected), "actual": len(actual)})
        for index, (left, right) in enumerate(zip(expected, actual)):
            value_diffs(left, right, f"{path}[{index}]", differences)
    elif (isinstance(expected, bool) != isinstance(actual, bool)
          or expected != actual):
        differences.append({"path": path, "expected": expected, "actual": actual})
    return differences


def canonical(condition, fields):
    name, op, value = (condition.get(key) for key in ("field", "op", "value"))
    if name == "phase" and op in ("eq", "contains", "in"):
        members = value if op == "in" and isinstance(value, list) else [value]
        if any(type(v) not in (int, float) for v in members):
            return name, "invalid_members", tuple(map(str, members))
        unique = tuple(sorted(set(members)))
        return (name, "member", unique[0]) if len(unique) == 1 else (
            name, "member_any", unique,
        )
    if fields.get(name) and fields[name].type == "text":
        if op == "in" and isinstance(value, list):
            value = tuple(sorted(set(v.strip().lower() for v in value)))
            if len(value) == 1:
                return name, "eq", value[0]
        elif isinstance(value, str):
            value = value.strip().lower()
    elif isinstance(value, list):
        value = tuple(value)
    return name, op, value


def expected_tokens(rules, fields):
    tokens = []
    for name, op, value in rules:
        if op == "member":
            tokens.append((name, op, value))
        else:
            tokens.append(canonical({"field": name, "op": op,
                                     "value": list(value) if op == "in" else value},
                                    fields))
    return tokens


def issue(code, reason, level="tool_workflow_gap", **details):
    return {"code": code, "level": level, "reason": reason, **details}


def semantics(qid, converted, catalog):
    issues = []
    scenarios = converted["scenarios"]
    expected = RULES.get(qid)
    if qid == "F11":
        if len(scenarios) != 2:
            issues.append(issue("scenario_count", "甲乙必須分成兩個獨立情境", "error"))
        assignments = []
        for scenario in scenarios:
            name = scenario["name"].lower()
            label = "甲" if "甲" in name or name == "site_a" else (
                "乙" if "乙" in name or name == "site_b" else None
            )
            actual = [canonical(c, catalog.fields)
                      for c in scenario["where"]["all"]]
            if label is None:
                candidates = [key for key, rules in expected.items()
                              if Counter(actual) == Counter(expected_tokens(
                                  rules, catalog.fields))]
                label = candidates[0] if len(candidates) == 1 else None
            assignments.append(label)
            desired = expected.get(label, [])
            compare_conditions(actual, desired, catalog, issues, scenario["name"])
        if set(assignments) != {"甲", "乙"}:
            issues.append(issue("scenario_assignment", "甲乙情境對應無法完整確認",
                                "error", assignments=assignments))
        return issues, assignments
    if qid == "F16":
        # Null selection is not an exposed operator; all related specs may be
        # returned for the model to inspect, without declaring null a mismatch.
        tokens = [canonical(c, catalog.fields) for s in scenarios
                  for c in s["where"]["all"]]
        series = set()
        for name, op, value in tokens:
            if name == "series" and op == "eq":
                series.add(value)
            elif name == "series" and op == "in":
                series.update(value)
        if series != {"eusr", "alligator"}:
            issues.append(issue("series_scope", "EUSR與ALLIGATOR範圍未完整對應",
                                "error", actual=sorted(series)))
        issues.append(issue("null_selection_in_model",
                            "工具只選相關系列，未篩null；需另檢查返回的solids_mm，不能視為已執行未知值篩選"))
        return issues, [None] * len(scenarios)
    if expected is not None:
        if len(scenarios) != 1:
            issues.append(issue("scenario_count", "此題條件應為一個AND情境", "error"))
        for scenario in scenarios:
            actual = [canonical(c, catalog.fields)
                      for c in scenario["where"]["all"]]
            compare_conditions(actual, expected, catalog, issues, scenario["name"])
            orders = [(o["field"], o["direction"]) for o in scenario.get("sort", [])]
            if qid in SORTS and orders != SORTS[qid]:
                code = "sort_not_requested" if not orders else "sort_incomplete_or_changed"
                issues.append(issue(code, "工具未完整請求題目指定的排序，回答自行排序另由grader評分",
                                    expected=SORTS[qid], actual=orders))
            if qid in ("F08", "F10") and scenario.get("limit") != 3:
                issues.append(issue("top3_not_requested", "工具未要求limit=3，返回候選池而非直接前三款",
                                    actual=scenario.get("limit")))
            elif qid not in ("F08", "F10") and scenario.get("limit") is not None:
                issues.append(issue("unrequested_limit", "完整清單不應限筆數", "error",
                                    actual=scenario["limit"]))
    if qid == "F09":
        issues.append(issue("per_series_winners_not_requested",
                            "工具返回三系列3HP候選池，未求各系列粒徑冠軍／全部並列；需模型完成分組極值"))
    return issues, [None] * len(scenarios)


def compare_conditions(actual, rules, catalog, issues, scenario):
    desired = expected_tokens(rules, catalog.fields)
    missing = list((Counter(desired) - Counter(actual)).elements())
    extra = list((Counter(actual) - Counter(desired)).elements())
    if missing or extra:
        issues.append(issue("condition_translation", "自然語言條件與工具條件不等值，即使本次集合相同仍標錯",
                            "error", scenario=scenario, missing=missing, extra=extra))


def models(rows):
    return [row["values"]["model"] for row in rows]


def independent_and_truth(conditions, values, fields):
    """Check known/unknown/excluded by plain AND logic, without engine _match."""
    missing = False
    for condition in conditions:
        name, op, target = canonical(condition, fields)
        actual = values.get(name)
        if actual is None:
            missing = True
            continue
        if op in ("member", "member_any"):
            members = actual if isinstance(actual, list) else [actual]
            accepted = [target] if op == "member" else target
            matches = any(value in members for value in accepted)
        else:
            if fields[name].type == "text":
                actual = actual.strip().lower()
            if op == "eq":
                matches = actual == target
            elif op == "lte":
                matches = actual <= target
            elif op == "gte":
                matches = actual >= target
            elif op == "in":
                matches = actual in target
            else:
                raise ValueError(f"獨立分類尚未定義本次運算子：{op}")
        if not matches:
            return False
    return None if missing else True


def independent_partition(scenario, output, catalog):
    expected = {"matches": [], "unknown": [], "excluded": []}
    for product in catalog.products:
        state = independent_and_truth(scenario["where"]["all"],
                                      product.values, catalog.fields)
        category = "unknown" if state is None else "matches" if state else "excluded"
        expected[category].append(product.values["model"])
    returned = set(models(output["matches"]))
    known = set(expected["matches"])
    if scenario.get("limit") is not None:
        # A limit hides known matches, but cannot make unknowns into matches.
        known_ok = returned <= known and output["match_count"] == len(known)
    else:
        known_ok = returned == known and output["match_count"] == len(known)
    return {
        "known_matches_verified": known_ok,
        "unknown_models_verified": set(models(output["unknown"])) == set(expected["unknown"]),
        "excluded_count_verified": output["excluded_count"] == len(expected["excluded"]),
        "independent_known_count": len(expected["matches"]),
        "independent_unknown_count": len(expected["unknown"]),
        "independent_excluded_count": len(expected["excluded"]),
    }


def coverage(question, outputs, assignments, catalog):
    expected = question["expected_models"]
    if isinstance(expected, dict):
        groups = {}
        for label in expected:
            rows = [r for i, s in enumerate(outputs) if assignments[i] == label
                    for r in s["matches"]]
            groups[label] = set_coverage(expected[label], models(rows))
        return {"view": "separate_scenarios", "groups": groups,
                "set_match": all(g["set_match"] for g in groups.values())}
    rows = [r for scenario in outputs for r in scenario["matches"]]
    raw_models = models(rows)
    view = "raw_tool_matches"
    selected = rows
    if question["id"] in ("F08", "F10"):
        view = "first_three_from_returned_pool"
        selected = rows[:3]
    elif question["id"] == "F09":
        view = "independent_per_series_max_with_all_ties"
        series_max = {}
        for row in rows:
            values = row["values"]
            series_max[values["series"]] = max(
                series_max.get(values["series"], float("-inf")), values["solids_mm"],
            )
        selected = [row for row in rows if row["values"]["solids_mm"] ==
                    series_max[row["values"]["series"]]]
    elif question["id"] == "F16":
        view = "independent_null_selection_from_returned_series"
        selected = [row for row in rows if row["values"]["solids_mm"] is None]
    result = {"view": view, **set_coverage(expected, models(selected)),
              "raw_returned_count": len(rows),
              "raw_pool_extra_models": sorted(set(raw_models) - set(expected))}
    if question["id"] in ("F07", "F08", "F10"):
        result["order_match"] = models(selected) == expected
    if question["id"] == "F09":
        lookup = {p.values["model"]: p.values for p in catalog.products}
        result["per_series"] = {}
        for series in ("STEEL", "HIPPO DN", "LEOPARD"):
            wanted = [m for m in expected if lookup[m]["series"] == series]
            actual = [r["values"]["model"] for r in selected
                      if r["values"]["series"] == series]
            result["per_series"][series] = set_coverage(wanted, actual)
    return result


def set_coverage(expected, actual):
    return {"expected_models": expected, "selected_models": actual,
            "missing_models": sorted(set(expected) - set(actual)),
            "unexpected_models": sorted(set(actual) - set(expected)),
            "set_match": set(expected) == set(actual),
            "duplicate_models": sorted(m for m, count in Counter(actual).items()
                                       if count > 1)}


def replay_call(step, module, catalog, question):
    record = {"tool_call_id": step.get("tool_call_id")}
    original = json.loads(step["result"]) if isinstance(step["result"], str) else step["result"]
    record["status"] = original.get("status")
    record["recorded_error"] = original.get("error")
    try:
        args = json.loads(step["arguments"]) if isinstance(step["arguments"], str) else step["arguments"]
        record["arguments"] = args
        converted = module._to_query(args, catalog)
        record["converted_query"] = converted
        semantic_issues, assignments = semantics(question["id"], converted, catalog)
        record["condition_semantic_issues"] = semantic_issues
        recomputed = module.filter_products(converted, catalog)
    except Exception as exc:
        record["replay_error"] = {"type": type(exc).__name__, "message": str(exc)}
        error_same = (original.get("status") == "error"
                      and str(exc) in str(original.get("error", "")))
        record["computation_verified"] = error_same
        record["verification_kind"] = "reproduced_error"
        record.setdefault("condition_semantic_issues", []).append(issue(
            "invalid_tool_arguments", "工具參數無法完成篩選；不可把錯誤當成無候選",
            "error", error=str(exc),
        ))
        record["oracle_coverage"] = {"status": "unavailable_tool_error"}
        return record
    differences = value_diffs(original.get("data"), recomputed)
    record["computation_verified"] = original.get("status") == "ok" and not differences
    record["verification_kind"] = "all_output_values_and_order"
    record["difference_count"] = len(differences)
    record["differences"] = differences[:30]
    record["oracle_coverage"] = coverage(question, recomputed["scenarios"], assignments, catalog)
    record["independent_partitions"] = [independent_partition(query, output, catalog)
                                        for query, output in zip(converted["scenarios"],
                                                                 recomputed["scenarios"])]
    record["scenario_counts"] = [{
        "name": s["name"], "match_count": s["match_count"],
        "returned_matches": len(s["matches"]), "unknown_count": len(s["unknown"]),
        "excluded_count": s["excluded_count"],
        "partition_equals_117": s["match_count"] + len(s["unknown"]) + s["excluded_count"] == 117,
        "unknown_fields_by_model": {r["values"]["model"]: r["unknown_fields"]
                                    for r in s["unknown"]},
    } for s in recomputed["scenarios"]]
    return record


def main():
    results = read_json("results.json")
    questions = read_json("questions.json")
    frozen = read_json("question_validation.json")
    snapshot = read_json("source_snapshot.json")
    source_errors = []
    for path, text in snapshot["files"].items():
        if digest(text.encode()) != snapshot["hashes"][path]:
            source_errors.append(path)
    inputs = {name: digest((ROOT / name).read_bytes()) for name in (
        "results.json", "questions.json", "question_validation.json", "source_snapshot.json",
    )}
    if inputs["questions.json"] != frozen["questions_sha256"] or source_errors:
        raise ValueError("凍結題目或來源雜湊不符，停止稽核")
    if inputs["source_snapshot.json"] != frozen["source_snapshot_sha256"]:
        raise ValueError("來源snapshot雜湊不符")
    module = current_functions()
    catalog = frozen_catalog(module, snapshot)
    question_map = {q["id"]: q for q in questions["questions"]}
    source_code = {name: digest((REPO / name).read_bytes()) for name in MODULES}
    manifest = results["checkout"].get("source_manifest", {})
    code_matches_recorded = {name: source_code[name] == manifest.get(name) for name in MODULES}
    audits = []
    for result in results["questions"]:
        qid = result["id"]
        steps = [step for step in result.get("tool_steps", [])
                 if step.get("name") == "filter_products"]
        calls = [replay_call(step, module, catalog, question_map[qid]) for step in steps]
        issues = [item for call in calls for item in call["condition_semantic_issues"]]
        if not calls and qid in RULES:
            issues.append(issue("tool_not_called_for_selection",
                                "未呼叫篩選工具，條件／集合覆蓋不能由工具確認；回答評分另行處理"))
        if not calls:
            why = ("direct_lookup_tool_optional" if qid in DIRECT_LOOKUPS else
                   "requested_field_absent_in_catalog" if qid in ABSENT_FIELDS else
                   "no_filter_call")
            oracle_coverage = {"status": "unavailable_no_tool_call", "reason": why,
                               "expected_models": question_map[qid]["expected_models"]}
        else:
            oracle_coverage = [call["oracle_coverage"] for call in calls]
        audits.append({
            "id": qid, "repeat": result["repeat"], "tool_called": bool(calls),
            "tool_call_count": len(calls),
            "coverage_group": "F01-F17" if int(qid[1:]) <= 17 else "F18-F20",
            "usage_classification": (
                "direct_comparison_search_can_supply_specs" if qid in ("F13", "F17") else
                "selection_or_missing_spec_list" if qid in RULES else
                "price_warranty_or_combined_weight_without_filter_field"
            ),
            "status": "not_called" if not calls else calls[0]["status"] if len(calls) == 1 else "multiple_calls",
            "computation_verified": all(c["computation_verified"] for c in calls) if calls else None,
            "oracle_coverage": oracle_coverage,
            "condition_semantic_issues": issues, "calls": calls,
        })
    all_calls = [call for row in audits for call in row["calls"]]
    summary = {
        "answer_count": len(audits), "product_count": len(catalog.products),
        "tool_called_answers": sum(row["tool_called"] for row in audits),
        "no_filter_call_answers": sum(not row["tool_called"] for row in audits),
        "filter_call_count": len(all_calls),
        "successful_calls": sum(c["status"] == "ok" for c in all_calls),
        "error_calls": sum(c["status"] == "error" for c in all_calls),
        "all_values_verified_calls": sum(c["verification_kind"] == "all_output_values_and_order"
                                         and c["computation_verified"] for c in all_calls),
        "reproduced_error_calls": sum(c["verification_kind"] == "reproduced_error"
                                      and c["computation_verified"] for c in all_calls),
        "computation_mismatch_calls": sum(not c["computation_verified"] for c in all_calls),
        "independent_partition_mismatches": sum(
            not all(partition[k] for k in ("known_matches_verified", "unknown_models_verified",
                                           "excluded_count_verified"))
            for call in all_calls for partition in call.get("independent_partitions", [])
        ),
        "condition_error_answers": sum(any(i["level"] == "error" for i in row["condition_semantic_issues"])
                                        for row in audits),
        "workflow_gap_answers": sum(any(i["level"] == "tool_workflow_gap" for i in row["condition_semantic_issues"])
                                     for row in audits),
        "issue_counts": dict(Counter(i["code"] for row in audits for i in row["condition_semantic_issues"])),
    }
    summary["coverage_groups"] = {}
    for group in ("F01-F17", "F18-F20"):
        subset = [row for row in audits if row["coverage_group"] == group]
        summary["coverage_groups"][group] = {
            "answer_count": len(subset),
            "tool_called_answers": sum(row["tool_called"] for row in subset),
            "no_filter_call_answers": sum(not row["tool_called"] for row in subset),
            "successful_tool_answers": sum(any(c["status"] == "ok" for c in row["calls"])
                                           for row in subset),
            "called_answer_ids": [f"{row['id']}-R{row['repeat']}" for row in subset if row["tool_called"]],
            "uncalled_answer_ids": [f"{row['id']}-R{row['repeat']}" for row in subset if not row["tool_called"]],
        }
    report = {
        "status": "verified" if not (summary["computation_mismatch_calls"]
                                      or summary["independent_partition_mismatches"]) else "mismatch",
        "method": "現有parser與engine離線逐值重跑；自然語言條件人工轉錄，與凍結獨立oracle另行比對，不修改回答grader。",
        "input_sha256": inputs, "current_code_sha256": source_code,
        "results_sha256": inputs["results.json"],
        "code_matches_recorded_manifest": code_matches_recorded,
        "frozen_source_file_hashes_verified": len(snapshot["files"]),
        "summary": summary, "questions": audits,
        "concerns": [{"id": row["id"], "repeat": row["repeat"],
                      "issues": row["condition_semantic_issues"]}
                     for row in audits if row["condition_semantic_issues"]],
        "limitations": [
            "只稽核已記錄的工具參數與輸出，沒有重新呼叫LLM或API，沒有重新評分最終答案。",
            "F08/F10前三款、F09分系列並列冠軍、F16缺值選擇的衍生視圖是本稽核離線處理；不冒充原工具有執行這些步驟。",
            "F18/F19沒有價格／保固欄位，無工具呼叫不等於空集合證據；缺資料結論仍需由原來源及grader確認。",
            "F01-F17覆蓋固定計51份，包含F13/F17指定型號比較；兩題可由search取得規格的分類另註，不從覆蓋分母移除。F18-F20九份另列，沒有適合價格／保固／加座總重的數值filter欄位。",
        ],
    }
    expected = {(q["id"], repeat) for q in questions["questions"] for repeat in (1, 2, 3)}
    if len(audits) != 60 or {(a["id"], a["repeat"]) for a in audits} != expected:
        raise ValueError("未涵蓋完整60題次")
    (ROOT / "tool_audit.json").write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n")
    print(json.dumps(summary, ensure_ascii=False))


def self_test():
    module = current_functions()
    catalog = frozen_catalog(module, read_json("source_snapshot.json"))
    broad = canonical({"field": "phase", "op": "in", "value": [1, 1, 3]}, catalog.fields)
    if broad == expected_tokens([rule("phase", "member", 1)], catalog.fields)[0]:
        raise AssertionError("過寬相數不可因目前集合相同而當作正確")
    for op, value in (("eq", 3), ("contains", 3), ("in", [3])):
        if canonical({"field": "phase", "op": op, "value": value}, catalog.fields) != ("phase", "member", 3):
            raise AssertionError("合法合併相數等值運算子應接受")
    if not value_diffs({"x": True}, {"x": 1}):
        raise AssertionError("布林與數字不能被Python相等比較掩蓋")
    if not value_diffs(["a", "b"], ["b", "a"]):
        raise AssertionError("逐值核對必須包含排序")
    conditions = [{"field": "max_head_m", "op": "gte", "value": 20},
                  {"field": "hp", "op": "lte", "value": 3}]
    if independent_and_truth(conditions, {"max_head_m": None, "hp": 5},
                             catalog.fields) is not False:
        raise AssertionError("已有確定不符時，不能因另一欄缺值變成未知")
    if independent_and_truth(conditions, {"max_head_m": None, "hp": 2},
                             catalog.fields) is not None:
        raise AssertionError("沒有確定不符時，缺值應為未知")
    print("offline audit self-test passed")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--self-test", action="store_true")
    arguments = parser.parse_args()
    self_test() if arguments.self_test else main()
