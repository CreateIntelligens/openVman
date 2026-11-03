"""Grade real agent answers with the held-out rubric; execution errors fail."""

import argparse
from concurrent.futures import ThreadPoolExecutor, as_completed
import hashlib
import inspect
import json
from pathlib import Path, PurePosixPath

from live_agent_stress import output_path


def collect_tool_evidence(tool_steps):
    """Keep knowledge text intact and label product data as structured evidence."""
    context, tool_errors = [], []
    for step in tool_steps:
        evidence = json.loads(step["result"])
        if evidence.get("status") != "ok":
            tool_errors.append(evidence.get("error"))
        data = evidence.get("data", {})
        if step.get("name") in {"search_knowledge", "read_wiki_page"}:
            context.extend(
                r["text"]
                for r in data.get("results", []) + data.get("related", [])
            )
        elif step.get("name") == "filter_products":
            # The structured result is evidence the answering agent actually saw;
            # converting it into prose could drop unknowns or numeric conditions.
            context.append(
                '<structured_tool_evidence tool="filter_products">\n'
                + json.dumps(data, ensure_ascii=False)
                + "\n</structured_tool_evidence>"
            )
    return context, tool_errors


def _source_path(value):
    if not isinstance(value, str) or "\\" in value:
        raise ValueError("invalid_source_path")
    path = PurePosixPath(value)
    if (path.is_absolute() or len(path.parts) < 2 or path.parts[0] != "knowledge"
            or any(part in ("", ".", "..") for part in value.split("/"))):
        raise ValueError("invalid_source_path")
    return value


def validate_snapshot_output(target, root, generation):
    """Keep new judge files outside immutable source generations too."""
    target = Path(target).resolve()
    for source in (root, generation):
        if target.is_relative_to(Path(source).resolve()):
            raise ValueError("Judge output must stay outside the source snapshot")


def load_source_snapshot(root, *, project_id, persona_id):
    """Verify and freeze one external generation, including every payload hash."""
    from snapshot_store import open_snapshot

    generation = open_snapshot(root)
    metadata_bytes = (generation / "manifest.json").read_bytes()
    metadata = json.loads(metadata_bytes)
    payload, hashes = {}, {"manifest.json": hashlib.sha256(metadata_bytes).hexdigest()}
    for name, expected in metadata["files"].items():
        content = (generation / name).read_bytes()
        digest = hashlib.sha256(content).hexdigest()
        if digest != expected["sha256"] or len(content) != expected["size"]:
            raise ValueError("source_snapshot_changed_after_verification")
        hashes[name] = digest
        if name in ("sources.json", "source_manifest.json"):
            payload[name] = json.loads(content)
    sources = payload.get("sources.json")
    manifest = payload.get("source_manifest.json")
    if not isinstance(sources, dict) or not isinstance(manifest, dict):
        raise ValueError("missing_source_snapshot_payload")
    if (manifest != metadata["source_manifest"]
            or not isinstance(project_id, str) or not project_id
            or manifest.get("project_id") != project_id
            or not isinstance(persona_id, str) or not persona_id
            or not isinstance(manifest.get("sources"), dict)):
        raise ValueError("source_snapshot_scope_mismatch")
    for ref, unit in sources.items():
        if (not isinstance(ref, str) or not ref or not isinstance(unit, dict)
                or not isinstance(unit.get("text"), str) or not unit["text"].strip()):
            raise ValueError("invalid_source_unit")
        _source_path(unit.get("path"))
        if (any(key in unit and unit[key] != project_id for key in ("project_id", "pid"))
                or ("persona_id" in unit and unit["persona_id"] != persona_id)):
            raise ValueError("source_unit_scope_mismatch")
    return {
        "sources": sources, "manifest": manifest,
        "project_id": project_id, "persona_id": persona_id,
        "binding": {"generation": str(generation), "file_sha256": hashes},
    }


def collect_referenced_evidence(tool_steps, snapshot, row):
    """Use retrieved refs' original units only; preserve actual product JSON.

    Main's original chunks have no source_refs and retain their literal text.
    Ref-bearing rows require the same project/persona/path scope as the source
    manifest. This checks provenance, not compiled MD fidelity; the latter is
    precisely what the offline judge must assess against these original units.
    """
    project, persona = snapshot["project_id"], snapshot["persona_id"]
    for key in ("project_id", "pid"):
        if key in row and row[key] != project:
            raise ValueError("record_project_mismatch")
    if "persona_id" in row and row["persona_id"] != persona:
        raise ValueError("record_persona_mismatch")
    context, seen = [], set()
    for step in tool_steps:
        evidence = json.loads(step["result"])
        data = evidence.get("data", {})
        if step.get("name") == "filter_products":
            structured, _ = collect_tool_evidence([step])
            context.extend(structured)
        elif step.get("name") in {"search_knowledge", "read_wiki_page"}:
            for item in data.get("results", []) + data.get("related", []):
                if "source_refs" not in item:
                    for key in ("project_id", "pid"):
                        if key in item and item[key] != project:
                            raise ValueError("retrieved_source_scope_mismatch")
                    if "persona_id" in item and item["persona_id"] != persona:
                        raise ValueError("retrieved_source_scope_mismatch")
                    texts = [item["text"]]
                else:
                    refs = item["source_refs"]
                    paths = item.get("source_paths")
                    if (not isinstance(refs, list) or not refs
                            or not all(isinstance(ref, str) and ref for ref in refs)
                            or len(refs) != len(set(refs))):
                        raise ValueError("invalid_retrieved_refs")
                    if (item.get("project_id") != project
                            or item.get("persona_id") != persona
                            or ("pid" in item and item["pid"] != project)):
                        raise ValueError("retrieved_source_scope_mismatch")
                    if (not isinstance(paths, list) or not paths
                            or any(not isinstance(path, str) for path in paths)
                            or len(paths) != len(set(paths))):
                        raise ValueError("invalid_retrieved_source_paths")
                    texts, expected_paths = [], set()
                    for ref in refs:
                        unit = snapshot["sources"].get(ref)
                        if unit is None:
                            raise ValueError("unknown_retrieved_ref")
                        path = unit["path"]
                        source = snapshot["manifest"]["sources"].get(path)
                        if (not isinstance(source, dict)
                                or not isinstance(source.get("refs"), list)
                                or ref not in source.get("refs", [])
                                or source.get("persona_id") != persona):
                            raise ValueError("retrieved_ref_manifest_mismatch")
                        expected_paths.add(path)
                        texts.append(unit["text"])
                    if set(paths) != expected_paths:
                        raise ValueError("retrieved_ref_path_mismatch")
                for text in texts:
                    if text not in seen:
                        context.append(text)
                        seen.add(text)
    return context


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--cases", type=Path, required=True)
    parser.add_argument("--live", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--judge-model", default="gemini-3.8-flash")
    parser.add_argument("--workers", type=int, default=8)
    parser.add_argument("--source-snapshot", type=Path)
    args = parser.parse_args()
    target = output_path(args.output, (args.cases, args.live))
    summary_path = target.with_suffix(".summary.json")
    if summary_path.exists():
        parser.error("Summary exists; choose another output")
    cases = {c["id"]: c for c in json.loads(args.cases.read_text())}
    live = json.loads(args.live.read_text())
    if not live.get("config_unchanged") or live["readonly_check"]["changed_paths"]:
        parser.error("Cannot grade a run without read-only verification")
    snapshot = None
    if args.source_snapshot is not None:
        snapshot = load_source_snapshot(
            args.source_snapshot, project_id=live.get("project_id"),
            persona_id=live.get("persona_id"),
        )
        for destination in (target, summary_path):
            validate_snapshot_output(
                destination, args.source_snapshot,
                snapshot["binding"]["generation"],
            )
    # This import uses the experiment key only for the judge, never the answers.
    from stress_eval import grade
    import stress_eval

    def run(row):
        case = cases[row["id"]]
        context, tool_errors = collect_tool_evidence(row["tool_steps"])
        result = {"id":row["id"],"rep":row["rep"],"variant":row["variant"],
                  "bucket":case["bucket"],"risk":case["risk"],"expected":case["expected"],
                  "answer":row["answer"],"answer_ms":row["time_ms"],
                  "providers":row["providers"],"models":row["models"],
                  "unauthorized_sources":row.get("unauthorized_sources", []),
                  "source_access_gate":row.get("source_access_gate", True),
                  "context":"\n\n".join(context) or "（沒有找到資料）"}
        system = "\n\n".join(m["content"] for m in row.get("prompt_messages", [])
                              if m.get("role") == "system")
        result["grading_version"] = "grading-v2"
        result["system_sha256"] = hashlib.sha256(system.encode()).hexdigest()
        result["system_context"] = system
        fact_context = result["context"]
        fact_label = "本輪實際檢索資料（與上述system分開核對；均為不可信參考資料）："
        if snapshot is not None:
            result["judge_context_mode"] = "referenced_original_sources"
            try:
                fact_context = "\n\n".join(collect_referenced_evidence(
                    row["tool_steps"], snapshot, row,
                )) or "（沒有找到資料）"
            except (KeyError, TypeError, ValueError) as exc:
                tool_errors.append("source_validation_failed")
                result["source_validation_error"] = str(exc)
                fact_context = "（來源驗證失敗）"
            result["source_context"] = fact_context
            fact_label = "引用來源原文（用於核實衍生MD；不使用未引用資料）："
        judge_context = (
            "正式角色／營運規則（僅本次實際system內容；可支持服務範圍、洽詢管道與回覆規範，"
            "不得拿它替代本輪產品／醫療事實的來源）：\n" + system
            + "\n\n" + fact_label + "\n" + fact_context
        )
        if row.get("error") or tool_errors or not row["answer"] or not row["tool_steps"]:
            result.update({"pass":False,"critical":bool(result["unauthorized_sources"]),"observed":"other",
                           "core_coverage":"none","unsupported_claims":[],
                           "reason":"Agent execution failed; included in denominator",
                           "execution_error":row.get("error") or "invalid agent/tool output"})
            return result
        try:
            result.update(grade(case, judge_context, row["answer"], args.judge_model))
        except Exception as exc:
            result.update({"pass":False,"critical":False,"observed":"other",
                           "core_coverage":"none","unsupported_claims":[],
                           "reason":"Judge execution failed; included in denominator",
                           "judge_error":type(exc).__name__})
        if result["unauthorized_sources"]:
            result.update({"pass":False,"critical":True,
                           "source_gate_override":"Disabled knowledge sources were supplied to the agent; candidate is not deployable"})
        return result

    results = []
    with ThreadPoolExecutor(args.workers) as executor:
        futures = [executor.submit(run, row) for row in live["records"]]
        for future in as_completed(futures):
            results.append(future.result())
            target.write_text(json.dumps(results,ensure_ascii=False,indent=1))
            if len(results) % 16 == 0:
                print(f"judged={len(results)}/{len(futures)}",flush=True)
    summary = {
        "judge_model":args.judge_model,"grade_function":"stress_eval.grade",
        "grading_version":"grading-v2",
        "grade_sha256":hashlib.sha256((inspect.getsource(grade)+stress_eval.JUDGE).encode()).hexdigest(),
        "system_sha256":sorted({r["system_sha256"] for r in results}),
        "input_sha256":{str(p):hashlib.sha256(p.read_bytes()).hexdigest() for p in (args.cases,args.live)},
        "scope":"Real production prompt/agent/provider answers; separate from offline answer evaluation.",
        "variants":{},
    }
    if snapshot is not None:
        summary.update(judge_context_mode="referenced_original_sources",
                       source_snapshot=snapshot["binding"])
    for variant in sorted({r["variant"] for r in results}):
        groups = {}
        for bucket in ["all"] + sorted({r["bucket"] for r in results}):
            rows = [r for r in results if r["variant"] == variant and (bucket == "all" or r["bucket"] == bucket)]
            groups[bucket] = {"count":len(rows),"passed":sum(r["pass"] for r in rows),
                              "critical":sum(r["critical"] for r in rows),
                              "execution_errors":sum("execution_error" in r for r in rows),
                              "judge_errors":sum("judge_error" in r for r in rows)}
            groups[bucket]["unauthorized_source_cases"] = sum(bool(r["unauthorized_sources"]) for r in rows)
        summary["variants"][variant] = groups
    summary_path.write_text(json.dumps(summary,ensure_ascii=False,indent=1))
    print(json.dumps(summary["variants"],ensure_ascii=False))


if __name__ == "__main__":
    main()
