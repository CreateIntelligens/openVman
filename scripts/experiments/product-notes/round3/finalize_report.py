"""Merge 240 reviewed grades and update the existing parent report in place."""

from datetime import datetime
import hashlib
import json
from pathlib import Path
import re
import statistics
from zoneinfo import ZoneInfo


ROOT = Path(__file__).resolve().parent
ARMS = ("A", "B", "C", "D")
VERDICTS = ("對", "部分對", "錯")
RANK = {"錯": 0, "部分對": 1, "對": 2}
TOKEN_KEYS = ("input_tokens", "output_tokens", "total_tokens",
              "cached_tokens", "reasoning_tokens")
GRADE_FIELDS = {"id", "repeat", "arm", "verdict", "reason",
                "matched_points", "missing_points", "false_claims",
                "source_lines", "quality_issues"}


def read(name):
    return json.loads((ROOT / name).read_text(encoding="utf-8"))


def write(name, value):
    (ROOT / name).write_text(
        json.dumps(value, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8")


def verify_grading_inputs(result):
    current = {(r["id"], r["repeat"], arm): answer
               for r in result["questions"] for arm, answer in r["answers"].items()}
    verified = set()
    packs = {}
    paths = sorted(ROOT.glob("answers_for_grading_*.json"))
    assert paths, "缺少當次回答評分輸入pack，不可沿用無法核對的評分"
    for path in paths:
        content = json.loads(path.read_text(encoding="utf-8"))
        rows = content if isinstance(content, list) else content["answers"]
        pack_keys = set()
        for row in rows:
            repeat = int(row["repeat"])
            for arm, answer in row["answers"].items():
                key = (row["id"], repeat, arm)
                assert key in current and key not in verified, (path.name, key)
                text = answer if isinstance(answer, str) else answer["answer"]
                assert text == current[key]["answer"], ("舊回答評分輸入", path.name, key)
                if isinstance(answer, dict) and "reference_chars" in answer:
                    assert answer["reference_chars"] == current[key]["reference_chars"]
                verified.add(key)
                pack_keys.add(key)
        digest = hashlib.sha256(path.read_bytes()).hexdigest()
        packs[digest] = {"filename": path.name, "keys": pack_keys}
    assert verified == set(current), ("評分輸入不完整", sorted(set(current) - verified))
    return packs


def merge_grades(result):
    rows = result["questions"]
    expected = {(f"Q{qid:02}", repeat, arm)
                for qid in range(1, 21) for repeat in range(1, 4)
                for arm in ARMS}
    assert len(rows) == 60
    assert {(r["id"], r["repeat"]) for r in rows} == {
        (qid, repeat) for qid, repeat, _ in expected}
    input_packs = verify_grading_inputs(result)
    indexed = {}
    files = sorted(ROOT.glob("grading_*.json"))
    assert files, "缺少grading_*.json，不可定稿"
    for path in files:
        content = json.loads(path.read_text(encoding="utf-8"))
        grades = content if isinstance(content, list) else content["grades"]
        input_hash = content.get("input_sha256") if isinstance(content, dict) else None
        if input_hash is not None:
            assert input_hash in input_packs, ("評分輸入雜湊不符", path.name)
        assert isinstance(grades, list), path.name
        for original in grades:
            assert GRADE_FIELDS <= original.keys(), (path.name, original)
            grade = {**original, "repeat": int(original["repeat"])}
            key = (grade["id"], grade["repeat"], grade["arm"])
            assert key in expected, ("非預期評分", path.name, key)
            assert key not in indexed, ("重複評分", path.name, key)
            assert grade["verdict"] in VERDICTS and grade["reason"].strip()
            grade_input_hash = grade.get("input_sha256", input_hash)
            if grade_input_hash is not None:
                assert grade_input_hash in input_packs and key in (
                    input_packs[grade_input_hash]["keys"]), (path.name, key)
            indexed[key] = grade
    assert set(indexed) == expected, ("缺少評分", sorted(expected - set(indexed)))
    for row in rows:
        assert set(row["answers"]) == set(ARMS)
        for arm in ARMS:
            grade = indexed[row["id"], row["repeat"], arm]
            if "answer_sha256" in grade:
                digest = hashlib.sha256(
                    row["answers"][arm]["answer"].encode()).hexdigest()
                assert digest == grade["answer_sha256"], "評分與回答雜湊不同"
            row["answers"][arm]["grade"] = grade
    return [p.name for p in files]


def counts(verdicts):
    return {verdict: verdicts.count(verdict) for verdict in VERDICTS}


def group_rows(rows, group):
    if group == "all":
        return rows
    return [r for r in rows if (int(r["id"][1:]) <= 12) == (group == "old")]


def build_summary(rows):
    summary = {}
    question_summary = []
    paired = {}
    for group in ("all", "old", "new"):
        selected = group_rows(rows, group)
        ids = sorted({r["id"] for r in selected})
        summary[group] = {}
        for arm in ARMS:
            verdicts = [r["answers"][arm]["grade"]["verdict"] for r in selected]
            all_three = sum(all(r["answers"][arm]["grade"]["verdict"] == "對"
                                for r in selected if r["id"] == qid)
                            for qid in ids)
            summary[group][arm] = {
                "scores": counts(verdicts), "all_three_correct": all_three,
                "per_repeat": {
                    str(repeat): counts([
                        r["answers"][arm]["grade"]["verdict"] for r in selected
                        if r["repeat"] == repeat]) for repeat in range(1, 4)
                }
            }
        totals = {"C_wins": 0, "draws": 0, "D_wins": 0}
        per_question = []
        for qid in ids:
            qrows = sorted([r for r in selected if r["id"] == qid],
                           key=lambda r: r["repeat"])
            assert [r["repeat"] for r in qrows] == [1, 2, 3]
            pair = {"id": qid, "C_wins": 0, "draws": 0, "D_wins": 0,
                    "per_repeat": []}
            for row in qrows:
                c = row["answers"]["C"]["grade"]["verdict"]
                d = row["answers"]["D"]["grade"]["verdict"]
                outcome = "C_wins" if RANK[c] > RANK[d] else (
                    "D_wins" if RANK[c] < RANK[d] else "draws")
                totals[outcome] += 1
                pair[outcome] += 1
                pair["per_repeat"].append({"repeat": row["repeat"],
                                           "C": c, "D": d,
                                           "outcome": outcome})
            per_question.append(pair)
            if group == "all":
                detail = {"id": qid, "group": "old" if int(qid[1:]) <= 12
                          else "new", "arms": {}}
                for arm in ARMS:
                    values = [r["answers"][arm]["grade"]["verdict"]
                              for r in qrows]
                    detail["arms"][arm] = {
                        "verdicts_by_repeat": values, "counts": counts(values),
                        "all3complete": values == ["對", "對", "對"]}
                detail["all3complete"] = {
                    arm: detail["arms"][arm]["all3complete"] for arm in ARMS}
                question_summary.append(detail)
        paired[group] = {**totals, "paired_answers": len(selected),
                         "rank_rule": RANK, "per_question": per_question,
                         "C_any_win_questions": [p["id"] for p in per_question
                                                 if p["C_wins"]],
                         "C_net_win_questions": [p["id"] for p in per_question
                                                 if p["C_wins"] > p["D_wins"]]}
    return summary, question_summary, paired


def call_usage(calls):
    return {"calls": len(calls),
            "missing_usage_calls": sum(c.get("usage") is None for c in calls),
            **{key: sum((c.get("usage") or {}).get(key, 0) for c in calls)
               for key in TOKEN_KEYS},
            "median_llm_seconds": statistics.median(
                [c["elapsed_seconds"] for c in calls
                 if c.get("elapsed_seconds") is not None]) if any(
                     c.get("elapsed_seconds") is not None for c in calls) else None}


def usage_summary(result, generation, preflight):
    calls = result["calls"]
    parser_calls = [c for c in calls if c["label"].startswith("filter-")]
    phases = {arm: [c for c in calls if c["label"].endswith("-" + arm)]
              for arm in ARMS}
    assert len(calls) == 300 and len(parser_calls) == 60
    assert all(len(c) == 60 for c in phases.values())
    assert sum(map(len, phases.values())) + len(parser_calls) == len(calls)
    phases["C_parser"] = parser_calls
    phases["C_total"] = phases["C"] + parser_calls
    generation_calls = generation["calls"]
    accepted_labels = {f"note-{n['frontmatter']['model']}-attempt{n['attempt']}"
                       for n in generation["notes"]}
    accepted = [c for c in generation_calls if c["label"] in accepted_labels]
    rejected = [c for c in generation_calls if c["label"] not in accepted_labels]
    assert len(accepted_labels) == len(accepted) == 15
    initial = preflight.get("calls", []) if preflight else []
    if preflight:
        assert len(initial) == 4 and preflight["notes_used_in_evaluation"] == 0
    all_generation = initial + generation_calls
    retries = [c for c in all_generation
               if (match := re.search(r"-attempt(\d+)$", c["label"]))
               and int(match[1]) > 1]
    phases.update({"generation_accepted": accepted,
                   "generation_rejected": rejected,
                   "generation_preflight_failed": initial,
                   "generation_retries": retries,
                   "generation_total": all_generation})
    phase_usage = {phase: call_usage(records) for phase, records in phases.items()}
    all_calls = calls + all_generation
    known_attempts = (result["usage"]["provider_attempts"]
                      + generation["usage"]["provider_attempts"])
    resumed_unrecorded = sum(
        data["usage"].get("provider_attempts_unrecorded_calls", 0)
        for data in (result, generation))
    preflight_attempts = (preflight or {}).get("usage", {}).get("provider_attempts")
    if preflight_attempts is None and preflight and "route_attempts" in preflight:
        preflight_attempts = len(preflight["route_attempts"])
    preflight_unrecorded = len(initial) if preflight_attempts is None else 0
    missing_attempts = bool(preflight_unrecorded or resumed_unrecorded)
    totals = call_usage(all_calls)
    all_usage = {"llm_calls": totals.pop("calls"),
                 "provider_attempts": None if missing_attempts else (
                     known_attempts + (preflight_attempts or 0)),
                 "recorded_provider_attempts": known_attempts + (preflight_attempts or 0),
                 "preflight_provider_attempts": preflight_attempts,
                 "provider_attempts_unrecorded_calls": (
                     resumed_unrecorded + preflight_unrecorded),
                 "resumed_provider_attempts_unrecorded_calls": resumed_unrecorded,
                 "provider_attempts_complete": not missing_attempts,
                 "missing_usage_calls": totals["missing_usage_calls"],
                 "tokens": {key: totals[key] for key in TOKEN_KEYS},
                 "generation_all_calls": len(all_generation),
                 "generation_accepted_calls": len(accepted),
                 "generation_rejected_calls": len(rejected),
                 "generation_preflight_failed_calls": len(initial),
                 "generation_retry_calls": len(retries),
                 "parser_attributed_to": "C", "C_including_parser_calls": 120}
    return phase_usage, all_usage


def compact(scores):
    return "／".join(str(scores[v]) for v in VERDICTS)


def cell(text):
    return str(text).replace("|", "\\|").replace("\n", " ")


def build_report(result, generation, preflight):
    summary = result["summary"]
    date = datetime.now(ZoneInfo("Asia/Taipei")).date().isoformat()
    config = result["config"]
    audit = result["note_audit"]
    filters = result["filter_audit"]
    verification = result["verification"]
    usage = summary["all_usage"]
    phases = summary["phase_usage"]
    paired = summary["C_vs_D"]
    chars = {arm: round(statistics.mean(
        r["answers"][arm]["reference_chars"] for r in result["questions"]))
        for arm in ARMS}
    scores_table = ["| 範圍 | 做法 | 對 | 部分對 | 錯 | 三次都對題數 |",
                    "|---|---|---:|---:|---:|---:|"]
    group_names = {"all": "全部20題×3", "old": "舊題12題×3", "new": "新題8題×3"}
    for group in group_names:
        for arm in ARMS:
            entry = summary[group][arm]
            s = entry["scores"]
            scores_table.append(f"| {group_names[group]} | {arm} | {s['對']} | "
                                f"{s['部分對']} | {s['錯']} | {entry['all_three_correct']} |")
    repeats_table = ["| 範圍 | 做法 | 第一次 對／部分／錯 | 第二次 | 第三次 |",
                     "|---|---|---|---|---|"]
    for group in group_names:
        for arm in ARMS:
            values = summary[group][arm]["per_repeat"]
            repeats_table.append(f"| {group_names[group]} | {arm} | " + " | ".join(
                compact(values[str(rep)]) for rep in (1, 2, 3)) + " |")
    qtable = ["| 題號 | A 三次 | B 三次 | C 三次 | D 三次 | 三次都對 | C勝／平／D勝 |",
              "|---|---|---|---|---|---|---|"]
    pair_by_qid = {p["id"]: p for p in paired["all"]["per_question"]}
    for detail in summary["question_summary"]:
        qid = detail["id"]
        values = ["／".join(detail["arms"][arm]["verdicts_by_repeat"])
                  for arm in ARMS]
        complete = "、".join(a for a in ARMS if detail["all3complete"][a]) or "無"
        p = pair_by_qid[qid]
        qtable.append(f"| {qid} | " + " | ".join(values) +
                      f" | {complete} | {p['C_wins']}／{p['draws']}／{p['D_wins']} |")
    ptable = ["| 範圍 | C勝 | 平手 | D勝 | C至少勝一次題號 | C勝多於敗題號 |",
              "|---|---:|---:|---:|---|---|"]
    for group in group_names:
        p = paired[group]
        wins = "、".join(p["C_any_win_questions"]) or "無"
        net = "、".join(p["C_net_win_questions"]) or "無"
        ptable.append(f"| {group_names[group]} | {p['C_wins']} | {p['draws']} | "
                      f"{p['D_wins']} | {wins} | {net} |")
    evidence = []
    for p in paired["all"]["per_question"]:
        if p["C_wins"] or p["D_wins"]:
            pieces = []
            for row in result["questions"]:
                if row["id"] != p["id"]:
                    continue
                c, d = (row["answers"][a]["grade"] for a in ("C", "D"))
                if c["verdict"] == d["verdict"]:
                    continue
                pieces.append(f"R{row['repeat']} C{c['verdict']}／D{d['verdict']}："
                              f"C {c['reason']}；D {d['reason']}")
            evidence.append(f"- **{p['id']}**：" + "；".join(pieces))
    if not evidence:
        evidence = ["所有配對評分相同，沒有可列出的勝敗差異。"]
    ttable = ["| 階段 | LLM呼叫 | input tokens | output tokens | total tokens |",
              "|---|---:|---:|---:|---:|"]
    labels = {"generation_accepted": "入選筆記生成", "generation_rejected": "本次生成未入選回覆",
              "generation_preflight_failed": "前置驗證失敗回覆（未入測量）",
              "C_parser": "C條件解析", **{a: f"{a}回答" for a in ARMS}}
    for phase, label in labels.items():
        u = phases[phase]
        ttable.append(f"| {label} | {u['calls']} | {u['input_tokens']:,} | "
                      f"{u['output_tokens']:,} | {u['total_tokens']:,} |")
    tokens = usage["tokens"]
    ttable.append(f"| 全部（不重複累計） | {usage['llm_calls']} | "
                  f"{tokens['input_tokens']:,} | {tokens['output_tokens']:,} | "
                  f"{tokens['total_tokens']:,} |")
    c_total = phases["C_total"]
    generation_total = phases["generation_total"]
    rejects = []
    for origin, candidates in (("前置失敗", (preflight or {}).get("candidates", [])),
                               ("本次生成", generation.get("rejected_notes", []))):
        for n in candidates:
            errors = n.get("validation", {}).get("errors", [])
            rejects.append(f"| {origin} | {cell(n.get('filename', '未記載'))} | "
                           f"{n.get('attempt', '未記載')} | "
                           f"{cell(json.dumps(errors, ensure_ascii=False))} |")
    rejected_table = "\n".join([
        "| 階段 | 筆記 | 嘗試 | 驗證錯誤明細 |", "|---|---|---:|---|", *rejects
    ]) if rejects else "沒有未入選筆記回覆。"
    grade_sources = summary["grading_files"]
    old_c, new_c = summary["old"]["C"], summary["new"]["C"]
    new_comparison = (
        f"新題三次都對：C {new_c['all_three_correct']}/8、"
        f"D {summary['new']['D']['all_three_correct']}/8。"
        "本批C的新增題正確比例低於舊題，不能直接稱為與舊題同樣穩定。"
        if new_c['scores']['對'] / 24 < old_c['scores']['對'] / 36 else
        "本批新增題正確比例未低於舊題，但仍需更多來源與未見問法確認。"
    )
    p = paired["all"]
    comparison = ("C在本批配對中勝多於敗" if p["C_wins"] > p["D_wins"] else
                  "D在本批配對中勝多於敗" if p["D_wins"] > p["C_wins"] else
                  "本批C與D的配對勝敗次數相同")
    conclusion = (
        f"{comparison}（C勝{p['C_wins']}／平{p['draws']}／D勝{p['D_wins']}）；"
        f"C三次都對{summary['all']['C']['all_three_correct']}/20題，"
        f"D三次都對{summary['all']['D']['all_three_correct']}/20題。"
        "C與D的格式、參考量及解析失敗退回路徑不同，結果不能全歸因於純篩選運算。")
    readonly_table = ["| 階段 | 鏡像檢查exit |", "|---|---:|"]
    for name, data in result["mirror_checks"].items():
        readonly_table.append(f"| {name} | {data['exit_code']} |")
    if preflight:
        for name in ("mirror_before", "mirror_after"):
            readonly_table.append(f"| 前置失敗 {name} | {preflight[name]['exit_code']} |")
    rejected_explanation = ""
    if preflight:
        rejected_explanation = (
            f"前置四次生成未進入測量：驗證器曾拒絕合法的相關連結標題及項目符號，修正後重新生成；"
            f"原失敗回覆與原因保留在 `round3/generation_preflight.json`。其狀態為 "
            f"`{preflight['status']}`，候選入測量數為0。拒絕紀錄包含驗證器誤拒，不能全當筆記內容錯誤。\n\n")
        recheck = result.get("generation_preflight_audit")
        if recheck:
            values = recheck["summary"]
            rejected_explanation += (
                f"使用修正後驗證器重驗原始四份前置回覆，"
                f"{values['validator_false_rejections']}份是驗證器誤拒，"
                f"{values['legitimate_note_rejections']}份確有筆記錯誤；"
                "原文及原判定保留於generation_preflight_audit。\n\n")
    if usage["provider_attempts_complete"]:
        attempt_text = f"供應商嘗試共{usage['provider_attempts']}次。"
    else:
        attempt_text = (f"生成／評測有紀錄的供應商嘗試為{usage['recorded_provider_attempts']}次；"
                        f"前置及中斷後續跑共有{usage['provider_attempts_unrecorded_calls']}份回覆"
                        "缺route_attempts紀錄，因此全部供應商嘗試數為null／未知，"
                        "不把LLM回覆數自行當provider attempts；其LLM呼叫與token仍完整納入。")
    recommendations = (
        "本批C的配對結果較佳，值得繼續做更大規模、同格式同資料量的運算對照，再決定是否整合為正式Brain工具。"
        if p["C_wins"] > p["D_wins"] else
        "本批未建立C穩定超過D的證據；可先評估完整筆記是否已足夠，再做同格式同資料量的運算對照。"
    )
    section = f"""## 第三輪：全部筆記對照與三次重複（{date}）

日期：{date}（Asia/Taipei）。狀態：實測及來源核對完成；這是代理依凍結規則判定，尚非使用者驗收。

{conclusion}

### 方法、資料與凍結

與第二輪相同的15列中文型錄來源：EDW第9頁L201–205、EUB-M 2～7.5HP第11頁L233–242。原始快照雜湊 `{result['config']['source_sha256']}`。前12題完整question objects及grading_rubric沿用；新增Q13–Q20在任何回答生成前手算及凍結，題目雜湊 `{result['question_validation']['questions_sha256']}`，38處逐字引用與頁碼／行號核對通過，標準集合由raw cells獨立重算，沒有把filter_engine當oracle。

新題涵蓋三相電流／重量、粒徑與kW、電流主排序及重量同分次排序、兩現場分集合、跨系列最輕款、明列額定點與保證限制、CH數值缺資料、三相欄null語意。題目使用口語但沒有測ASR。

模型固定 `{config['provider']}/{config['model']}`、temperature `{config['temperature']}`，四組回答使用相同system prompt與4200 token上限，解析及筆記生成各2200。20題各三次，共60個問題／重複組合與240份回答；每次沒有對話歷史，回答模型不看標準答案。四組順序以題號與重複次數輪替，實際順序保存於results。

- A：原樣現行 `_search_tool`，含results／related／來源。
- B：A＋最相近3篇合格產品筆記。
- C：B＋同模型條件JSON，使用第二輪原樣篩選工具，成功時對全部15篇frontmatter作計算；matches／unknown／excluded保留全規格。
- D：A＋全部15篇Markdown筆記，不給篩選工具。

解析成功時C與D能看到相同15款的數值資訊，但C拿分類後frontmatter及三篇筆記，D拿15篇完整Markdown；資料表示與內容長度不同。平均參考字數A {chars['A']:,}、B {chars['B']:,}、C {chars['C']:,}、D {chars['D']:,}，各組實際input tokens見下表。C解析失敗{len(filters['errors'])}次時只剩B的3篇筆記與錯誤訊息，不能聲稱該次C也拿到全部15款。成功解析亦不等於語意正確；工具核對僅證明按當次JSON計算一致。這是整體方案比較，不能將差異全歸因於純運算。

筆記不人工修改後混入測量：不合格整篇重生成，入選15篇皆通過原文數字、額定點、最大值獨立敘述、禁止額外材質／用途推論與來源頁碼／行號檢查。評分先沿用凍結規則：數字錯、錯納型號或重大禁止主張判錯；漏必要型號、數字、情境、排序／限定判部分對；required_points全滿足才判對，引用品質另列。240筆唯一評分與理由來自{', '.join('`'+f+'`' for f in grade_sources)}，合併於results的answers.grade；非模型自評或人類驗收。

### 分層結果與重複穩定性

{chr(10).join(scores_table)}

{chr(10).join(repeats_table)}

新題C為{new_c['scores']['對']}/24次對（{new_c['scores']['對']/24:.1%}），三次都對{new_c['all_three_correct']}/8題；舊題C為{old_c['scores']['對']}/36次對（{old_c['scores']['對']/36:.1%}），三次都對{old_c['all_three_correct']}/12題。這是同一來源與固定問法的小樣本比例，不能直接視為跨型錄泛化機率。

{new_comparison}

### 逐題三次與C／D配對

{chr(10).join(qtable)}

配對只比較同題同重複，判定rank為錯0、部分對1、對2；不跨重複挑最佳答案，也不以新舊題不同分母混算。

{chr(10).join(ptable)}

勝敗的逐份理由（完整matched／missing／false_claims與來源見results）：

{chr(10).join(evidence)}

### 筆記、來源與篩選核對

入選15篇錯誤{audit['accepted_note_errors']}，正文不再把兩個最大值併為同一工作點，額定值保持同一點；逐篇來源含模型資料列或實際使用的註腳，頁次按該行所在頁核對。逐篇結果在 `round3/note_audit.json`；凍結題目、原始筆記回覆一致、來源、固定模型、同回答提示及240份回答檢查在 `round3/verification.json`（status={verification['status']}）。保留null，不由型號推斷未載數值。

解析60次，schema有效{filters['schema_valid']}次，失敗{len(filters['errors'])}次。錯誤明細在 `round3/filter_audit.json`：{', '.join(f"{e['id']}-R{e['repeat']}" for e in filters['errors']) or '無'}。沒有為新題修改第二輪filter_engine，沒有修補或重試當次失敗解析。

{rejected_explanation}未入選回覆的驗證拒絕明細：

{rejected_table}

### LLM呼叫與token

{chr(10).join(ttable)}

C回答60次＋解析60次，歸C共{c_total['calls']}次，input {c_total['input_tokens']:,}、output {c_total['output_tokens']:,}、total {c_total['total_tokens']:,}。所有筆記生成含前置失敗與重生共{generation_total['calls']}次，其中入選15次；所有attempt>1重試回覆共{usage['generation_retry_calls']}次，這個重試數是前述生成呼叫的子集合，不能再重複累加。完整stage usage保存於results.summary.phase_usage。

{attempt_text} Token全為供應商回報，缺usage {usage['missing_usage_calls']}次；cached {tokens['cached_tokens']:,}已包含input，不再加算，reasoning {tokens['reasoning_tokens']:,}。本表沒有把grading代理對話計成實驗模型呼叫。LLM秒數不含整個檢索／embedding，不作正式端到端延遲結論。

### 唯讀與產物完整性

{chr(10).join(readonly_table)}

正式 `proj-0cc5c610b4` 與dev `dev-c0c8fdff34` 的workspace／LanceDB內容生成前後、評測前後雜湊均未變；生成結束到評測開始摘要相同。評測檔案數{result['integrity']['file_count_before']}，前後digest `{result['integrity']['digest_after']}`。完整逐檔列表在git忽略檔，交付的檢查產物只保留數量與摘要；未變更round1／round2，由previous_rounds_integrity與verification核對。

所有實驗只在既有API容器的唯讀子程序執行，筆記向量只在記憶體；沒有放進knowledge、建表、reindex、正式chat API、部署、重啟／重建、env或帳號修改，也沒有stage／commit／push。本輪只更新實驗腳本、產物與同一份報告，Brain／Backend／前台／管理介面／SDK／API contract不需介面修改。

### 建議與限制

{recommendations} 先處理解析失敗與選配缺值的正式語意，再擴大未見題、系列與數量，測試限定上下文後是否仍完整列出符合型號。

本輪修正筆記正文後重跑，不能把與第二輪的分數差異只歸因於工具；新增題雖未見過回答，仍出自同一份15列型錄。三次重複不是三個獨立產品樣本。來源為既有Markdown，未重新比對PDF或原廠確認，也未測正式人格、工具自主選擇、語音、前台圖文與完整agent loop。C／D格式與token不同、解析失敗C退回B，無法宣稱完成純運算消融或正式服務品質驗收。
"""
    return section, conclusion


def update_parent_report(section, conclusion, summary):
    path = ROOT.parent / "REPORT.md"
    original = path.read_text(encoding="utf-8")
    start = original.index("## 第一輪")
    historical = original[start:]
    if "\n## 第三輪" in historical:
        historical = historical.split("\n## 第三輪", 1)[0] + "\n"
    old_rows = []
    for label in ("第一輪", "第二輪"):
        line = next(line for line in original[:start].splitlines()
                    if line.startswith("| " + label + " |"))
        values = [v.strip() for v in line.strip("|").split("|")][:5]
        old_rows.append("| " + " | ".join(values) + " | — |")
    s = summary["all"]
    third = "| 第三輪 | 同15列、20題×3次（每組60答） | " + " | ".join(
        compact(s[arm]["scores"]) for arm in ARMS) + " |"
    prefix = f"""# AI 產品筆記與跨產品問答實驗

AI讀型錄，生成含frontmatter的產品筆記，檢驗跨產品選型回答。前兩輪比較A現行檢索、B加3篇筆記、C加篩選工具；第三輪加D全15篇筆記與三次重複。交辦見 [TASK.md](TASK.md)，重現見 [README.md](README.md)。

| 輪次 | 範圍 | A 對／部分對／錯 | B | C | D |
|---|---|---|---|---|---|
{chr(10).join(old_rows)}
{third}

目前結論：

- {conclusion}
- 第三輪入選15篇筆記逐篇原文數字、正文工作點及來源頁碼／行號核對通過；未入選回覆含前置失敗與重生全部保留，未人工修好後混入測量。
- C新題與舊題的完整答對比例、三次都對題數及C／D配對差異分開報告；尚未測正式工具自主選擇、語音或完整agent loop。
- 三輪皆未改正式workspace／LanceDB、知識庫與部署。第一輪、第二輪歷史正文原樣保留。

"""
    return path, prefix + historical + ("\n" if not historical.endswith("\n\n") else "") + section


def main():
    result = read("results.json")
    generation = result.get("generation") or read("generation.json")
    preflight = read("generation_preflight.json") if (
        ROOT / "generation_preflight.json").exists() else None
    grading_files = merge_grades(result)
    summary, question_summary, paired = build_summary(result["questions"])
    phase_usage, all_usage = usage_summary(result, generation, preflight)
    for name in ("note_audit", "filter_audit", "verification", "question_validation"):
        result[name] = read(name + ".json")
    if preflight and (ROOT / "generation_preflight_audit.json").exists():
        result["generation_preflight_audit"] = read("generation_preflight_audit.json")
        assert result["generation_preflight_audit"]["status"] == "passed"
    assert result["note_audit"]["accepted_note_errors"] == 0
    assert result["verification"]["status"] == "passed"
    assert result["verification"]["answer_count"] == 240
    frozen_hash = hashlib.sha256((ROOT / "questions.json").read_bytes()).hexdigest()
    assert frozen_hash == result["question_validation"]["questions_sha256"]
    assert not result["integrity"]["changed"] and not generation["integrity"]["changed"]
    assert generation["integrity"]["digest_after"] == result["integrity"]["digest_before"]
    mirror_names = ("mirror_before.json", "mirror_after_generation.json",
                    "mirror_before_evaluation.json", "mirror_after.json")
    result["mirror_checks"] = {name: read(name) for name in mirror_names}
    assert all(data["exit_code"] == 0 for data in result["mirror_checks"].values())
    if preflight:
        assert all(preflight[name]["exit_code"] == 0
                   for name in ("mirror_before", "mirror_after"))
    answer_calls = [c for c in result["calls"]
                    if not c["label"].startswith("filter-")]
    assert len({c["system_sha256"] for c in answer_calls}) == 1
    assert {c["max_tokens"] for c in answer_calls} == {4200}
    summary.update({"question_summary": question_summary, "C_vs_D": paired,
                    "phase_usage": phase_usage, "all_usage": all_usage,
                    "grading_files": grading_files,
                    "grading": "代理依凍結required_points／forbidden_claims逐份對照原文，非人類驗收，無額外實驗模型自評。",
                    "generation_to_evaluation_unchanged": True})
    result["summary"] = summary
    result["summary"]["grading_inputs"] = {
        digest: data["filename"] for digest, data in verify_grading_inputs(result).items()}
    section, conclusion = build_report(result, generation, preflight)
    report_path, report = update_parent_report(section, conclusion, summary)
    # Build both complete outputs before the first write; no partial grades.
    write("results.json", result)
    report_path.write_text(report, encoding="utf-8")
    print(json.dumps({"status": "finalized", "grades": 240,
                      "report": str(report_path),
                      "scores": {group: summary[group] for group in
                                 ("all", "old", "new")},
                      "C_vs_D": {group: {k: p[k] for k in
                                          ("C_wins", "draws", "D_wins")}
                                 for group, p in paired.items()},
                      "usage": all_usage}, ensure_ascii=False))


if __name__ == "__main__":
    main()
