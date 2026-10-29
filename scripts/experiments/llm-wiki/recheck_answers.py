"""Replay a final check on unchanged real answers, keeping paired provenance."""

import argparse
from concurrent.futures import ThreadPoolExecutor, as_completed
from contextvars import copy_context
import hashlib
import inspect
import json
from pathlib import Path
import subprocess

from live_agent_stress import HERE, answering_cases, output_path


def parallel_checks(rows, run, workers):
    # Project credentials live in ContextVars; every worker needs its own copy.
    with ThreadPoolExecutor(max_workers=workers) as executor:
        futures = {executor.submit(copy_context().run, run, row): index
                   for index, row in enumerate(rows)}
        for future in as_completed(futures):
            yield futures[future], future.result()


def restore_draft(row):
    check = row.pop("answer_check", None)
    if check is None:
        return
    row["source_answer_check"] = check
    row["answer"] = check["original_answer"]
    error = row.get("error")
    if error and (error["type"] == "AnswerCheckFailed" or
                  error["message"] == "Answer evidence check failed; attempts retained"):
        row["source_check_error"] = error
        row["error"] = None


SCRIPT = r'''
import copy
from concurrent.futures import ThreadPoolExecutor, as_completed
from contextlib import ExitStack
from contextvars import copy_context
import hashlib
import json
import logging
from pathlib import Path
import sys
import time
import types
from unittest.mock import patch

logging.disable(logging.CRITICAL)
p=json.load(sys.stdin)
exec(p["restore_source"], globals())
exec(p["parallel_source"], globals())
runtime=types.ModuleType("readonly_runtime");sys.modules[runtime.__name__]=runtime
exec(p["runtime"],runtime.__dict__)
checker=types.ModuleType("answer_check");exec(p["checker"],checker.__dict__)
from core import llm_client,provider_router
from core.gemini_credentials import project_model_scope
from infra import project_context,usage_ledger
root=project_context.resolve_project_context(p["live"]["project_id"]).project_root
before=runtime._manifest(root)
data=copy.deepcopy(p["live"])
cases={c["id"]:c for c in p["cases"]}
records=[]
with runtime.readonly_search(data["project_id"],persona_id=data["persona_id"]), project_model_scope(data["project_id"]), ExitStack() as stack:
    stack.enter_context(patch.object(llm_client,"record_usage_event",lambda **_:None))
    stack.enter_context(patch.object(usage_ledger,"record_usage_event",lambda **_:None))
    stack.enter_context(patch.object(provider_router,"record_error_event",lambda **_:None))
    def generate(messages, **kwargs):
        return llm_client.generate_chat_turn(messages, model_override=p["check_model"], **kwargs)
    def run(row):
        case=cases[row["id"]]
        if p["restore_drafts"]:restore_draft(row)
        row["precheck_answer"]=row["answer"]
        evidence=[item for step in row["tool_steps"] for field in ("results","related")
                  for item in json.loads(step["result"]).get("data",{}).get(field,[])]
        hint=str(case.get("lang","")).lower()
        language="es" if hint.startswith("es") else "en" if hint.startswith("en") else "zh"
        start=time.perf_counter()
        result=checker.check_answer(question=case["q"],history=row["prompt_messages"][1:-1],
            evidence=evidence,answer=row["answer"],language=language,
            operational_rules=row["prompt_messages"][0]["content"],generate=generate,allow_repair=p["repair"])
        row["answer_check"]=result
        row["answer"]=result["final_answer"]
        row["check_time_ms"]=round((time.perf_counter()-start)*1000,2)
        if result.get("error"):row["error"]={"type":"AnswerCheckFailed","message":result["error"]}
        return row
    pending=[r for r in data["records"] if r["variant"]==p["profile"]]
    ordered={}
    for index,row in parallel_checks(pending,run,p["workers"]):
        ordered[index]=row
        print(json.dumps({"event":"checkpoint","record":row},ensure_ascii=False),flush=True)
    records=[ordered[i] for i in sorted(ordered)]
after=runtime._manifest(root)
if before!=after:raise RuntimeError("Production project files changed")
data["records"]=records
data["errors"]=[{"id":r["id"],"error":r["error"]} for r in records if r.get("error")]
data["answer_check_policy"]="evidence_check_v13" if p["repair"] else "evidence_check_v10"
data["answer_check_model_override"]=p["check_model"]
data["answer_check_source_sha256"]=hashlib.sha256(p["checker"].encode()).hexdigest()
data["check_readonly"]={"file_count":len(before),"changed_paths":[]}
data["answer_check_workers"]=p["workers"]
data["check_restore_drafts"]=p["restore_drafts"]
data["source_run_differences"]=data.get("differences",[])
data["differences"]=["Post-agent check replay; original saved draft/context restored when explicitly requested; no new retrieval", "Optional single newly generated repair with independent full verification" if p["repair"] else "No repair generation"]
data["check_mode"]="Original saved draft/context replay; optional one newly generated and independently checked repair; no new retrieval" if p["repair"] else "Replay of unchanged actual answer/context; no regeneration or new retrieval"
print(json.dumps(data,ensure_ascii=False))
'''


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    for name in ("cases","live","output"):parser.add_argument("--"+name,type=Path,required=True)
    parser.add_argument("--profile",default="focused_v2")
    parser.add_argument("--check-model", default=None)
    parser.add_argument("--repair", action="store_true")
    parser.add_argument("--workers",type=int,default=1)
    parser.add_argument("--original-drafts", action="store_true",
                        help="Restore the actual saved draft before an earlier check; keep earlier failures as provenance")
    args=parser.parse_args()
    if not 1 <= args.workers <= 8:parser.error("workers must be 1..8")
    target=output_path(args.output,[args.cases,args.live])
    checkpoint=output_path(target.with_suffix(".checkpoint.jsonl"),[args.cases,args.live])
    cases=json.loads(args.cases.read_text());live=json.loads(args.live.read_text())
    if not live.get("config_unchanged") or live["readonly_check"]["changed_paths"]:
        parser.error("Original run did not pass readonly verification")
    if any("answer_check" in row for row in live["records"]) and not args.original_drafts:
        parser.error("Input already checked; use --original-drafts to recheck the actual saved original")
    payload={"repair":args.repair,"parallel_source":inspect.getsource(parallel_checks),"workers":args.workers,"restore_source":inspect.getsource(restore_draft),"restore_drafts":args.original_drafts,"cases":answering_cases(cases),"live":live,"profile":args.profile,
             "check_model":args.check_model,"runtime":(HERE/"readonly_runtime.py").read_text(),"checker":(HERE/"answer_check.py").read_text()}
    process=subprocess.Popen(["docker","exec","-i","-w","/app","openvman-api-1","python","-c",SCRIPT],
                             stdin=subprocess.PIPE,stdout=subprocess.PIPE,stderr=subprocess.PIPE,text=True)
    process.stdin.write(json.dumps(payload,ensure_ascii=False));process.stdin.close()
    data=None;count=0
    with checkpoint.open("x") as stream:
        for line in process.stdout:
            if not line.startswith("{"):continue
            item=json.loads(line)
            if item.get("event")=="checkpoint":
                stream.write(json.dumps(item["record"],ensure_ascii=False)+"\n");stream.flush();count+=1
                print(json.dumps({"checked":count,"id":item["record"]["id"],"error":bool(item["record"]["error"])}),flush=True)
            else:data=item
    process.stderr.read();status=process.wait()
    if status or data is None:raise SystemExit("Check process failed; checkpoint retained")
    data["check_input_sha256"]={str(p):hashlib.sha256(p.read_bytes()).hexdigest() for p in (args.cases,args.live)}
    target.write_text(json.dumps(data,ensure_ascii=False,indent=1))
    print(json.dumps({"answers":count,"errors":len(data["errors"]),"output":str(target)}))


if __name__=="__main__":main()
