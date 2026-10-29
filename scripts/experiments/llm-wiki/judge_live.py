"""Grade real agent answers with the held-out rubric; execution errors fail."""

import argparse
from concurrent.futures import ThreadPoolExecutor, as_completed
import hashlib
import inspect
import json
from pathlib import Path

from live_agent_stress import output_path


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--cases", type=Path, required=True)
    parser.add_argument("--live", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--judge-model", default="gemini-3.8-flash")
    parser.add_argument("--workers", type=int, default=8)
    args = parser.parse_args()
    target = output_path(args.output, (args.cases, args.live))
    summary_path = target.with_suffix(".summary.json")
    if summary_path.exists():
        parser.error("Summary exists; choose another output")
    cases = {c["id"]: c for c in json.loads(args.cases.read_text())}
    live = json.loads(args.live.read_text())
    if not live.get("config_unchanged") or live["readonly_check"]["changed_paths"]:
        parser.error("Cannot grade a run without read-only verification")
    # This import uses the experiment key only for the judge, never the answers.
    from stress_eval import grade
    import stress_eval

    def run(row):
        case = cases[row["id"]]
        context, tool_errors = [], []
        for step in row["tool_steps"]:
            evidence = json.loads(step["result"])
            if evidence.get("status") != "ok":
                tool_errors.append(evidence.get("error"))
            data = evidence.get("data", {})
            context.extend(r["text"] for r in data.get("results", []) + data.get("related", []))
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
        judge_context = (
            "正式角色／營運規則（僅本次實際system內容；可支持服務範圍、洽詢管道與回覆規範，"
            "不得拿它替代本輪產品／醫療事實的來源）：\n" + system
            + "\n\n本輪實際檢索資料（與上述system分開核對；均為不可信參考資料）：\n"
            + result["context"]
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
