# 串接方交付說明（模板）

給拿到 openVman 帳號的串接方。複製這份文件，把 `<...>` 換成實際值；帳號密碼與 API key 另外用安全管道傳，不要寫進文件或聊天記錄。完整規格見[能力探索與語音串接快速開始](integration-quickstart.md)與[帳號 API key](account-api-keys.md)，這裡只放串接方第一天需要的部分。

## 帳號與登入

| 項目 | 值 |
|---|---|
| 帳號 | `<username>` |
| 角色 | `<admin 或 user>`。管理員能進後台、看得到全部專案與資源；一般帳號只看得到授權的專案與資源，預設不能進後台 |
| 密碼 | 另外傳；登入後在後台右上角帳號選單自行更改 |
| 管理後台 | `https://api.example.com/openvman/admin/` |
| 虛擬人前台 | `https://api.example.com/openvman/` |
| API 根網址 | `https://api.example.com/api/v1/` |
| OpenAPI | `https://api.example.com/docs`，Swagger 的 AccountBearer 填 API key 即可直接試 |

## API key

另外傳，或由串接方登入後台「專案與權限 → API 金鑰」自己建立：填用途名稱與期限（介面預設 90 天，可不設期限），完整 key 只顯示一次。每個串接對象各開一把，才能分開停用與查用量。

所有請求都帶同一個標頭：

```http
Authorization: Bearer ovk_<key_id>.<secret>
```

key 沿用帳號當下的權限；帳號停用或改角色時 key 失效，重設密碼不影響 key。不要把 key 放進網址、程式碼、版本庫或瀏覽器前端；給網頁用的是 Embed key（後台「Embed 金鑰」）。

## 可用專案

專案範圍的 API 都要帶 `project_id`，用 ID 不用名稱；能用哪些由帳號授權決定（管理員看得到全部），專案自己設的限制一律適用。交付時把這個帳號能用的專案填進來：

| 專案 | project_id | 語言分流 |
|---|---|---|
| `<醫院示範專案>` | `<project-id>` | 華語、英文、台語 |
| `<工業示範專案>` | `<project-id>` | 華語、英文 |

登入後的預設（專案、人物、聲音、背景）由管理者在後台「專案與權限 → 帳號 → 資源權限」設定，呼叫端用 capabilities 讀取即可。

## 先查能力

不要把人物、聲音、引擎的 ID 寫死，先問伺服器這把 key 現在能用什麼：

| 端點 | 回什麼 |
|---|---|
| `GET /api/v1/me/capabilities` | 帳號、預設值、可用專案、人物、背景、TTS 供應商與聲音、ASR 引擎（`batch` 批次、`stream` 串流；`configured` 只代表部署有設） |
| `GET /api/v1/me/capabilities?project_id=<id>` | 同上，但改成這個專案能用的範圍，多一個 `project_policy`。人物、背景多半是專案專屬，不帶專案時可能是空的 |
| `GET /api/v1/projects/{project_id}/resources` | 專案解析後的全部可用資源與有效預設，每項標來源，推薦用這個 |
| `GET /api/v1/projects` | 專案清單 |
| `GET /api/v1/tts/providers?project_id=<id>` | 這個專案能用的 TTS 供應商與聲音 |

```bash
curl -s https://api.example.com/api/v1/me/capabilities \
  -H "Authorization: Bearer $OPENVMAN_API_KEY"
```

## 一輪對話：辨識、回答、念出

三個端點依序呼叫就是前台數位人的一輪：上傳錄音拿逐字稿 → 送對話拿回答 → 把回答送去合成。

1. 批次辨識 `POST /api/v1/asr/transcribe`（multipart：`file` 必填，`project_id`、`provider`、`language_routes` 選填）：

```bash
curl -s https://api.example.com/api/v1/asr/transcribe \
  -H "Authorization: Bearer $OPENVMAN_API_KEY" \
  -F file=@sample.wav -F project_id=<project-id>
# 回 {"text": "...", "provider": "breeze", "language": "nan" 或 null, "elapsed_seconds": 0.8, ...}
```

沒指定 `provider` 就照帳號偏好、專案預設與部署預設。回應要檢查 `provider` 非空、`text` 不是「（音訊轉錄失敗）」，舊路徑失敗時仍可能回 200。

2. 對話 `POST /api/v1/chat/stream`（SSE，逐句送回；要整段一次回改用 `/api/v1/chat`，body 相同）：

```bash
curl -sN https://api.example.com/api/v1/chat/stream \
  -H "Authorization: Bearer $OPENVMAN_API_KEY" -H "Content-Type: application/json" \
  -d '{"message": "骨科上午門診時間？", "project_id": "<project-id>", "session_id": "kiosk-01-20260101", "metadata": {"speech_language": "nan"}}'
# event: sentence  data: {"index": 0, "text": "...", "tts_text": "..."}
# event: done      data: {"reply": "...", "tts_text": "...", "citations": [...], "answer_source": "qa", "no_answer": false, "session_id": "..."}
# event: error     data: {"status": 429, "detail": {...}}
```

`sentence` 一到就可以送去合成，不必等 `done`；顯示的文字以 `done.reply` 為準。`no_answer: true` 代表知識庫沒答案，要改念固定拒答句由呼叫端自己做。`metadata.speech_language` 照抄第 1 步回的 `language`（台語時是 `nan`）。

3. 念出 `POST /api/v1/tts/stream`（JSON：`text` 必填，`project_id`、`speech_language`、`language`、`provider`、`voice`、`format` 選填）：

```bash
curl -s https://api.example.com/api/v1/tts/stream \
  -H "Authorization: Bearer $OPENVMAN_API_KEY" -H "Content-Type: application/json" \
  -d '{"text": "骨科上午門診時間為九點到十二點。", "project_id": "<project-id>", "speech_language": "nan"}' \
  -D - -o reply.audio
# 標頭 X-TTS-Provider 標實際引擎；Content-Type 決定格式（mp3、wav 或 raw PCM）
```

送 `tts_text` 比送 `reply` 好（已去 markdown、電話轉讀法）。要固定格式給對嘴引擎，加 `"format": "pcm16k"`，不論哪個引擎都回 16 kHz 單聲道 16-bit raw PCM。

## 語言與台語

伺服器依語言選引擎，呼叫端只要把語言帶對。

| 情形 | 要帶什麼 | 結果 |
|---|---|---|
| 使用者講台語 | 專案分流含台語，辨識帶 `project_id`；對話帶 `metadata.speech_language: "nan"`；合成帶 `speech_language: "nan"` | 辨識走 Breeze 轉華語文字並判斷是否台語；對話優先查台語文件、回繁體中文；合成走 CosyVoice 念台語，指定別家引擎也會被換 |
| 使用者打字選台語 | 對話帶 `preferred_language: "nan"`；合成帶 `language: "nan"` | 同上 |
| 華語、英文 | 不帶或帶 `zh`、`en` | 合成走 IndexTTS（沒指定 provider 與 voice 時） |
| 其他語言 | `preferred_language`：`es`、`ja`、`ko` | 用指定或預設聲音 |

回應標頭 `X-TTS-Provider` 是最後真正念的引擎。台語引擎有備援鏈 CosyVoice → VoxCPM → IndexTTS → Edge，發生備援時另帶 `X-TTS-Fallback: true` 與 `X-TTS-Fallback-Reason`。台語合成是整段合成，第一聲約 1.8 到 3 秒，比華語的逐句串流慢。

## 錯誤碼與限流

錯誤 body 都是 `{"detail": ...}`。

| 狀態碼 | 意思 | 怎麼處理 |
|---|---|---|
| 400 | 對話請求被拒：空訊息、超長、內容檢查擋下（`error_code: INVALID_REQUEST`） | 改內容再送，不要重試 |
| 401 | key 錯誤、過期、撤銷，或帳號停用 | 換 key |
| 403 | 沒有這個資源或動作的權限（聲音不在專案限制內、只有讀取權卻要刪） | 查 capabilities 或請管理者改授權 |
| 404 | 專案、人物、聲音不存在，或這個帳號看不到 | 確認 ID（用 ID 不用名稱） |
| 422 | 參數格式不對，或專案範圍 API 沒帶 `project_id` | 改參數 |
| 429 | 超過每把 key 每分鐘上限（部署設定 `API_KEY_RATE_LIMIT_PER_MINUTE`，預設 300），或同一專案每分鐘超過 90 次對話（`LLM_OVERLOAD`） | 照 `Retry-After` 秒數後重試 |
| 502 / 503 | 指定的上游引擎失敗或未設定 | 不指定引擎讓伺服器備援，或稍後重試 |

限流以 60 秒滑動視窗計算，多台機器共用一把 key 就共用一個上限。

## 注意事項

- key 只放伺服器端環境變數，不進網址、不進瀏覽器。外洩就到後台撤銷重發。
- `session_id` 自己定，建議加前綴（例如 `kiosk-<機台>-<日期>`），後台對話紀錄才分得出來源。一個 session 最多 100 輪、閒置 30 天失效；重開對話換新的 `session_id` 即可。
- 打斷：直接中斷 HTTP 連線，伺服器會停止生成。要確定被打斷的回合不進紀錄，每輪帶 `turn_id` 與 `turn_revision`，真的播出回答後再呼叫 `POST /api/v1/chat/accept`。
- 用 key 呼叫的對話會出現在後台該專案的對話紀錄與用量頁；測試請用測試專案，不要沙在正式專案裡。
- `provider`、`voice`、`engine` 只影響這一次請求；`PUT /api/v1/settings/my-asr-provider` 改的是帳號偏好，共用同一把 key 的所有機台會一起變，不要在程式裡呼叫。
- 串流辨識 `wss://api.example.com/api/v1/asr/stream?project_id=<id>&engine=gemini-live` 要在握手標頭帶 Authorization，只適合後端 client；專案開著台語時前台用的是批次辨識，不是串流。

## 參考文件

| 文件 | 內容 |
|---|---|
| [能力探索與語音串接快速開始](integration-quickstart.md) | 能力探索、一輪 ASR→Chat→TTS、逐句串流、打斷、台語、錯誤碼、可執行的 Python 範例 |
| [帳號 API key 與 ASR 整合](account-api-keys.md) | API key 的建立、撤銷、代發規則、失效時機 |
| [Avatar JavaScript SDK](avatar-embed/README.md) | 把數位人嵌進外部網頁（Embed key 與 SDK） |
| `scripts/integration_client.py` | 用 `OPENVMAN_API_KEY` 跑完一輪的範例程式 |
| 部署的 `/docs` | OpenAPI，每個端點的欄位與狀態碼 |
