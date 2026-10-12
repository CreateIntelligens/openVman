"""Update the existing report from verified grades without editing raw answers."""

import hashlib
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parent
REPORT = ROOT.parents[1] / "REPORT.md"
BEGIN = "<!-- acceptance-117-20261012:begin -->"
END = "<!-- acceptance-117-20261012:end -->"


def main():
    summary = json.loads((ROOT / "summary.json").read_text())
    assert summary["status"] == "verified"
    assert summary["results_sha256"] == hashlib.sha256(
        (ROOT / "results.json").read_bytes()
    ).hexdigest()
    for name, expected in summary["grading_sha256"].items():
        assert hashlib.sha256((ROOT / name).read_bytes()).hexdigest() == expected
    assert hashlib.sha256((ROOT / "tool_audit.json").read_bytes()).hexdigest() == (
        summary["tool_audit_sha256"]
    )
    scores = summary["scores"]
    repeats = "\n".join(
        f"| 第 {repeat} 次 | {values['對']} | {values['部分對']} | {values['錯']} |"
        for repeat, values in summary["per_repeat"].items()
    )
    rows = "\n".join(
        "| " + " | ".join([q["id"], q["kind"], *q["verdicts"]]) + " |"
        for q in summary["per_question"]
    )
    stable = "、".join(summary["all_three_correct"])
    base = "acceptance/20261012_117"
    block = f"""{BEGIN}
## 117 款新題：固定程式快照的 Brain 生成鏈驗收（2026-10-12）

**60 份回答：{scores['對']} 對／{scores['部分對']} 部分對／{scores['錯']} 錯，三次都完整答對 {len(summary['all_three_correct'])}/20 題。** 這輪測量與逐份評分已完成，但結果尚不支持「正式選型已可靠完成」。工具能提供結構化候選，模型仍可能漏叫、轉錯條件、漏列或改錯數字。這是當次凍結 checkout 的 Brain 生成鏈測量，不是最新程式或部署後 HTTP／語音驗收。

### 資料與測量範圍

唯讀凍結正式／dev 現有的 117 篇產品筆記、18 系列、`_catalog.yaml`、更正後型錄及 QA。沒有重新生成、校正或入庫筆記。新 20 題覆蓋 17 款完整清單、12 款電流／重量選型、兩現場、多欄排序與同分、HP／kW、m³/h／LPM、額定點與獨立最大值、null、價格／保固及著脫座重量缺資料。

標準答案由原始 frontmatter 的獨立手算／迴圈核對，沒有用正式 filter 引擎當 oracle；181 段引文及頁次逐字核對。題目、必要重點及禁止主張在模型生成前凍結，SHA-256 `{summary['questions_sha256']}`。來源見 [source_snapshot.json]({base}/source_snapshot.json)，規則及標準見 [questions.json]({base}/questions.json)。本輪沒有重新逐格對原始 PDF 圖片核驗全部 117 款，測量基準是此批已載資料的快照。

容器內私有 `/tmp` 副本載入當時 checkout `0759f4f` 的來源，實際呼叫 `prepare_generation → execute_generation → finalize_generation(persist=False)`；每份新 session、空歷史、正常 user metadata。每輪決策、prompt、工具選擇、fast 限制、語音字數策略與模型備援沿用原程式。實際回答／條件呼叫 {summary['answer_stage_llm_calls']} 次、provider 嘗試 {summary['answer_stage_provider_attempts']} 次，均為 `gemini/gemini-3.5-flash-lite`，temperature 0.3；另有 {summary['decision_provider_calls']} 次實際每輪決策呼叫。兩題 probe 的 {summary['probe_llm_calls_separate']} 次回答／條件呼叫及 {summary['probe_decision_calls_separate']} 次決策另存，不混入 60 份計分。標準答案未送回答模型，沒有以模型自評代替原文評分。

程式來源在 11:28（Asia/Taipei）封存，完整逐檔 SHA-256 在 `results.json.checkout.source_manifest`。測量後另有工作線提交 `9134101`，修改 `agent_loop.py`、`chat_service.py`、Live helper 及測試；私有副本不受這些變更影響，這批結果也不代表該新版本已驗收。session 建立／歷史／限制與持久化被隔離，PII 偵測整體停用，用量／recall 審計不落檔；暫存與本目錄產物仍可寫，唯讀主張僅指受保護的 workspace／LanceDB。

### 回答評分

| 批次 | 對 | 部分對 | 錯 |
|---|---:|---:|---:|
{repeats}
| 合計 | {scores['對']} | {scores['部分對']} | {scores['錯']} |

| 題號 | 題型 | 第一次 | 第二次 | 第三次 |
|---|---|---|---|---|
{rows}

三次都完整答對：{stable}。完整回答在 [results.json]({base}/results.json)，每份的命中、缺項、錯誤、品質問題與來源依據在 `grading_F*.json`；`verify_artifacts.py` 從原始證據重建本機 `summary.json`，不另上版重複資料。評分由獨立代理逐份對照原文，主代理統一邊界判定；屬代理評閱，並非人類驗收。

判對必須滿足凍結的必要資訊；純漏款、數字、單位或限制判部分對，有實際錯誤主張判錯。中文口述數字與唯一可辨識的型號別名可接受，沒有為語音策略放寬數字要求。價格／保固六份均沒有捏造，但只有說未載，漏了無法排名與需補各款報價／條款的必要限定，全部部分對。另有六份實質錯誤，部分對不能當作通過。

### 已確認的失誤

- **F04 第一次**：工具列出五款，回答稱四款、漏 100STEEL-5.50 的 1000 LPM 邊界，並把 100DIVA-5.50 寫成不存在的 100DIVT-5.50。
- **F06 第一次與第三次**：第一次把 50EUS-5.20、80EUS-5.20 的額定 315 LPM／18.9 m³/h 改成 250／15；第三次稱五款「皆超過」250 LPM，但兩個 C 版剛好等於門檻。
- **F11／F12／F14**：三次都未完整答對；雙現場漏乙候選或逐款數字，額定點候選只列一到兩款，電流／重量清單每次漏 50STEEL-5.05。這些題即使部分規格正確仍不能宣稱完整選型。
- **F16 第二次**：把來源未載的 EUSR 不鏽鋼材質補進回答；另外兩次欠完整清單／揚程或原廠確認限制。
- **F17**：第一次錯稱兩口徑水力數字不同，第二次稱型錄僅列 8 吋；第三次保留正確 8 吋數字但稱未見 6 吋，列部分對及來源品質問題。實際兩款都是 15 kW、15 m @ 4000 LPM、最大揚程 22 m、最大流量 6200 LPM。

### 工具、延遲與資料完整性

60 份均有 `search_knowledge`。F01–F17 的 51 份選型／規格比較，有 {summary['tools'].get('filter_products', 0)} 份呼叫 `filter_products`，39 次成功、1 次因 F05 第二次 `in` 參數格式錯誤被拒絕；39 次成功輸出逐值／排序重算一致，沒有發現運算或未知分類差異。剩餘 11 份未呼叫（含 F13、F17 的直接型號比較）；F18–F20 九份價格／保固／整套重量另外列，不當作應有數值篩選的空集合。

條件語意錯誤 3 份：F02 第一次、第三次把單相轉成 `phase in [1,1,3]`，本資料剛好同集合，也不能當成條件轉換正確；F05 第二次格式錯。另有 17 份出現工具工作流程缺項，例如少傳排序／前三名／分系列冠軍、額定點候選三次漏叫、粒徑缺值在回答端才處理。缺項計數可能重疊，且未傳 limit 但模型最後仍排對前三名時，回答分數可保持正確。參數能執行、條件符合提問、工具計算正確與最後回答完整，分開稽核，見 [tool_audit.json]({base}/tool_audit.json)；工具輸出不代替回答得分。

Brain 生成耗時中位數 {summary['timing_seconds']['p50']:.2f} 秒、p90 {summary['timing_seconds']['p90_nearest_rank']:.2f} 秒，排除 HTTP／Backend／ASR／TTS，不能與舊 `/api/v1/chat` 延遲直接比。前後正式與 dev 的 workspace／LanceDB 共 967 個檔案，SHA-256 均為 `{summary['integrity']['sha256_before']}`，零變更；probe 也零變更。

原始鏡像檢查前後都 **exit 1**，保留 `.doc_meta.json` 差異。99 筆差異是自動語言快取（含 `_catalog.yaml` 的快取新增項）；只用原解析器補算缺少的語言及來源，不刪其他鍵，完整 129 筆 metadata 解析後相同，knowledge 文件內容相同。證據見 [parity_verification.json]({base}/parity_verification.json)。沒有為了讓檢查變綠而 sync、reindex 或覆寫 metadata，也沒有宣稱兩專案所有人格／歷史文件完全相同。

### 驗證與後續判斷

工具入口回歸 39 個在主機及既有 API 容器隔離程序通過。決策設定測試原本用小寫 constructor 參數，而該欄位實際以大寫 validation alias 驗證；本次修正測試，覆蓋 constructor 與環境變數，不改正式設定程式。相關測試 37 個通過，第一次 Brain 非 integration 全套 1,237 passed、1 skipped、15 deselected；測量後 reads helper 重整也納入最後一次完整單元測試，**1,243 passed、1 skipped、15 deselected**。這次單元測試不取代該新版本的聊天正確率驗收，檢查紀錄見 [verification_checks.json]({base}/verification_checks.json)。

結構化筆記與篩選可以補足向量片段無法完整列舉的規格，但舊 C 組 55／2／3 不能直接外推到這 117 款的正式生成策略；資料、題目、可用參考及回答限制都不同，本輪也沒有 A／B／C／D 同題對照。下一步應針對漏叫／過寬條件與回答重新改寫工具數字的問題改進，再以另外凍結的新題及 HTTP／語音測量驗證，避免為本批分數調整標準。

測量階段沒有部署、重啟／重建、改 `.env`、寫入 workspace／LanceDB 或執行 Git 寫入；後續版本整理另按使用者授權提交。容器 `/app` 的執行程式未被私有副本取代，完整 HTTP 驗證、session 限制／持久化、PII 流程、Frontend、Backend、ASR、TTS、SDK 及 protocol contracts 均不在這輪測量範圍。既有 QA 格式與操作流程未改；產品工具沿用原問答生成鏈。
{END}

"""
    text = REPORT.read_text()
    if BEGIN in text:
        first, tail = text.split(BEGIN, 1)
        _, rest = tail.split(END, 1)
        text = first + block + rest.lstrip("\n")
    else:
        marker = "## 第一輪：EUS（2026-10-05）"
        assert marker in text
        text = text.replace(marker, block + marker, 1)
    intro = "目前結論：\n"
    latest = (
        "\n2026-10-12 新題驗收：117 款、20 題×3 次，"
        f"**{scores['對']} 對／{scores['部分對']} 部分對／{scores['錯']} 錯**。"
        "固定快照的生成鏈驗收已跑完，仍有漏款與錯誤主張；詳見下方 117 款一節。\n"
    )
    if "2026-10-12 新題驗收：" not in text:
        text = text.replace(intro, intro + latest, 1)
    text = text.replace(
        "- C新題與舊題的完整答對比例、三次都對題數及C／D配對差異分開報告；尚未測正式工具自主選擇、語音或完整agent loop。",
        "- 第三輪當時的C新題與舊題完整答對比例、三次都對題數及C／D配對差異分開報告；當時未測正式工具自主選擇、語音或完整agent loop。117款本輪範圍另列。",
    )
    REPORT.write_text(text)
    print("Updated existing REPORT.md; historical round bodies and raw answers preserved")


if __name__ == "__main__":
    main()
