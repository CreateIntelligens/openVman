"""Run disposable experiment code inside the existing API container."""

import json
from pathlib import Path
import subprocess
import sys


ROOT = Path(__file__).resolve().parent
PREFIX = "PRODUCT_NOTES_EVENT "


def write_json(name, data):
    (ROOT / name).write_text(
        json.dumps(data, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )


def mirror_check(name):
    result = subprocess.run(
        [sys.executable, "scripts/project_mirror.py", "check"],
        cwd=ROOT.parents[3], capture_output=True, text=True,
    )
    write_json(name, {
        "command": "python3 scripts/project_mirror.py check",
        "exit_code": result.returncode,
        "stdout": result.stdout, "stderr": result.stderr,
    })
    if result.returncode:
        raise RuntimeError("鏡像檢查失敗；沒有執行同步")


def run_container(payload, checkpoint):
    # Only stdout artifacts return to this directory; /data stays read-only.
    code = "DATA = " + repr(payload) + "\n"
    code += "import types, sys\n"
    code += "filter_module = types.ModuleType(\"filter_engine\")\n"
    code += "sys.modules[\"filter_engine\"] = filter_module\n"
    code += (
        "exec(" + repr((ROOT / "filter_engine.py").read_text())
        + ", filter_module.__dict__)\n"
    )
    code += (ROOT / "runtime.py").read_text(encoding="utf-8")
    process = subprocess.Popen(
        ["docker", "exec", "-i", "-w", "/app",
         "openvman-api-1", "python3", "-B", "-"],
        stdin=subprocess.PIPE, stdout=subprocess.PIPE, text=True,
    )
    process.stdin.write(code)
    process.stdin.close()
    events = []
    result = None
    for line in process.stdout:
        if not line.startswith(PREFIX):
            print(line.rstrip(), file=sys.stderr)
            continue
        event = json.loads(line[len(PREFIX):])
        events.append(event)
        write_json(checkpoint, events)
        if event["type"] == "result":
            result = event["data"]
            full = result["integrity"].pop("full", None)
            if full is not None:
                write_json(payload["operation"] + ".full.json", full)
        else:
            print(event["type"], event.get("label", ""), flush=True)
    if process.wait() or result is None:
        raise RuntimeError("容器實驗失敗；已保留 checkpoint，不自動重試")
    return result
