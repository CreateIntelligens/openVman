# Jev 意圖影子模式

實驗功能的操作契約：只觀察、不控制正式路由，設定預設關閉。與
[Embedding 意圖影子](../intent-shadow/OPERATIONS.md)並排跑，同一筆訊息兩邊都記，
用 `trace_id` 對照。計畫與驗收條件見
[docs/plans/jev-decision-layer.md](../../../docs/plans/jev-decision-layer.md) §2。

## 設定

加進 Brain 讀的 `.env`，再按既有發布流程建置與更新 api 服務。

| 設定 | 預設值 | 範圍／意義 |
|---|---|---|
| `JEV_SHADOW_ENABLED` | false | 開啟 `/brain/chat` 的背景觀測 |
| `TYPESAFE_API_KEY` | 空 | TypeSafe API key；空值時即使啟用也不送 |
| `JEV_SHADOW_SAMPLE_RATE` | 0.05 | 0–1；符合條件回合的抽樣機率 |
| `JEV_SHADOW_TIMEOUT_SECONDS` | 0.6 | 大於 0、最多 5 秒；HTTP timeout，不重試 |
| `JEV_SHADOW_COOLDOWN_SECONDS` | 60 | 0–3600 秒；逾時或錯誤後暫停送出 |
| `JEV_SHADOW_DAILY_CALL_CAP` | 2000 | 每 process 每個 UTC 日最多送幾次；到了就停到隔天 |
| `JEV_SHADOW_BASE_URL` | `https://api.typesafe.ai` | 一般不需要改 |

每個 Brain process 最多一筆背景工作，忙碌就略過，不排隊。每日上限在 process
啟動後第一次送出時，從 `usage.db` 當天已記錄的 Jev 事件數補回，重啟不會歸零；
失敗的呼叫不進帳本，所以重啟後補回的只有成功次數。

## 外送邊界

使用者訊息會送到外部服務，這是這個功能唯一需要特別許可的地方（2026-09-23 經
使用者同意）。送出的 `state` 有兩個欄位，寫死在 `core/jev_shadow.py` 的
`jev_state()`，不由設定放寬：

- `message`：當前使用者訊息，最多 1024 字元
- `history`：與正式 LLM 看到的同一份對話歷史——`select_recent_messages()`，最近
  `max(SHORT_TERM_MEMORY_ROUNDS × 2, 8)` 則、每則壓縮到 600 字、總長 15000 字內——
  只留 user 與 assistant

不送 system prompt、工具結果、知識庫段落、帳號或 metadata。正式流程本來就把
對話送到外部 LLM，這裡對齊它；最初只送「助手上一句前 200 字」，dev 多輪實測中
使用者上一句提到的網址因此看不到而判錯，才改成與正式流程一致。
`tests/services/test_jev_shadow.py` 直接檢查送上線的 HTTP body 釘住這條邊界。

TypeSafe 條款（2026-09-23 查）：隱私政策承諾不以用戶資料訓練；DPA 保存期限只寫
「必要期間」，沒有具體天數；零保存需向 privacy@typesafe.ai 申請企業方案。

## 服務契約

`POST {JEV_SHADOW_BASE_URL}/v1/systemone`，`Authorization: Bearer <TYPESAFE_API_KEY>`。
Body 為 `state`（上述 JSON 字串）、`model=jev-latest`、一個 `choice` 題目，選項
chat、knowledge、web、clarify，題目與選項描述與 `run_jev.py` 的 routing 實驗一致。
回應選項不在四類之內一律視為錯誤。

## 費用

輸入每百萬 token US$0.042，輸出不計費（2026-09-23，typesafe.ai 首頁與發表文；
官方自承可能是補貼價）。無歷史時一次約 560 輸入 token，每日上限 2000 次約
US$0.05；帶多輪歷史會多一些，仍在每日一美元以下。上限的用途是擋住程式失控與限制外送量，不是控制花費。

每次成功呼叫以 `provider=typesafe`、`kind=intent_shadow` 記進 `usage.db`，
帶原請求的使用者、session、project、trace 歸屬。

## 記錄與排查

`event=jev_shadow` 的 JSON 寫入 Brain logger：

- 共同欄位：`trace_id`、`project_id`、`actual_route`
- `ok`：`suggestion`、`confidence`、`probabilities`、`model_version`、
  `input_tokens`、`output_tokens`、`elapsed_ms`、`input_truncated`
- `timeout`：`elapsed_ms`
- `error`：`error_type`、`http_status`（非 HTTP 錯誤為 null），不記例外內容
- `daily_cap`：當天已達上限

不記訊息原文。metrics store 另有 `jev_shadow_total`（依 status、suggestion）與
`jev_shadow_duration_ms`；status 另含 `sampled_out`、`busy`、`cooldown`、`no_key`。

`actual_route` 是粗粒度路由（例如 `tool`），不是實際執行的工具清單。§2.4 的漏檢率
需要「實際呼叫了 search_knowledge 且有命中」，要另外用 `trace_id` 對工具紀錄。
