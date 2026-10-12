# 帳號 API key 整合

API key 適用可信任的後端程式、CLI 與服務之間的串接。每把 key 對應一個正式帳號，沿用其角色與當下的資源權限；root 的 key 可操作 root 的應用 API，admin 的 key 仍受 admin 管理階層與資源上限限制。

## 建立與管理

後台「帳號 → API 金鑰」網址為 `/admin/accounts/api-keys`，公開子路徑部署需加 `/openvman`。已獲准進入後台的正式帳號也可由頁首入口管理自己的 key；這不會自動開啟原本沒有的後台訪問權限。管理員可選擇自己能管理的正式帳號，例如專供合作方串接的帳號。

輸入用途名稱及期限（介面預設 90 天，可不設期限）。建立後完整 key **只顯示一次**；複製後關閉，之後列表只提供識別前綴、期限、最近使用與請求次數。遺失時建立新 key 並撤銷舊 key。每個串接對象分別建立，便可獨立停用與查用量。

API 管理入口如下，皆需帳號登入 session（JWT Bearer 或同來源 Cookie），不接受 API key／Embed key 管理其他 key：

| 方法與路徑 | 請求 | 回應 |
|---|---|---|
| `GET /api/v1/api-keys` | 選填 query `user_id`，省略為自己 | `{"keys": [metadata, ...]}` |
| `POST /api/v1/api-keys` | JSON `label`、選填 `user_id`、`expires_at` | 201；metadata 加上僅這次提供的 `key` |
| `DELETE /api/v1/api-keys/{key_id}` | key 識別 ID | `{"ok": true}`；撤銷並保留紀錄 |

`label` 需 1～120 字元；`expires_at` 為含時區的未來 ISO 8601 時間，例如 `2027-01-10T00:00:00Z`，或 `null` 表示不設期限。臨時帳號不可持有長期 key。管理別人的 key 沿用帳號管理階層，不允許 admin 管理 root 或不在其管理範圍內的帳號。

代發另有權限上限：root 可替正式帳號發行；admin 替他人發行時，目標須為一般正式帳號，且發行當下的全部有效資源須在該 admin 的有效資源內。替其他 admin 發行需 root；admin 仍可依既有階層查看、撤銷其能管理的 admin key。發行後以所屬帳號權限為準，root 日後調整該帳號資源授權時，其所有 key 一起沿用新授權。

metadata 欄位為 `key_id`、`user_id`、`label`、`token_prefix`、`created_at`、`expires_at`、`revoked_at`、`last_used_at`、`request_count`。管理回應帶 `Cache-Control: no-store`。資料庫只保存高熵隨機 token 的 SHA-256；列表與 audit 不提供明文或雜湊。

## 呼叫 ASR 或其他應用 API

現有 JWT 不變，API key 使用同一個標頭：

```http
Authorization: Bearer ovk_<key_id>.<secret>
```

以音檔上傳為例，先在自己的程式環境安全設定 `OPENVMAN_API_KEY`：

```bash
curl --fail-with-body \
  'https://146.5gao.ai/openvman/api/v1/asr/transcribe' \
  -H "Authorization: Bearer $OPENVMAN_API_KEY" \
  -F 'file=@sample.wav' \
  -F 'project_id=<已授權的專案ID>'
```

`file` 必填，`project_id` 與逗號分隔的 `language_routes` 選填。辨識引擎沿用帳號選擇與授權；不能藉由 key 任意指定引擎。回應包含 `text`、實際 `provider`、`elapsed_seconds`、`language`、`language_check`、`language_routes` 與 `glossary`。所有上游失敗時，既有批次路徑可能仍回 HTTP 200、`provider` 為空、文字為「（音訊轉錄失敗）」；整合者須一併判斷，不能只看 HTTP 成功。

Chat、TTS 與其他應用 API 也帶相同標頭，請求／回應契約維持各端點定義。可由部署的 `/openapi.json` 與 `/docs` 查詢，Swagger 的 AccountBearer 可填 JWT 或完整 API key；管理 key 的端點使用 SessionBearer。

成功批次辨識另記音訊秒數：WAV 讀取 frames／sample rate，其他格式透過 ffprobe 讀 duration（最多等 5 秒）。無法取得長度或記帳失敗不改辨識結果；`elapsed_seconds` 仍只量轉寫，不包含此長度探測，因此非 WAV 的整體 HTTP 耗時可能較長。

## 串流 ASR

可信任的後端 WebSocket client 可連到 `wss://146.5gao.ai/openvman/api/v1/asr/stream?project_id=<已授權的專案ID>`，握手標頭帶同一個 `Authorization: Bearer ...`。帳號必須有串流引擎授權，並選擇可用的串流引擎。等待 `{"type":"ready"}` 後傳 16 kHz、單聲道、16-bit little-endian PCM binary frames；接收 `interim` 暫定文字與 `final` 定稿文字。結束音訊送 `{"type":"end"}`，等待尾句後關閉。連線錯誤可能回 `error` 事件或在握手時拒絕。

API key 不接受 query 參數；不要把 key 放進網址。瀏覽器原生 WebSocket 無法自行設定 Authorization 標頭，這種串流 key 接法供後端 client 使用。既有瀏覽器串流仍使用同來源登入 Cookie；本功能沒有自動開啟跨網域 CORS，也沒有把 root／admin key 加入 Avatar SDK。

## 失效與用量

- 到期或撤銷 key 後，後續驗證拒絕；已在執行的請求或已連上的 WebSocket 不會因此自動中斷。
- 停用帳號、撤銷帳號憑證（token version）或變更角色後，原 key 失效，需重新建立。資源授權變更則在後續請求按新權限判斷。
- `request_count` 記錄通過 key 驗證的 HTTP 請求及 WebSocket 握手，包含稍後被資源權限拒絕的請求；不代表成功辨識次數。WebSocket 每個音訊 frame 不另算一個請求。
- 推論帳本保留擁有者 `user_id`，以 `principal_type=api_key`、`principal_id=key_id` 區分每把 key；用量頁可篩選 API 金鑰。請求次數與模型 token／字元／音訊秒數是不同指標。
- 無效、到期或撤銷的 key 回 401；角色／資源不足或用 API key 管理 key 回 403。欄位驗證、音檔大小與服務失敗仍遵循各端點的狀態碼。

帳號 API key 不取代 `GATEWAY_INTERNAL_TOKEN`、embedding service token、供應商 key 或 Embed key。它授權的是 Backend 應用 API，不能直接當成內部服務的通用憑證。
