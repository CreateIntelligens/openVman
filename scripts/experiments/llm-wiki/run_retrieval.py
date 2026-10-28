"""把 retrieval_all.py 丟進 openvman-api-1 容器執行（唯讀），結果寫成 retrieval_all.json。

需要環境變數 LLM_WIKI_PROJECT（要測的專案 ID）。
"""
import json
import os
import pathlib
import subprocess

here = pathlib.Path(__file__).resolve().parent
payload = {
    "project_id": os.environ["LLM_WIKI_PROJECT"],
    "sections": json.load(open("wiki_sections.json")),
    "pages": json.load(open("wiki/pages.json")),
    "questions": json.load(open(here / "questions.json")),
}
r = subprocess.run(
    ["docker", "exec", "-i", "-w", "/app", "openvman-api-1", "python", "-c", (here / "retrieval_all.py").read_text()],
    input=json.dumps(payload, ensure_ascii=False), capture_output=True, text=True,
)
if r.returncode:
    raise SystemExit(r.stderr[-2000:])
out = json.loads([l for l in r.stdout.splitlines() if l.startswith("{")][-1])
json.dump(out, open("retrieval_all.json", "w"), ensure_ascii=False)
print(len(out), "questions")
