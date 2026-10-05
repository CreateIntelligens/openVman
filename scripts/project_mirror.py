"""Keep a test project identical to the production project it mirrors.

在測試專案上跑實驗（語音模擬、提示詞比較）才不會把測試對話寫進正式專案的對話紀錄
與每日記憶摘要。測試專案要跟正式專案一樣才有參考價值，所以這支腳本負責兩件事：

    python3 scripts/project_mirror.py check            # 有差異就列出來、exit 1
    python3 scripts/project_mirror.py sync             # 正式 → 測試，先備份測試專案再重建索引

在 repo 根目錄、主機上執行；檔案操作都在 api 容器裡做（docker compose exec）。
只比對「決定行為」的檔案：知識庫、原始資料、詞表、人設、文件設定、語言分流，
以及檢索時用的知識圖譜鄰接表（LanceDB `note_graph`，Graph RAG 靠它多帶相關文件）。
對話、記憶、夢境整理不比對：那些是使用產生的，本來就該不同。
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

# 測試專案 → 它鏡像的正式專案。
MIRRORS = {
    "dev-c0c8fdff34": "proj-0cc5c610b4",  # 鶴記dev → 鶴記
}

_IN_CONTAINER = r'''
import hashlib, json, os, shutil, sys, time, urllib.request
from pathlib import Path

sys.path.insert(0, "/app")
from infra.db import get_db

action, source, target = sys.argv[1:4]
projects = Path("/data/projects")
# 決定行為的檔案與目錄（相對於 workspace）。
MIRRORED = ["knowledge", "raw", "personas", "ASR_PROMPT.md", "SOUL.md", "IDENTITY.md",
            "AGENTS.md", "TOOLS.md", ".doc_meta.json", ".kb_settings.json"]


def fingerprints(project):
    workspace = projects / project / "workspace"
    out = {}
    for name in MIRRORED:
        path = workspace / name
        paths = [path] if path.is_file() else sorted(p for p in path.rglob("*") if p.is_file())
        for item in paths:
            out[str(item.relative_to(workspace))] = hashlib.md5(item.read_bytes()).hexdigest()
    rows = note_graph_rows(project)
    if rows is not None:
        out["lancedb:note_graph"] = hashlib.md5(json.dumps(rows, sort_keys=True).encode()).hexdigest()
    return out


def note_graph_rows(project):
    db = get_db(project)
    if "note_graph" not in db.table_names():
        return None
    return sorted(db.open_table("note_graph").to_arrow().to_pylist(), key=lambda row: row["source_file"])


def drift():
    src, dst = fingerprints(source), fingerprints(target)
    return {
        "only_in_source": sorted(set(src) - set(dst)),
        "only_in_target": sorted(set(dst) - set(src)),
        "changed": sorted(k for k in set(src) & set(dst) if src[k] != dst[k]),
    }


if action == "check":
    print(json.dumps(drift(), ensure_ascii=False))
    sys.exit(0)

src_ws, dst_ws = projects / source / "workspace", projects / target / "workspace"
backup = Path("/data/backups") / f"mirror-{target}-{time.strftime('%Y%m%d-%H%M%S')}"
backup.mkdir(parents=True)
for name in MIRRORED + ["graphify-out"]:
    if (dst_ws / name).exists():
        (shutil.copytree if (dst_ws / name).is_dir() else shutil.copy2)(dst_ws / name, backup / name)
for name in MIRRORED:
    src, dst = src_ws / name, dst_ws / name
    if dst.is_dir():
        shutil.rmtree(dst)
    elif dst.exists():
        dst.unlink()
    if src.is_dir():
        shutil.copytree(src, dst)
    elif src.exists():
        shutil.copy2(src, dst)
# 知識圖譜由 LLM 抽取，重建要花模型呼叫；內容相同就直接沿用正式專案建好的結果，
# 只有兩個狀態檔寫了專案代號。
if (src_ws / "graphify-out").exists():
    shutil.rmtree(dst_ws / "graphify-out", ignore_errors=True)
    shutil.copytree(src_ws / "graphify-out", dst_ws / "graphify-out")
    for name in ("status.json", "summary.json"):
        path = dst_ws / "graphify-out" / name
        if path.exists():
            path.write_text(path.read_text(encoding="utf-8").replace(source, target), encoding="utf-8")
    if (projects / source / "graph_index_state.json").exists():
        shutil.copy2(projects / source / "graph_index_state.json", projects / target / "graph_index_state.json")
# 鄰接表在 LanceDB 裡，複製 graphify-out 不會帶過去；少了它測試專案的檢索不會做圖譜擴充。
# 列裡只有相對 workspace 的路徑，不含專案代號，可以原樣寫入。
rows = note_graph_rows(source)
if rows:
    get_db(target).create_table("note_graph", data=rows, mode="overwrite")
request = urllib.request.Request(
    "http://localhost:8100/brain/knowledge/reindex", method="POST",
    headers={"X-Internal-Token": os.environ["GATEWAY_INTERNAL_TOKEN"], "Content-Type": "application/json"},
    data=json.dumps({"project_id": target}).encode(),
)
result = json.loads(urllib.request.urlopen(request, timeout=900).read())
print(json.dumps({"backup": str(backup), "reindex": result, "drift": drift()}, ensure_ascii=False))
'''


def run_in_container(action: str, source: str, target: str) -> dict:
    result = subprocess.run(
        ["docker", "compose", "exec", "-T", "api", "python3", "-", action, source, target],
        input=_IN_CONTAINER, capture_output=True, text=True, cwd=ROOT,
    )
    if result.returncode != 0:
        sys.exit(f"api 容器執行失敗：{result.stderr.strip()[-500:]}")
    return json.loads(result.stdout.strip().splitlines()[-1])


def has_drift(report: dict) -> bool:
    return any(report[key] for key in ("only_in_source", "only_in_target", "changed"))


def check(target: str) -> bool:
    """True when the test project matches its production project."""
    report = run_in_container("check", MIRRORS[target], target)
    if not has_drift(report):
        return True
    print(f"{target} 跟 {MIRRORS[target]} 不一樣：", file=sys.stderr)
    for key, label in (("only_in_source", "測試專案缺少"), ("only_in_target", "測試專案多出"), ("changed", "內容不同")):
        for path in report[key]:
            print(f"  {label}：{path}", file=sys.stderr)
    print(f"同步：python3 scripts/project_mirror.py sync --target {target}", file=sys.stderr)
    return False


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("action", choices=["check", "sync"])
    parser.add_argument("--target", default=next(iter(MIRRORS)), choices=sorted(MIRRORS))
    args = parser.parse_args(argv)
    if args.action == "check":
        sys.exit(0 if check(args.target) else 1)
    report = run_in_container("sync", MIRRORS[args.target], args.target)
    reindex = report["reindex"]
    print(f"已同步 {MIRRORS[args.target]} → {args.target}；備份在 api 容器 {report['backup']}；"
          f"索引 {reindex.get('document_count')} 份文件、{reindex.get('chunk_count')} 段")
    if has_drift(report["drift"]):
        sys.exit(f"同步後仍有差異：{report['drift']}")


if __name__ == "__main__":
    main()
