import json
rows = json.load(open("rows.json"))
PLANTS = [
    ("P1", "門診時間表.csv", "9", "08:30-11:30", "08:30-10:00", "健檢_IMG_A1-1.csv#1"),
    ("P2", "各科介紹.csv", "6", "C醫師、B醫師、A醫師", "C醫師、B醫師", "門診時間表.csv#2"),
    ("P3", "各科介紹.csv", "8", "(02) 8792-8888", "(02) 8792-6666", "醫院資訊.csv#14"),
    ("P4", "門診.csv", "2", "最後10分鐘前", "最後30分鐘前", "醫院資訊.csv#12"),
    ("P5", "1-痛風.csv", "17", "但發作期間仍需避免含糖咖啡。", "發作期間喝含糖咖啡也沒關係，糖分不影響尿酸。", "1-痛風.csv#28"),
]
truth = []
for pid, f, idx, old, new, counterpart in PLANTS:
    hit = [r for r in rows if r["file"] == f and r["index"] == idx]
    assert len(hit) == 1 and old in hit[0]["a"], (pid, hit)
    hit[0]["a"] = hit[0]["a"].replace(old, new)
    truth.append({"id": pid, "row": f"{f}#{idx}", "counterpart": counterpart})
json.dump(rows, open("rows_planted.json", "w"), ensure_ascii=False, indent=0)
json.dump(truth, open("plants.json", "w"), ensure_ascii=False, indent=1)
print("planted", len(truth))
