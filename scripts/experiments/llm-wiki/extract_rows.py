"""把專案 QA CSV 攤平成 rows.json。用法：python3 extract_rows.py <QA CSV 目錄>（在產出目錄執行）"""
import csv
import glob
import json
import os
import sys

rows = []
for path in sorted(glob.glob(os.path.join(sys.argv[1], "*.csv"))):
    with open(path, encoding="utf-8-sig") as fh:
        for r in csv.DictReader(fh):
            q, a = (r.get("q") or "").strip(), (r.get("a") or "").strip()
            if q or a:
                rows.append({"file": os.path.basename(path), "index": r.get("index"), "q": q, "a": a})
json.dump(rows, open("rows.json", "w"), ensure_ascii=False, indent=0)
print(len(rows), "rows")
