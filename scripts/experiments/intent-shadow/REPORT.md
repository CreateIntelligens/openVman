# Embedding 意圖影子模式評估

日期：2026-09-20。結論：**保留為觀測，不用來跳過 RAG**。固定 64 筆獨立合成案例答對 52 筆（81.25%），包含一筆 knowledge→chat 錯誤。

## 方法與結果

沿用既有 BGE-M3 服務，使用 intent-centroid-v1 四類固定 centroid；先凍結案例及分類範例，再執行評估，未依結果調整分類範例或標籤。每類 16 筆，含歷史對話、否定、引用、ASR 錯字與主題切換。

| 正確類別 | 判為 chat | knowledge | web | clarify |
|---|---:|---:|---:|---:|
| chat | 15 | 0 | 1 | 0 |
| knowledge | 1 | 12 | 3 | 0 |
| web | 1 | 0 | 15 | 0 |
| clarify | 0 | 2 | 4 | 10 |

暖機約 339 ms；暖機後 64 筆分類 p50 **53.94 ms**、p95 **57.35 ms**，請求錯誤 0。這是分類器的串行耗時，不是聊天端到端延遲，也不是高併發負載測試。

分類的主要問題是含糊問題被過早判為可搜尋，以及內部知識問題誤判為外部搜尋或閒聊。合成集的類別分布與實際流量不同；與先前 SemIf 報告不是同一份資料，不能直接當成勝負比較。

## 錯誤案例索引

對照 cases.jsonl 查看原始問題與歷史；逐筆分數保留於 results.json。

| ID | 預期 | 建議 |
|---|---|---|
| intent-013 | chat | web |
| intent-024 | knowledge | web |
| intent-028 | knowledge | web |
| intent-029 | knowledge | web |
| intent-030 | knowledge | chat |
| intent-046 | web | chat |
| intent-058 | clarify | web |
| intent-059 | clarify | web |
| intent-060 | clarify | knowledge |
| intent-061 | clarify | web |
| intent-062 | clarify | web |
| intent-063 | clarify | knowledge |

## 實際服務及故障驗證

在既有 api 容器內的獨立程序呼叫真實 embedding 服務，未重啟或替換正式應用程式。smoke.json 記錄：

- 提交耗時約 0.75 ms，背景冷啟動分類約 491 ms。
- 第一筆未完成時，第二筆立即略過，沒有等待佇列。
- 使用程序內 loopback HTTP 測試伺服器注入真實 read timeout；提交耗時約 0.07 ms，背景約 97 ms 後記錄錯誤，釋放容量並進入冷卻。
- 沒有呼叫正式聊天 LLM，也沒有修改正式對話資料。這是元件 smoke，不代表完整使用者對話延遲已量測。

容器內 Brain 非 integration 全套測試：**860 passed、1 failed、1 skipped、15 deselected**。唯一失敗 tests/test_a2a_skill.py::test_a2a_send_task_validation 在乾淨 HEAD 快照亦失敗：預期 Missing required fields，實際 target_agent_id is required。本次未修改該既有差異。

## 重現與追溯

cases.jsonl 與 results.json 記錄 fixture、classifier、prototype SHA-256、identity 與逐筆資料；README.fixture.md 說明標籤政策。評估不需要開啟 INTENT_SHADOW_ENABLED。

在包含此版本來源碼及既有 embedding 設定的 api 容器內執行（路徑依容器來源碼位置調整）：

```bash
PYTHONPATH=/app python /path/to/intent-shadow/evaluate.py   --module /app/core/intent_shadow.py
```

evaluate.py 的同一目錄需有 cases.jsonl，stdout 為 JSON。請保留本次 results.json 作為基準；後續更換分類範例應另建版本與獨立評估集。既有服務必須可用並具備原有憑證，請勿把憑證寫入結果檔。

本次功能預設關閉，未修改正式 .env，未部署；操作契約見 [意圖影子模式](../../../docs/intent-shadow.md)。

## 程式整理後的驗證

2026-09-20 將 centroid 初始化與 query 評分分開，集中輸入長度常數並清理測試設定。以固定測試向量比較整理前後的 64 筆案例，加一筆超長歷史／訊息，共 65 筆：分類輸出、輸入截斷及 embedding 呼叫完全相同。這是程式等價檢查，沒有重跑真實模型，也不產生新的準確率或延遲數據。

results.json 的 classifier_sha256 保留原實測版本，並非整理後檔案的 hash；資料集、分類範例與原始結果未更動。
