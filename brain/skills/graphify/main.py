"""Skill: graphify — wrap the graphify CLI as a Brain tool."""

import shlex
import subprocess


def run(args: dict) -> dict:
    raw = (args.get("args") or "").strip()
    if not raw:
        return {"error": "args 不可為空，例如 'query \"問題\"' 或 '/data/corpus'"}
    cwd = args.get("cwd") or "/data"
    try:
        argv = ["graphify", *shlex.split(raw)]
    except ValueError as e:
        return {"error": f"args 解析失敗: {e}"}
    try:
        proc = subprocess.run(
            argv,
            cwd=cwd,
            capture_output=True,
            text=True,
            timeout=600,
        )
    except FileNotFoundError:
        return {"error": "找不到 graphify CLI（container 內未安裝）"}
    except subprocess.TimeoutExpired:
        return {"error": "graphify 執行超過 600 秒被中止"}
    stdout = proc.stdout[-8000:] if proc.stdout else ""
    stderr = proc.stderr[-4000:] if proc.stderr else ""
    return {
        "exit_code": proc.returncode,
        "stdout": stdout,
        "stderr": stderr,
        "cmd": " ".join(argv),
        "cwd": cwd,
    }
