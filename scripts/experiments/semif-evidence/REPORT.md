# SemIf 本機可行性實測

日期：2026-09-19（Asia/Taipei）。範圍：離線合成案例；沒有接入正式流量。

## 判斷

架構建議是「推論獨立 service，分類政策整合在 openVman」，可先放同一 repository／Docker Compose，不必另開專案。推論 service 若日後建立，只提供選項評分；Brain／Backend 控制權限、路由、逾時 fallback 與明確停止規則。

**本輪不建議讓此模型設定接管正式分流。** 同一批輸入只反轉選項順序，就有大量答案改變；補充路由規則後仍存在。不要只採用較好的選項排列、把開發集高分視為泛化能力，或把分數當成校準過的信心。

## 結果

| 方法 | 原順序正確數 | 反轉選項正確數 | 原順序 p50 | 原順序 p95 |
|---|---:|---:|---:|---:|
| BGE-M3 prototype 分流 | 27/32（84.4%） | — | 71.0 ms | 94.8 ms |
| SemIf 分流，初始規則 | 20/32（62.5%） | 29/32（90.6%） | 412.2 ms | 479.8 ms |
| SemIf 分流，補充規則 | 19/32（59.4%） | 31/32（96.9%） | 421.1 ms | 521.5 ms |
| SemIf 語音打斷 | 15/16（93.8%） | 14/16（87.5%） | 413.7 ms | 527.1 ms |
| 現有 GuardAgent 語音打斷 | 9/16（56.3%） | — | 0.0026 ms | 0.0270 ms |

分流初始規則：反轉選項造成 **13/32** 答案翻轉。補充「是在選處理路徑，不是在判斷已知答案」後，仍有 **14/32** 翻轉。第二輪是看過第一輪結果後的開發調整，並非獨立保留集；沒有改 gold 或挑掉難題。所有原始失敗結果均保留。

語音打斷：SemIf 原順序修正了「停」被忽略、「不用停，繼續說」被打斷等錯誤，但仍把「好」當成打斷。反轉順序後多誤判「這段我懂了，請繼續下一段」。約 0.4 秒的額外延遲，不適合擋在明確停止指令前；若繼續驗證，僅考慮模糊語句的輔助判斷。

初始分流還出現約 0.99 分卻錯誤的案例；不能直接用 0.9 門檻採信。這不證明所有 SemIf 模型或 BF16 版本都失敗，只反映本機模型、量化、提示與 runtime 的組合。

## 方法與環境

- 32 筆四分類 routing、16 筆 STOP／IGNORE；均是人工合成繁體中文，包含否定、ASR 同音字、引用與上下文，不是真實用戶抽樣。
- 使用 SemIf 固定 commit 的原始 core.py/direct.py 評分程式；Qwen3.5-4B 固定 revision，以 bitsandbytes NF4 double quant / BF16 compute 載入。
- RTX A4000 16 GB；模型推論峰值 allocated **2.98 GiB**、reserved **3.06 GiB**，不含全部 CUDA／驅動程序開銷。不是整個服務的容量估算。
- 初次下載與載入約 260 秒，因缺 C compiler 而於首次推論失敗；只在測試容器補 gcc/libc6-dev 後完成。成功輪次快取載入約 11.2 秒。
- 原始輪 96 次、提示診斷輪 64 次，共 **160 筆**預測。沒有更換模型後只挑最好數字。
- SemIf 計時含 tokenizer、GPU forward 與結果取回，排除模型載入，先做一次暖機；尚非 HTTP service。Embedding 計時含既有服務 HTTP 與 JSON 解碼，不含 cosine 計算。Guard 是 in-process 規則呼叫，因此表中數字不是相同服務邊界的公平效能排名。
- 正式服務共用硬體，流量未控制；沒有進行併發、壓力、完整語音串流或端到端對話測試。16 筆樣本的 p95 等同最大值。
- BGE-M3 是以現有 embedding 服務配合獨立撰寫 prototype 建立的實驗分類器，不是目前正式 Brain 的路由。

## 後續建議

先保留正式流程。若繼續研究，應先建立獨立保留集與順序穩定性驗收，分辨提示、量化及模型能力的影響，再決定是否投入常駐服務。現有 embedding 基線已能以較小的新增負擔做初步分流，值得與更完整的分類器一併比較。GuardAgent 的明確停止／否定規則可以另外修正，但本次沒有修改它。

## 可重現證據

- [案例政策](README.fixture.md)。執行方式與基線方式的說明隨可執行的實驗一起退場
  （2026-09-22，見 `docs/plans/jev-decision-layer.md` §4）；模型、revision、NF4 設定
  與載入時間保留在 [環境與驗證](results/environment.json) 與各 `metadata.json`。
- [初始摘要](results/summary.json)、[初始逐筆結果](results/predictions.jsonl)
- [提示診斷摘要](results/prompt-v2/summary.json)、[診斷逐筆結果](results/prompt-v2/predictions.jsonl)
- [Guard／embedding 基線](results/baselines.json)、[環境與驗證](results/environment.json)

來源：[SemIf](https://github.com/TheoLeeCJ/SemIf/tree/ca3ba65f142967030ecb453346e94d6f476a69df)。權重與上游程式暫存於測試容器，repository 不收錄模型。


## 2026-09-20：後續確定性規則修正

依本次實驗發現修正 GuardAgent：單字停止優先、排除已識別的附和／否定停止／引用背景話，仍接受後續新問題；空辨識欄位的明確控制事件直接停止。修正版在原本 16 個語音合成案例為 16/16，這是已知開發案例的迴歸結果，不是保留集或生產準確率。上方原始基線數字、來源 hash 與原始測試檔案不變。新增獨立迴歸案例與 WebSocket 工作取消測試，詳見 backend/tests/live/test_guard_agent.py 和 backend/tests/gateway/test_websocket_interrupt.py；不採用 SemIf 推論。


修正驗證：84 項分類／中斷測試通過，另以真實 loopback WebSocket、token 驗證及正式 router 完成 6 個 smoke cases。完整 Backend 測試為 966 通過、1 失敗；失敗項目 test_queue_outbound_idempotency 在未修改的 HEAD 匯出版本亦可重現，與本次 GuardAgent 修正分開追蹤。此驗證未使用真實麥克風、外部 Brain／TTS，也未部署到正式服務。


## 2026-09-20：固定輸入與全排列穩定性

**結論：這組 SemIf＋Qwen3.5-4B NF4 設定的主要問題是選項順序敏感，不是同一輸入隨機跳動。暫不接管正式路由，也不因這份結果新增常駐推論服務。**

沿用 initial prompt、同一份 32 題 routing 開發案例、四個選項的原始描述、相同模型 revision／NF4 設定。全部 24 種排列各重跑 3 次，共 2,304 次評分；每輪固定 RNG seed 打散工作順序，沒有抽樣答案，也沒有調整 prompt 或 gold。

| 觀察 | 結果 |
|---|---:|
| 完全相同輸入組合 | 768 組，每組 3 次 |
| 同組三次答案翻轉 | 0 組 |
| 同組 probability／logit 最大差值 | 均為 0 |
| 換排列會改答案的案例 | **21/32（65.6%）** |
| 排除最高分同分後仍改答案 | **21/32** |
| 第一輪全部 24 種排列都答對 | 11/32 |
| 同一批題目，各排列正確數範圍 | **20/32–31/32（62.5%–96.9%）** |
| 全排列、全重跑平均正確率 | 1860/2304（80.73%） |
| 最高分同分 | 6 個題目／排列組合，各重跑 3 次，共 18 筆 |
| 與前次 initial 原序／反序重疊比較 | 64/64 的預測、分數、logits、prompt hash 一致 |
| 推論含前後處理 p50／p95 | 374.10／409.27 ms |
| PyTorch 峰值 allocated／reserved | 2.98／3.06 GiB |

平均準確率只描述這份開發集的全部排列，不能把 2,304 次重複量測當作 2,304 題獨立樣本，也不能只挑 96.9% 的排列宣稱改善。這次所有 knowledge 案例都沒有被判成 chat，但它們仍可能被判成其他不正確路徑；有限合成案例不足以證明能安全跳過檢索。

同分沿用上游選第一位置的規則；排除同分後仍有 21 題翻轉，因此不能把問題只歸因於 tie-break。選項排列同時改變文字順序與答案字母位置，本測試沒有進一步區分這兩者，也沒有隔離量化、模型本身或提示設計的個別影響。

這次是同一次模型載入內的三輪測試；與前次重疊的 64 筆一致提供額外重現證據，但不能保證其他硬體、runtime、模型版本或所有輸入都完全確定。共用 GPU 的延遲是觀察值，未做正式流量壓力測試。

### 證據及驗證

- [完整排程與環境](results/stability/metadata.json)
- [逐筆評分](results/stability/predictions.jsonl)、[統計摘要](results/stability/summary.json)
- [同分排除、位置分布與前次比較](results/stability/diagnostics.json)
- [推論時程式快照](results/stability/runner_used.py)——這是產生上述結果時實際執行的
  程式，可重現用它；原 `stability.py` 已隨實驗退場。

完整執行順序、每組三個不同 repeat、prompt hash、fixture／來源 hash 均已核對，另由獨立代理重新統計逐筆結果。七項摘要測試通過，涵蓋穩定基準、重跑翻轉與跨排列分開計算、資料缺漏、重複輪次、順序錯誤及 prompt 漂移。

本輪不再投入此設定的正式整合。若日後要繼續研究，應先另定模型／量化或提示方案，重跑同樣的穩定性驗收；改善後再以未參與調整的真實問句做比較。此次未部署、未變更正式路由，既有 BGE 影子功能仍維持原設定。
