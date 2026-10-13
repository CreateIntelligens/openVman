# 產品筆記實驗

> 資料去識別化：發布的實驗 JSON 附件已將客戶專案名稱／ID 與隨機 trace ID 改為示例別名；純題號與重複次數組成的關聯 ID 保留。欄位結構、數字、評分、商品型號及原始商品型錄／產品筆記內容雜湊不變。附件一致性 checksum 已按匿名化後的發布內容更新；規格表索引的客戶名稱註解也已匿名並更新其 checksum。歷史回答中的專案自稱也已匿名，數據仍代表匿名化前的原測量；重播部署流程前須以自身專案 ID 覆寫示例值。

AI 讀型錄、為每個型號產生 Obsidian 式筆記，看能不能改善跨產品選型問答。

| 檔案 | 內容 |
|---|---|
| [REPORT.md](REPORT.md) | 結論，一輪一節 |
| [TASK.md](TASK.md) | 最近一次的交辦；下一輪直接改這份 |
| [WORKFLOW.md](WORKFLOW.md) | 新資料的固定驗收步驟、MD／CSV 分工與單一離線檢查入口 |
| `round1/` | 第一輪（EUS 5 組型號、10 題）：腳本、`notes/`、`questions.json`、`results.json`、核對與評分 |
| `round2/` | 第二輪（EUB-M＋EDW 15 列、12 題）：同上，另有 `filter_engine.py` 與它的單元測試 |
| `round3/` | 第三輪（同15列、20題、A／B／C／D各3次）：生成／評測／凍結／驗證腳本、15篇合格筆記、240筆回答與評分、唯讀摘要 |
| `acceptance/` | `filter_products` 正式路徑驗收（2026-10-06）：部署前 `/api/v1/chat` 20 題×1、容器內 20 題×3、部署後 `/api/v1/chat` 20 題×3 的原始回答與評分，評分規則沿用 `round3/questions.json`；結論在 `docs/plans/product-spec-filter.md` |
| `acceptance/20261012_117/` | 117 款／18 系列的新題驗收：先凍結 20 題與獨立標準答案，再以 11:28 封存 checkout 的 Brain 生成鏈跑 60 個新 session；保存原始回答、工具／決策紀錄、逐份評分、來源快照及唯讀證據，結果見同一份 `REPORT.md` |
| `round3/freeze_questions.py` | 前12題與評分規則原樣沿用，新增8題手算及raw cells獨立驗證；生成回答前凍結雜湊，重跑只核對 |
| `round3/note_validation.py`、`test_note_validation.py` | frontmatter、額定點／獨立最大值、禁止額外推論與頁碼／逐行來源的生成閘門與測試 |
| `round3/generation_preflight.json` | 前置4次驗證失敗回覆與usage；候選未參與評測，但呼叫及token納入總量 |
| `round3/finalize_report.py` | 合併240筆唯一評分，按舊／新題與重複次數彙整，直接更新同一份上層 `REPORT.md` |

## 重現

在 repo 根目錄執行，需要能 `docker exec` 進既有的 `openvman-api-1`（從 Claude 外掛派出的 Codex 會被沙盒擋住 docker.sock，要手動開 Codex）。不安裝套件。

```bash
# 第三輪：只核對既有證據，不重新呼叫模型
python3 -B scripts/experiments/product-notes/round3/freeze_questions.py
python3 -B scripts/experiments/product-notes/round3/test_note_validation.py
python3 -B scripts/experiments/product-notes/round3/test_filter_engine.py
python3 -B scripts/experiments/product-notes/round3/test_runner_guards.py
python3 -B scripts/experiments/product-notes/round3/verify_artifacts.py
# 第三輪：完整重新測量；--fresh先保存舊產物，再清除舊結果／評分／checkpoint
python3 -B scripts/experiments/product-notes/round3/generate_notes.py --fresh
python3 -B scripts/experiments/product-notes/round3/evaluate.py
python3 -B scripts/experiments/product-notes/round3/prepare_grading.py
python3 -B scripts/experiments/product-notes/round3/verify_artifacts.py
# 獨立逐份對照凍結required_points／forbidden_claims及原文，重新產生grading_*.json後：
python3 -B scripts/experiments/product-notes/round3/finalize_report.py
python3 -B scripts/experiments/product-notes/round3/verify_artifacts.py
# 第二輪
python3 -B scripts/experiments/product-notes/round2/test_filter_engine.py
python3 -B scripts/experiments/product-notes/round2/generate_notes.py
python3 -B scripts/experiments/product-notes/round2/evaluate.py
python3 -B scripts/experiments/product-notes/round2/verify_artifacts.py
# 第一輪
python3 -B scripts/experiments/product-notes/round1/generate_notes.py
python3 -B scripts/experiments/product-notes/round1/evaluate.py
python3 -B scripts/experiments/product-notes/round1/verify_artifacts.py
```

117 款驗收的既有證據可以離線重核，不會重新呼叫模型：

```bash
python3 -B scripts/experiments/product-notes/acceptance/20261012_117/check_offline.py
# 需要以已核對的評分更新同一份報告時，再加 --update-report
```

Git 保存腳本、凍結題目、原始回答、獨立評分、來源快照與核對證據。117 篇 `notes/*.md`、`source_catalog.md`、`catalog.yaml` 是來源快照的逐位元組副本，`answers_for_grading_*.json` 與 `summary.json` 是原始回答及評分的派生資料，均不重複上版。`freeze_questions.py` 自動補回缺少的來源副本，`prepare_grading.py` 重建評分輸入，`verify_artifacts.py` 重建彙整；若現有副本被修改，會停止而不覆蓋。整套離線核對不需要正式服務或呼叫模型；需要 Python 的 PyYAML。

`check_behavior_parity.py` 另透過既有 API 容器唯讀核對兩專案的知識文件與自動語言快取。117 款這批原始 `project_mirror.py check` 為 exit 1：99 筆語言快取差異，僅補算缺少的 `language/language_source` 後，完整 129 筆 metadata 相同；不丟棄其他鍵，也不寫回或 sync。這是 metadata 解析與知識資料的一致性檢查，不代表兩專案的所有人格或歷史文件都相同。

既有結果不覆寫。要重新生成，使用 `run_acceptance.py --full --questions-sha256 <questions.json 的 SHA-256> --run-label <新名稱>`；新名稱的 checkpoint、結果及鏡像證據另存，不混入本批分數。`--probe 2` 只作前置測試，不進入 60 份計分。新回答必須另建對應評分與完整性證據，不能沿用本批評分。

新資料的流程可重跑，但這份題目、手算 oracle 及來源雜湊固定對應 2026-10-12 的 117 款，不能把新型錄覆蓋進舊快照。收到新資料時，另建日期／批次目錄，核對來源與模型規格，更新必要題目及獨立標準答案，先凍結再生成、逐份重新評分，最後更新同一份 REPORT 的新批次結果。同資料離線重建可以逐位元組核對；重新呼叫 LLM 的文字與分數不保證完全一致。完整重新生成還需當時相容的程式與執行設定，版本雜湊會另外記錄。

- 生成與評測會重新呼叫 LLM、覆寫該輪的產物；重跑後要重新核對筆記、重新評分，不能沿用舊的評分。
- 上一項覆寫說明適用第一、二輪。第三輪完成的生成預設拒絕覆寫；完整重跑需 `generate_notes.py --fresh`，先把舊JSON／JSONL／notes保存為git忽略的 `archived_measurement_<UTC>.full.json`，再清除舊生成／回答／評分／評分輸入／checkpoint／audit，保留凍結題目與來源。失敗的生成預設從原合格筆記與完整calls續跑，只整篇重生缺少的筆記。評測遇到既有checkpoint或results會停止，避免無聲覆蓋。
- 各輪的 `questions.json` 在回答生成前凍結；來源快照 `source_catalog.md` 跟容器裡的型錄不同時腳本會停止。
- 第一、二輪 `finalize_report.py` 把評分併進 `results.json`，並在該輪資料夾寫一份報告草稿；定稿要搬進上層 `REPORT.md` 對應的那一節，不要留第二份報告。
- 第三輪 `finalize_report.py` **直接更新同一份上層 `REPORT.md`**，保留第一、二輪正文、更新頂端總表與目前結論、替換第三輪節，不另建報告。
- 第三輪評分介面：`grading_*.json` 可為list或`{"grades": [...]}`；每筆必須包含 `id/repeat/arm/verdict/reason/matched_points/missing_points/false_claims/source_lines/quality_issues`。`repeat`為1～3、`arm`為A～D、`verdict`為對／部分對／錯；必須剛好240組唯一 `(id, repeat, arm)`，缺漏或重複會停止，不挑最佳一次。
- 每批另保存 `answers_for_grading_Rn_Qxx_Qyy.json`，包含 `grading_rubric`、oracle `questions` 與 `answers`（每列有id、repeat、A～D的answer／reference_chars）。彙整前必須240份輸入文字與當次results逐字一致，reference_chars一致；評分檔可加 `input_sha256` 固定對應pack，雜湊不符或仍是舊回答會停止。
- 重新生成筆記或重新評測後，必須逐份**重新評分**並替換舊 `grading_*.json`，再跑驗證、彙整；沿用舊評分不能代表新回答。不要同時保留新舊兩份重複評分檔。第三輪的前置失敗候選不參與回答，但4次呼叫及usage完整計入；中斷後續跑也保留原合格筆記、拒絕紀錄與所有呼叫。前置4次與續跑前17次回覆缺route_attempts紀錄，供應商嘗試總數保留未知，呼叫與token可完整統計。

## 寫入邊界

- 容器內唯讀：只讀既有 workspace／LanceDB，擋掉 Python 對 `/data` 的寫入，停用該子程序的用量／PII／recall 寫入。正式 api 行程與設定不改。
- 工業示範專案（開發） 的 workspace 與 LanceDB 不改；前三輪前後 `scripts/project_mirror.py check` 為 exit 0。117 款新驗收保留實際 exit 1 與獨立語言快取解析證據，不把差異改標為成功。
- 筆記向量只在記憶體裡算，不建表、不 reindex。
- 中途 checkpoint 與完整逐檔雜湊（`*_checkpoint.json`、`*_checkpoint.jsonl`、`*.full.json`）不進 git（`.gitignore`）；提交的結果把逐檔雜湊縮成檔案數與總雜湊。
- 前三輪實驗沒有變更正式 Brain、Backend、前台、管理介面、SDK 或 API contract。117 款驗收載入固定 checkout 快照的 Brain 生成鏈；隔離 session／用量等寫入，停用該測量程序的 PII 偵測，不經 HTTP、Backend、前台、ASR 或 TTS，也沒有部署。另修正決策設定測試的 alias 傳參，不改正式設定載入行為。第一、二輪及這次驗收記在根目錄 `CHANGELOG.md`；第三輪依交辦範圍記在 `round3/CHANGELOG.md`。
