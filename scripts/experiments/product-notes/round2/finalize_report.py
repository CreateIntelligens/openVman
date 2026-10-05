"""Combine source-reviewed grades and update this round's report."""

import json
from pathlib import Path
import statistics


ROOT = Path(__file__).resolve().parent


def read(name):
    return json.loads((ROOT / name).read_text())


def write(name, data):
    (ROOT / name).write_text(
        json.dumps(data, ensure_ascii=False, indent=2) + "\n",
    )


def main():
    result = read("results.json")
    grades = (read("grading_Q01_Q06.json")["grades"]
              + read("grading_Q07_Q12.json")["grades"])
    assert len(grades) == 36
    indexed = {(g["id"], g["arm"]): g for g in grades}
    assert len(indexed) == 36
    scores = {arm: {v: 0 for v in ("對", "部分對", "錯")}
              for arm in ("A", "B", "C")}
    for row in result["questions"]:
        for arm, answer in row["answers"].items():
            answer["grade"] = indexed[row["id"], arm]
            scores[arm][answer["grade"]["verdict"]] += 1
    phases = {
        "筆記生成": result["generation"]["calls"],
        "條件解析": [c for c in result["calls"]
                     if c["label"].startswith("filter-")],
        **{arm: [c for c in result["calls"]
                 if c["label"].endswith("-" + arm)] for arm in scores},
    }
    phase_usage = {}
    for phase, calls in phases.items():
        phase_usage[phase] = {
            "calls": len(calls),
            **{key: sum(c["usage"][key] for c in calls)
               for key in ("input_tokens", "output_tokens", "total_tokens")},
            "median_llm_seconds": statistics.median(
                c["elapsed_seconds"] for c in calls),
        }
    all_calls = result["generation"]["calls"] + result["calls"]
    usage = {"llm_calls": len(all_calls), "provider_attempts": (
        result["usage"]["provider_attempts"]
        + result["generation"]["usage"]["provider_attempts"]),
        "missing_usage_calls": sum(c["usage"] is None for c in all_calls),
        "tokens": {key: sum(c["usage"][key] for c in all_calls)
                   for key in ("input_tokens", "output_tokens", "total_tokens",
                               "cached_tokens", "reasoning_tokens")}}
    rank = {"錯": 0, "部分對": 1, "對": 2}
    wins = [row["id"] for row in result["questions"]
            if rank[row["answers"]["C"]["grade"]["verdict"]]
            > rank[row["answers"]["B"]["grade"]["verdict"]]]
    full_wins = [row["id"] for row in result["questions"]
                 if row["answers"]["C"]["grade"]["verdict"] == "對"
                 and row["answers"]["B"]["grade"]["verdict"] != "對"]
    schema_errors = [row["id"] for row in result["questions"]
                     if "error" in row["frontmatter_filter"]]
    result["note_audit"] = read("note_audit.json")
    result["numeric_audit"] = read("numeric_audit.json")
    result["filter_audit"] = {
        "schema_valid_questions": 12 - len(schema_errors),
        "schema_errors": schema_errors,
        "Q03": "LLM產生where.or；schema只支援all/any，因此拒絕。不修補或重試，保留其對C答題的影響。",
        "Q06": "甲乙分成兩個scenarios，完整集合分別2與3列，沒有合併AND。",
        "Q07": "以max_head_m desc再max_flow_lpm desc排序，23m同值依1900>700LPM正確排序。",
        "Q08": "30m³/h轉500LPM，gte方向與邊界正確，S/T合併列包含單相。",
        "Q09": "設定15m/400LPM operating_point，exact為空；同額定點門檻候選4列，不把最大值合成工作點。",
        "null": "本批相數限定的電流與重量有24個null；18項測試另驗證null AND/OR不能當確認排除。",
        "confound": "成功的工具回覆保留matches/unknown/excluded完整frontmatter，C能見全15列，資料量多於B三篇；需加A+全15篇不篩選的控制才能分離資訊量與運算效果。",
    }
    write("filter_audit.json", result["filter_audit"])
    result["summary"] = {
        "scores": scores, "C_better_than_B": wins,
        "C_full_correct_wins": full_wins, "all_usage": usage,
        "phase_usage": phase_usage,
        "grading": "Codex獨立代理與主代理依凍結規則逐條對照原文，非人類驗收，沒有額外實驗模型自評。",
        "generation_to_evaluation_unchanged": (
            result["generation"]["integrity"]["digest_after"]
            == result["integrity"]["digest_before"]),
    }
    assert result["summary"]["generation_to_evaluation_unchanged"]
    write("results.json", result)
    score_rows = "\n".join(
        f"| {arm} | {s['對']} | {s['部分對']} | {s['錯']} |"
        for arm, s in scores.items())
    qrows = "\n".join(
        "| " + row["id"] + " | " + " | ".join(
            row["answers"][arm]["grade"]["verdict"] for arm in scores) + " |"
        for row in result["questions"])
    trows = "\n".join(
        f"| {phase} | {u['calls']} | {u['input_tokens']:,} | "
        f"{u['output_tokens']:,} | {u['total_tokens']:,} |"
        for phase, u in phase_usage.items())
    audit = result["note_audit"]
    chars = {arm: round(statistics.mean(
        row["answers"][arm]["reference_chars"] for row in result["questions"]))
        for arm in scores}
    report = f"""# 第二輪：完整規格表的產品筆記與篩選工具

日期：2026-10-05（Asia/Taipei）。狀態：實測完成。第一輪產物保留，本輪只寫 `round2/`。

第二輪結果為 A **{scores['A']['對']}對／{scores['A']['部分對']}部分對／{scores['A']['錯']}錯**、B **{scores['B']['對']}對／{scores['B']['部分對']}部分對／{scores['B']['錯']}錯**、C **{scores['C']['對']}對／{scores['C']['部分對']}部分對／{scores['C']['錯']}錯**。C 完整答對的題數多於 B，主要補足跨系列清單、多情境、排序與額定點候選。但 C 包含更多規格資料，本輪尚不能把改善全部歸因於篩選運算。

## 來源、筆記與凍結題目

來源為鶴記dev `dev-c0c8fdff34` 的中文 `knowledge/EVAK_CATALOG.md`，對應正式鶴記 `proj-0cc5c610b4`。只使用 EDW 第9頁 L201–205 五列、EUB-M 2～7.5HP 第11頁 L233–242 十列。其他系列與 EUB-M 10～20HP 不納入評分。來源快照 SHA-256：`{result['config']['source_sha256']}`。

每列一篇，共15篇。EDW的三個 `S/T` 合併列保留原model，phase為 `[1,3]`；檔名用 `S-T` 避免斜線成為目錄，Obsidian連結使用alias。EUB-M單／三相不同列分開。馬力、kW、口徑、額定／最大揚程與流量、粒徑、兩相電流與重量皆分欄；缺少的一相資料保留null。沒有從型號猜規格。

12題包含數值／多條件篩選、兩現場OR、多欄排序與23m同分、3HP及3吋跨系列比較、30m³/h換算500LPM、15m下400LPM的額定點與最大值區分，另有價格／保固兩題。問題未提頁碼或「型號組」，部分為確保可評分而明示最大／額定及完整清單，不代表已測真實ASR口語輸入。

`questions.json` 在回答生成前凍結；`question_validation.json` 保存其 SHA-256、手算集合、23段逐字引文與完整型錄價格／保固缺資料核對。驗證腳本重新檢查所有來源列、引文及凍結雜湊。

## A／B／C 方法

固定 `{result['config']['provider']}/{result['config']['model']}`、temperature `{result['config']['temperature']}`，63份實際回覆同模型。使用既有服務的單一route，不備援、不重試失敗解析。三組回答系統提示完全一致，提示固定比較範圍；回答上限4200 tokens、條件解析2200、筆記生成2200。每題回答順序循環A/B/C、B/C/A、C/A/B，沒有對話歷史，也沒有向回答模型提供標準答案。

- A：現行 `_search_tool("knowledge", {{"queries": [q]}})` 原樣 results／related／出處，沒有額外手工改寫或擴展query。
- B：A 加問題向量最相近三篇原生成筆記；query/document identity只改語意用途，保持模型、維度及revision，cosine排序只在記憶體。
- C：B 加同模型解析的JSON，以及腳本對全15篇frontmatter的篩選結果。解析使用白名單欄位與op，巢狀all/any、多scenarios、多欄sort、未知分類與operating_point。

C工具保留 `matches_all/selected/unknown/excluded`，不因limit無痕丟掉完整符合名單。重要限制：這些分類都包含完整frontmatter，成功執行時C實際可見全15列，而B只加3篇。參考字數平均 A {chars['A']:,}、B {chars['B']:,}、C {chars['C']:,}。本輪是兩個完整方案的比較，不是等資訊量的運算消融測試。

## 回答結果與逐題理由

| 做法 | 對 | 部分對 | 錯 |
|---|---:|---:|---:|
{score_rows}

| 題號 | A | B | C |
|---|---|---|---|
{qrows}

C 比 B 改善的題：**{', '.join(wins)}**；其中升為完整答對：**{', '.join(full_wins)}**。兩題價格／保固三組都沒有編造。完整36筆回答、參考資料、模型usage與逐題判定，見 [results.json](results.json)；評分由Codex獨立代理及主代理對照原文完成，並非人類驗收。

主要差異：

- Q01／Q02：C列出完整3吋揚程候選5列與三相低馬力流量候選6列；B曾捏造 `80EUB-M-5.30S/T`、22m／36m，或錯稱沒有候選。
- Q04：C列完整4個3HP型號，冠軍 `80EDW-5.30S/T` 26.5m；B只有一列26m，漏冠軍及其他型號。
- Q05／Q10：C正確比較各系列3吋揚程冠軍32.4m／33m（差0.6m）、4吋流量冠軍1680／1900LPM（差220）。B資料不完整，誤說EDW沒有相關規格。
- Q06：C分開甲現場2列、乙現場3列。B把690LPM錯寫630，並捏造EDW型號與揚程。
- Q07：C六列完整排序，23m同值以1900>700LPM處理；B只有21m的一列。
- Q08：C換算500LPM後列全3列。A/B缺EDW，部分回答又用「極限點 Xm @ YLPM」把獨立最大值配成工作點。
- Q09：C列全4個同額定點門檻候選，並拒絕保證15m時400LPM。A/B能說明最大值不可拼工作點，但沒有完整候選。
- Q03：條件解析寫 `where.or`，不符合只允許all/any的schema，工具拒絕；C從B筆記指出正確1900LPM型號，但仍沒有確認全範圍冠軍，判部分對。

評分規則先凍結：數字錯、錯納型號、虛構價格／保固或把最大值合為工作點判錯；漏型號、漏題目要求數字／排序／限制判部分對；只有主結論及完整必要資訊正確才判對。缺資料題的拒答可判對，原文明載資訊卻拒答不能判對。引用品質另列，chunk id不是頁碼。Q05-C額外寫80mm／3吋未區分公稱與精確換算，列品質問題，冠軍及題目要求數字仍正確。

## 筆記與工具核對

frontmatter逐欄規格數字錯誤 **{result['numeric_audit']['spec_error_count']}**：168個已知單值、3個相數陣列、24個null均吻合原表。null都在沒有提供的那一相電流／重量，不是馬力、揚程或口徑缺資料。正文178處數字亦為0錯，但有 **9篇合成工作點語意錯誤、2篇最大值措辭歧義、13項頁碼錯誤**。15個連結有效、0個無效。逐篇明細見 [note_audit.json](note_audit.json)，機械逐欄明細見 `numeric_audit.json`。

不能只看數字為零錯就直接入庫：多篇摘要用「最大揚程搭配最大流量」配成未證實的工作點；13篇把source.page填字串「主頁」，頁碼不可直接用。原生成筆記保留，沒有修正後再混入B/C。所有連結均指向本輪已生成檔案，部分為自連結，不能把連結存在視為已驗證圖譜擴充有用。

第一輪列出的工具問題已有實作：Q06實測兩scenarios，Q07實測雙欄排序與tie，Q08方向gte及相數合併列正確，Q09操作點分清rated與max。null AND/OR、缺排序值放尾端、limit保留完整名單由18項邊界測試驗證。12題解析11題schema有效，Q03無效原樣保留，不偷偷修正再算成功。

## LLM 呼叫與token

共 **{usage['llm_calls']}次LLM呼叫**＝15生成＋12解析＋36回答；供應商嘗試 **{usage['provider_attempts']}次**，usage遺漏 **{usage['missing_usage_calls']}次**。Q03是回覆JSON無效，仍計入一次成功模型呼叫。

| 階段 | 呼叫 | input tokens | output tokens | total tokens |
|---|---:|---:|---:|---:|
{trows}
| 全部 | {usage['llm_calls']} | {usage['tokens']['input_tokens']:,} | {usage['tokens']['output_tokens']:,} | {usage['tokens']['total_tokens']:,} |

供應商另回報cached tokens {usage['tokens']['cached_tokens']:,}、reasoning tokens {usage['tokens']['reasoning_tokens']:,}；cached包含在input，不再累加。這是實驗API回報usage，不是Codex對話用量。腳本保存每次LLM耗時但不含整個檢索／embedding，不能據此宣稱正式端到端延遲。

## 資料完整性與驗證

生成前、生成後、評測後 `python3 scripts/project_mirror.py check` 均exit 0。正式與dev的workspace／LanceDB每次包含2892檔，生成與評測前後逐檔SHA-256零變動，生成結束到評測開始摘要也相同：`{result['integrity']['digest_after']}`。完整逐檔列表保存在忽略的 `generate.full.json/evaluate.full.json`，results只保留摘要。

`filter_engine` 18項unittest全通過；`verify_artifacts.py` 已核對12題、23段引文、15來源列、全部數字、固定模型與同回答提示，以及從獨立解析原表重算工具輸出。單位helper曾因浮點乘法產生500.00000000000006，已改成先乘1000再除60並測邊界；runtime沒有呼叫此helper，實測JSON直接是500，所以沒有改動評測結果。正式程式未變更，沒有跑正式服務全測；完整生成與評測已在現有api容器實際執行。

本目錄`.gitignore`排除1.1MB生成checkpoint、2MB評測checkpoint與完整逐檔雜湊。交付含生成／評測／篩選／驗證腳本、15篇筆記、凍結題目、原始結果、評分及核對明細、鏡像證據與本報告。第一輪檔案、正式程式、帳號、`.env`不改；沒有chat API、部署、重啟、重建、索引新增、stage、commit或push。依產出目錄限制，CHANGELOG與README只在本目錄更新；Brain、Backend、前台、管理介面、SDK、contract不需要產品介面改動。

## 建議與不確定處

**值得繼續驗證篩選方案，尚不建議直接做正式Brain工具。** C在此輪完整選型答案明顯優於B，證明結構化規格能補回現行三筆檢索與三篇相近筆記未提供的完整集合。下一步加一組「A＋全15篇規格、不做篩選」並限制各組相同參考資料量，才能分離條件計算與資料完整性，再決定是否正式整合。

正式化前需解決JSON修復／重試策略、輸出只保留必要候選及排除理由、來源頁碼驗證，以及摘要不得合併最大值。要補更多未見過的題、不同規格值／系列與更大產品數量，測試null與多情境在真實資料上的表現，避免15列全部塞入上下文才看起來有效。

本輪每題只跑一次，模型temperature0.3且參考量不同；分數不能視為穩定機率。型錄來源是現有Markdown，未重新比對原PDF。QA本身可能有省略字尾或來源差異，原資料保留，結果不能判定哪份已經過原廠確認。沒有測正式人格、回答字數限制、工具自主選擇、ASR、TTS、前台圖文或完整agent loop；本輪只證明此實驗設定下的效果。
"""
    (ROOT / "REPORT.md").write_text(report)
    print(json.dumps(result["summary"], ensure_ascii=False))


if __name__ == "__main__":
    main()
