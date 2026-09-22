# Jev 決策層：意圖分流影子觀測 → RAG 證據判斷

狀態：Draft。範圍：把官方 Jev API（typesafe-sdk）接進 Brain 當**決策層**，第一階段
只做影子觀測不改路由；第二階段用同一條線做 RAG 證據判斷。SemIf 本機實驗退場。

前提：這份計畫基於 [Jev 評估報告](../../scripts/experiments/jev/REPORT.md)
（2026-09-22，96/96、零翻轉）與另一個 session 的場景排序。那份排序的結論我同意，
但它沒把兩個決定性的數字攤開，這裡先補上。

---

## 0. 先回答的兩個問題

### 0.1 SemIf 順序敏感的結論適不適用於 Jev？

**不適用。** SemIf 的「21/32 題隨排列改答案」是本機 4B 模型的結果。Jev 在**同一份
fixture**（SHA256 `a1c635c…`）上正序反序都 32/32，翻轉 0。這不是「再測一次」，是換
了推論來源後問題消失。所以 09-21 那個「不接管正式路由」的決定是對 SemIf 下的，
不自動延伸到 Jev。

### 0.2 跳過檢索省得了多少？

**省不了多少，這改變了優先 1 的價值主張。** 唯一實測樣本（2026-09-22 14:32 那筆
trace）：`search_knowledge` 387 ms，整輪 `/brain/chat` 4718 ms，**檢索佔 8%**。09-17
基準也說瓶頸在 LLM 生成（4–9 s）與 TTS，不在檢索。

所以優先 1「純閒聊跳過檢索」的價值**不是延遲**，是：

- 少一次無謂檢索 → 少塞一段不相關的 context 給 LLM → 回答比較不會被知識庫帶偏
- 這是品質問題，跟優先 2 是同一件事的兩端

這個發現讓我更確定**先做優先 1 的影子觀測只是為了驗 Jev 的繁中泛化，真正的產品
價值在優先 2**。

### 0.3 SemIf 可以拿掉嗎？

**可執行的部分可以拿，證據要留。** 它在正式程式碼裡零接線（`git grep -i semif` 只
命中 `scripts/experiments/semif/` 與三處文件連結）。但 `results/stability*/` 被兩個
已寫進報告的結論引用，`cases.jsonl` 是 Jev 報告的 fixture——刪了結論就不可查證。
所以是「刪 compose 與 runner、留 results 與 fixture」，見 §4。

## 1. 為什麼是 Jev、不是 BGE 影子

`embedding-intent-shadow`（BGE-M3 prototype 分流）已經在跑影子模式，52/64。Jev 在
同一份 32 題上 32/32 vs BGE 27/32，差 5 題。但 Jev 是外部 API：

| | BGE-M3 影子 | Jev |
|---|---|---|
| 準確率（開發集） | 84.4% | 100% |
| 順序敏感 | 無（embedding 沒有選項順序） | 無（實測零翻轉） |
| p50 延遲 | 71 ms（本機） | 258 ms（含台灣→美西） |
| 費用 | 0 | **待查**——REPORT 明說沒拿到計費頁 |
| 外部依賴 | 無 | API key、網路、供應商 SLA |
| 資料外送 | 無 | **使用者訊息會送出去** |

最後兩列是 BGE 影子沒有、Jev 必須處理的。§2 的設計圍繞這兩點。

## 2. 第一階段：意圖分流影子觀測

### 2.1 不做什麼

- 不改 `RouteDecision`、不改 prompt、不改工具選擇、不跳過任何檢索。
- 不取代 BGE 影子；**兩個並排跑**，同一筆訊息兩邊都記，才比得出差異。
- 不在 SSE／即時語音路徑上呼叫（那條路延遲敏感，且已有 Guard）。

### 2.2 怎麼接

沿用 `brain/api/core/intent_shadow.py` 的骨架（每 process 一個背景任務、不排隊、
抽樣、短 timeout、失敗冷卻），加一個 `JevIntentObserver`：

- 抽樣率獨立設定 `JEV_SHADOW_SAMPLE_RATE`，預設 **0.05**（BGE 是 0.1）。它有費用
  與外送，起步要更保守。
- timeout **600 ms**（p95 是 322 ms，留一倍餘裕），逾時就記 `timeout`，不重試。
- 失敗冷卻 60 s：API 掛了不要每筆都打。
- **只送當前訊息 + 前一輪助手回覆的前 200 字**。不送 session 全文、不送知識庫內容、
  不送帳號資訊。這是外送邊界，寫死在 observer 裡，不由設定放寬。
- 記錄：trace_id、project_id、Jev 分類、BGE 分類、實際走的 route、Jev 延遲、
  token 用量。**不記原文**（跟 BGE 影子一樣）。

### 2.3 費用閘門

REPORT 說費率待查。**接線前先查清楚**，並在 observer 加硬上限
`JEV_SHADOW_DAILY_CALL_CAP`（預設 2000），到了就靜默停到隔天。用量寫進既有的
`usage.db`（見 [[usage-credit-design]]），跟 LLM token 同一張表。

### 2.4 驗收

- 跑 7 天、抽樣 5%，拿到至少 500 筆有 Jev 結果的樣本。
- **關鍵指標是漏檢率**：實際 route 走了 `search_knowledge` 且有命中，但 Jev 判成
  「純閒聊」的比例。這是把閒聊判斷拿去跳過檢索時會出事的那類錯。目標 < 2%。
- 次要：Jev 與 BGE 不一致的樣本人工看 50 筆，記下 Jev 錯的模式。
- 延遲：Jev p95 在正式流量下 < 500 ms，timeout 率 < 1%。
- 費用：7 天實際花費對照計費頁，確認 §2.3 的上限設得對。

過了才進 §3。沒過就停在影子，寫報告。

## 3. 第二階段：RAG 證據判斷

這是真正的產品價值所在，但**等 §2 驗過 Jev 的繁中泛化再做**。

### 3.1 問題

「問 A 型號的限制，搜到同系列 B 型號。」語意相近、向量分數高，但不能拿來答。
現在 Brain 會把它塞給 LLM，LLM 要嘛答錯型號、要嘛混著講。EVAK 型錄那 50 題 QA
裡就有這種對子。

### 3.2 判斷什麼

對每個檢索命中的段落，Jev 回一個四值之一：

| 標記 | 意思 | 第一版怎麼用 |
|---|---|---|
| `direct` | 對應問題的主體（型號／對象），且有直接證據 | 照常送 LLM |
| `background` | 相關背景，答不了問題本身 | 照常送，**但記錄** |
| `conflict` | 與問題前提衝突（型號不同、規格矛盾） | 照常送，記錄 |
| `insufficient` | 不足以回答，該補查或澄清 | 照常送，記錄 |

第一版**只標記不過濾**——跟 §2 一樣影子。要驗的是 Jev 會不會把 `direct` 誤標成別的
（那是把關鍵證據濾掉的風險）。

### 3.3 為什麼這比優先 1 更值得

- 四值不是「四選一排列」——每個段落獨立判斷，選項順序不影響。
- 不需要 session 上下文，只送「問題 + 一段」，外送邊界更窄。
- 有現成標準答案：EVAK 50 題 QA 的每一題都知道正確段落在哪，可以直接算
  precision／recall，不用等線上流量。
- 一旦 `direct` 的 recall 夠高，過濾 `conflict` 就能直接減少答錯型號——這是使用者
  看得到的改善，跳過檢索省 387 ms 不是。

### 3.4 驗收

- 離線：EVAK 50 題，每題 top-5 段落，Jev 標記對照人工標。`direct` recall ≥ 95%
  （寧可多放不可漏），`conflict` precision ≥ 90%。
- 線上影子：同 §2.4 的流程，額外看「LLM 最終回答有沒有用到被標 `conflict` 的段落」。

## 4. SemIf 退場

原本想整個目錄刪掉，盤了引用後改成「刪可執行的、留證據」：

- `results/stability/` 與 `results/stability-0p8b/` 被**兩個獨立結論**引用——SemIf 自己的
  「順序敏感」與 `browser-intent/P0-COMPATIBILITY.md` 的 0.8B 對比。裡面的
  `metadata.json`（完整排程與 fixture hash）和 `runner_used.py` 是讓那 2,304 次結果可
  重現的東西。刪了等於把已經寫進報告的結論變成不可查證。
- `cases.jsonl` 是 Jev 報告的 fixture（同一個 SHA256），`run_jev.py:28` 直接讀
  `../semif/cases.jsonl`。

所以：

| 動作 | 檔案 |
|---|---|
| **刪** | `compose.yaml`、`run.py`、`baseline.py`、`stability.py`、`test_stability.py`、`__pycache__/`、`README.baseline.md`、`results/run.log`、`results/prompt-v2.log` |
| **留**（改名為 `scripts/experiments/semif-evidence/`） | `cases.jsonl`、`README.fixture.md`、`REPORT.md`、`results/**/*.json`、`results/**/predictions.jsonl`、`results/stability/runner_used.py` |
| **改** | `run_jev.py:28` 指到新路徑；`browser-intent/P0-COMPATIBILITY.md` 兩處路徑；`README.md:331`、`brain/README.md:739`、`docs/README.md:39` 改指 Jev 報告，SemIf 一句話帶過並連到 evidence 目錄 |

`semif/README.md`（操作手冊）刪掉——它教的是怎麼跑一個不再存在的實驗。REPORT.md 留，
它是結論。CHANGELOG 一條 Removed。**不刪** `browser-intent/`，那是另一個問題。

## 5. 不做的事

- 語音打斷不換 Jev。REPORT 裡 Jev 16/16 對 GuardAgent 9/16 看起來很好，但
  GuardAgent 是 0.003 ms in-process、Jev 是 275 ms 網路往返——插話判斷慢 275 ms
  使用者感覺得到。而且 partial ASR 接線本來就不完整（見 [[latency-baseline-2026-09]]），
  先修那個。
- 醫療安全熔斷不交給 Jev 單獨決定。可以當額外訊號，不能當閘門。
- 多輪對話上下文選擇（那份排序的優先 3）：等 §2、§3 都有結果再說，現在沒有證據
  Jev 在這件事上比首尾截斷好。

## 6. 風險

- **資料外送**：§2.2 的邊界是唯一防線，要有測試釘住「observer 送出的 payload 不含
  session 全文、不含知識庫段落」——§3 會送段落，那是另一個 observer，邊界分開寫。
- **費用失控**：§2.3 的日上限是硬的，不是提醒。
- **供應商依賴**：影子階段掛了沒事；若之後真的接管路由，要有 BGE 或規則的 fallback。
  現在不設計，但 §2 的 observer 介面要讓 §3 之後能換成同步呼叫。
- **開發集過擬合**：96/96 是 48 筆合成題。§2.4 的 500 筆線上樣本才是第一次真的
  泛化測試。
