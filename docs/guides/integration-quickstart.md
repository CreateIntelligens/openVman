# 帳號能力探索與語音串接

可信任的後端程式以帳號 API key 呼叫 Backend。先在執行環境安全設定 `OPENVMAN_API_KEY`；勿把 key 寫入程式、命令參數、網址、版本庫或對外前端。建立與撤銷方式見 [帳號 API key](account-api-keys.md)。所有請求以 `Authorization: Bearer ...` 驗證，權限即時沿用所屬帳號。

## 先取得目前可用能力

`GET /api/v1/me/capabilities` 接受帳號 session 或 API key，未登入回 401，Embed key 回 403。回應頂層契約如下；此範例清單為空，實際內容依帳號當下授權與部署設定取得：

```json
{
  "schema_version": 1,
  "account": {"id": "<account-id>", "username": "<username>", "role": "user"},
  "defaults": {
    "project_id": "<opaque-project-id>",
    "character_id": "<character-id>",
    "voice_provider": "<provider-id>",
    "voice_id": "<voice-id>",
    "mascot_id": "<mascot-id>",
    "background_id": "<background-id>"
  },
  "projects": [],
  "characters": [],
  "mascots": [],
  "backgrounds": [],
  "tts": {"providers": []},
  "asr": {
    "value": "",
    "effective": "<effective-provider-id>",
    "allowed": [],
    "batch": [],
    "stream": [],
    "browser": []
  }
}
```

`asr.value` 為已保存選擇，`effective` 為目前生效引擎，`allowed` 是已授權引擎 ID 陣列。`batch`、`stream` 的項目為 `{"id":"引擎ID","configured":true或false}`；`browser` 項目為 `{"id":"browser","configured":null}`。`configured` 只表示必要部署設定齊全，**不是即時健康或成功保證**；browser 能否使用由 client 的瀏覽器決定。備援仍會在執行時套用授權與服務可用性檢查。

資源清單沿用對應端點的項目格式：專案以 `project_id` 識別，角色以 `char_id` 識別，聲音從 `tts.providers` 取供應商及其聲音。預設值可能空缺或因撤權不在目前清單，應先確認可用清單再呼叫。專案 `label` 只是顯示名稱，`project_id` 是 opaque ID，必須原樣傳遞，不能自行從名稱轉換。

### 帶專案查詢

專案可以在後台「專案與權限 → 專案 → 語音設定」限制能用的 ASR 引擎與聲音；實際能用的是帳號授權與專案限制的交集。呼叫 `GET /api/v1/me/capabilities?project_id=<project_id>` 時，`asr` 與 `tts.providers` 會改成這個專案能用的範圍，`asr.effective` 是這個專案會先用的引擎，並多一個 `project_policy`：

```json
{
  "project_policy": {
    "project_id": "<opaque-project-id>",
    "allowed_asr_engines": [],
    "default_asr_engine": null,
    "taiwanese_asr_engine": null,
    "allowed_tts_voices": [],
    "default_tts_voice": null,
    "effective_tts_voice": "<voice-id>"
  }
}
```

空陣列代表專案不限制。不帶 `project_id` 時沒有 `project_policy`，其他欄位與上例相同；專案讀不到回 404。之後的 ASR、TTS 請求記得帶同一個 `project_id`，限制才會套用：超出專案範圍的 ASR `provider` 回 403、聲音回 403。

需要個別重新整理時可呼叫：

| 資源 | 帳號授權清單 |
|---|---|
| 專案 | `GET /api/v1/projects` |
| 角色 | `GET /api/v1/avatar` |
| 吉祥物／小助理 | `GET /api/v1/avatar/mascots` |
| 背景 | `GET /api/v1/backgrounds` |
| TTS 供應商及聲音 | `GET /api/v1/tts/providers`（選填 `project_id`） |

`GET /api/v1/characters` 是公開 SDK 清單；取得角色授權以 `/avatar` 或 capabilities 為準。

## 一輪 ASR → Chat → TTS

| 步驟 | 請求位置與內容 | 回應 |
|---|---|---|
| 能力探索 | `GET /api/v1/me/capabilities` | 上述 JSON |
| 批次辨識 | `POST /api/v1/asr/transcribe`；multipart `file`，選填 `project_id`、`provider`、`language_routes` | JSON `text`、實際 `provider`、`language` 等 |
| 對話 | `POST /api/v1/chat`；JSON `message`、`project_id`、`session_id`，選填 `preferred_language`、`metadata.speech_language` | JSON `reply`、`citations`、`answer_source`、`knowledge_searched`、`no_answer` 等；通常會建立對話紀錄。要邊生成邊念改用 `POST /api/v1/chat/stream`（見「逐句串流」） |
| 念回答 | `POST /api/v1/tts/stream`；JSON `text`，選填 `project_id`、`provider`、`voice`、`speech_language`、`format` | 音訊 bytes，以實際 `Content-Type` 判斷格式；`format=pcm16k` 時固定為 16 kHz raw PCM |

選填 batch ASR `provider` 必須在已授權且已設定的 `asr.batch`。非批次引擎回 422、未授權回 403、未設定回 503；指定引擎失敗回 502，不備援、不讓台語分流改用其他辨識引擎。省略或空白時沿用帳號偏好、部署預設與既有備援，備援限授權候選及原部署預設相容例外。舊流程失敗可能仍回 HTTP 200，必須檢查非空 `provider`、有效 `text`，避免把「（音訊轉錄失敗）」當成問題送入 Chat。

一般帳號可選擇跨供應商的已授權聲音；TTS `provider` 與 `voice` 必須符合聲音資源 metadata。省略 provider 但提供 voice 時由 metadata 推導，舊 metadata 缺漏僅沿用管理員設定的預設 provider；省略 voice 時使用帳號預設，供應商不匹配仍拒絕。受限 admin 的 `/tts/providers` 與 capabilities 也僅列權限上限內的聲音。聲音 ID 的音質與可用性取決於部署及上游，不應把特定 ID 永久當成失效。Embed key 維持綁定聲音限制。

2026-10-13 [正式環境實測](../plans/integration-capabilities-asr.md)已跑通 5 個批次及 3 個串流 ASR、兩專案知識庫對話，以及 IndexTTS／CosyVoice／Gemini／有效 VoxCPM 聲音。當時仍有過期聲音被列出、Edge 回 200 卻無音訊，以及 IP 入口憑證不匹配等問題；不能僅因 HTTP 200 或聲音在清單上便視為成功，仍需檢查非空音訊及可解碼性。此為當日狀態，排障時需重新驗證。

### 對話的語言提示與回答來源

`preferred_language` 是使用者在你的介面選的語言（`zh` 華語、`nan` 台語、`en`、`es`、`ja`、`ko`；其他值回 422）。它是參考，不會鎖定回答語言：使用者這句話看得出是哪種語言（英文句、中文句），或明講「請用英文回答」時，照使用者；只有「ok」、型號這類看不出語言的輸入，才用選的語言回答（原本是用專案主要語言）。選 `nan` 時，中文字的句子會優先查台語文件、回答用繁體中文，跟 ASR 聽出台語（`metadata.speech_language: "nan"`）一樣。Brain 不記住這個值，整段對話每次請求都要帶。

回應的回答來源欄位只看這一輪的知識庫查詢（`search_knowledge`）：

| 欄位 | 說明 |
|---|---|
| `answer_source` | `qa`：引用到 QA 文件（QA CSV 匯入或 QA 筆記）；`knowledge`：引用到知識庫其他文件、沒有 QA；`none`：沒有知識庫引用 |
| `knowledge_searched` | 這一輪有沒有查知識庫 |
| `no_answer` | 查了知識庫但沒有任何引用（`knowledge_searched` 且 `answer_source` 為 `none`） |

要在知識庫沒有答案時改顯示固定拒答句，以 `no_answer: true` 判斷。沒查知識庫（例如打招呼、閒聊）時 `no_answer` 是 false、`answer_source` 是 `none`。網路搜尋與記憶的引用不算知識庫命中：專案開了網路搜尋時，只靠網路回答的一輪也是 `no_answer: true`。帶 `turn_id` 的可合併回合在 `POST /api/v1/chat/accept` 回應中有相同的值。

`no_answer` 有兩種情況會是 true：完全沒檢索到任何段落；或檢索到了段落，但回覆本身在說資料裡沒有答案。知識庫檢索為了接住錯字與跨語言問法，門檻刻意放寬，沾到邊的段落也會被帶回來，例如在醫院專案問「火星上有幾座醫院？」會檢索到院內服務的 QA。所以有引用時，後端會再請決策模型看一次回覆，判斷它是不是在說查不到（每輪約多 0.1–0.2 秒；判斷逾時或失敗時只看有沒有引用）。2026-10-14 實測 10 句真實回覆（中英文、答出來與查不到各半）全對。這時 `answer_source` 仍照實標出檢索到的是 QA 或一般文件。

### 打斷對話

使用者打斷數位人時，直接中斷 `POST /api/v1/chat` 的 HTTP 請求（瀏覽器 `AbortController.abort()`、HTTP 用戶端關閉連線）即可。Backend 發現連線斷了就關掉往 Brain 的請求，Brain 不再開始下一次 LLM 呼叫或下一輪工具，也不寫入這一輪。已送給模型的那一次請求收不回來，所以中斷後仍可能有幾秒的模型用量。你不會收到回應；Backend 的 log 會記成 499。

不帶 `turn_id` 時，中斷與寫入可能同時發生：Brain 已經寫完對話、回應還在路上時才中斷，這一輪仍會留在對話紀錄裡。要讓被打斷的回合確定不進紀錄，請每輪帶 `turn_id` 與 `turn_revision`，只在真的播出回答後呼叫 `POST /api/v1/chat/accept`；沒有 accept 的回合不會寫入對話、日誌或記憶。

ASR 的 `provider` 是 form 欄位，TTS 的 `provider` 是 JSON 欄位，串流 ASR 的 `engine` 是 WebSocket query；這些選擇只影響本次請求或連線，不需要先 `PUT /settings/my-asr-provider` 或 `PUT /settings/my-preferences`。`PUT /settings/my-asr-provider` 改的是帳號偏好，共用同一把 key 的所有機台會一起變，機台各自要不同引擎時請每次帶 `provider`／`engine`。

重開一段對話不需要刪除：換一個新的 `session_id` 即可。刪除對話（`DELETE /api/v1/sessions/{id}`、`POST /api/v1/sessions/batch-delete`）需要專案編輯權，只有讀取授權的帳號會收到 403。

### 邊生成邊念：逐句串流（SSE）

`POST /api/v1/chat` 要等整段回答寫完才回應。想讓數位人早一點開口，改用 `POST /api/v1/chat/stream`：請求 body、驗證方式與 `/chat` 完全相同（含 `preferred_language`、`metadata`、`turn_id`／`turn_revision`），回應是 `text/event-stream`，每個事件是 `event: <名稱>\ndata: <JSON>\n\n`：

| 事件 | `data` | 說明 |
|---|---|---|
| `sentence` | `{"index": 0, "text": "營業時間是早上九點。"}` | 最終回答每完成一句就送一次，`index` 從 0 起算。查知識庫等工具輪的文字不會送出 |
| `done` | 與 `/chat` 回應相同的 JSON（`reply`、`citations`、`answer_source`、`knowledge_searched`、`no_answer`、`session_id`、`trace_id`、`history`、`pii_pending`、`image_id`／`url` 等） | 最後一個事件，之後串流結束 |
| `error` | `{"status": 502, "detail": ...}` | `status` 與 `detail` 就是 `/chat` 遇到同一個錯誤時的 HTTP 狀態碼與錯誤 `detail`（可能是字串，也可能是含 `error_code`、`retry_after_ms` 的物件）。之後串流結束，不會再有 `done` |

句尾的判斷：中日文 `。！？；…`；英文 `. ! ?` 後面接空白或文字結束；換行。`3.5`、`HIPPO-50.html` 這類小數、型號與網址不會被切開，最後一段沒有句尾符號的文字在結束前補送。句子保留原文的空白與換行（換行後的那句以換行開頭），所有 `sentence.text` 依序接起來就等於 `done.reply`；送 TTS 前可以自己 trim。

建議做法：收到第一個 `sentence` 就送 `POST /api/v1/tts/stream`，之後每句排進佇列依序合成、依序播放；附圖、引用與 `no_answer` 等 `done` 再處理。`no_answer` 是 true 時要改念固定拒答句的話，請先等 `done` 再念，或接受已經念出前幾句。

其他行為與 `/chat` 相同：會寫入對話紀錄、計入用量；帶 `turn_id` 時一樣暫存、要 `POST /api/v1/chat/accept`。中途中斷（`AbortController.abort()`、關閉連線）時 Brain 停止生成、不寫入這一輪，跟「打斷對話」一樣。串流開始前就能判斷的錯誤（401、403、404、422、429）照一般 HTTP 狀態碼回應，不會開始串流；之後的錯誤才以 `error` 事件回報。

極少數情況下模型在同一回合先寫了文字又改叫工具，或 LLM 供應商串流到一半斷線、換下一家重寫：已送出的那幾句收不回來，也不在 `done.reply` 裡，最終回答之後仍會完整逐句送出。要顯示的文字以 `done.reply` 為準。

瀏覽器（`fetch` + `ReadableStream`）：

```js
const controller = new AbortController();
const res = await fetch("/api/v1/chat/stream", {
  method: "POST",
  headers: { "Content-Type": "application/json", Authorization: `Bearer ${apiKey}` },
  body: JSON.stringify({ message, project_id: projectId, session_id: sessionId }),
  signal: controller.signal, // 使用者打斷時 controller.abort()
});
if (!res.ok) throw new Error(`HTTP ${res.status}`);

const reader = res.body.pipeThrough(new TextDecoderStream()).getReader();
let buffer = "";
for (;;) {
  const { value, done } = await reader.read();
  if (done) break;
  buffer += value;
  let cut;
  while ((cut = buffer.indexOf("\n\n")) >= 0) {
    const block = buffer.slice(0, cut);
    buffer = buffer.slice(cut + 2);
    const event = block.match(/^event: (.*)$/m)?.[1];
    const data = JSON.parse(block.match(/^data: (.*)$/m)?.[1] ?? "null");
    if (event === "sentence") speak(data.text.trim()); // 排進 TTS 佇列
    else if (event === "done") showAnswer(data);
    else if (event === "error") showError(data.status, data.detail);
  }
}
```

Python（httpx）：

```python
import json

import httpx

with httpx.stream(
    "POST",
    f"{base_url}/api/v1/chat/stream",
    headers={"Authorization": f"Bearer {api_key}"},
    json={"message": "營業時間？", "project_id": project_id, "session_id": session_id},
    timeout=httpx.Timeout(10, read=120),
) as response:
    response.raise_for_status()
    event = None
    for line in response.iter_lines():
        if line.startswith("event: "):
            event = line[len("event: "):]
        elif line.startswith("data: "):
            data = json.loads(line[len("data: "):])
            if event == "sentence":
                speak(data["text"].strip())  # 排進 TTS 佇列
            elif event == "done":
                print(data["reply"], data["no_answer"])
            elif event == "error":
                raise RuntimeError(f"{data['status']}: {data['detail']}")
```

## 錯誤與限流

| 狀態碼 | 意思 |
|---|---|
| 401 | key 錯誤、過期、撤銷，或帳號停用 |
| 403 | 帳號沒有這個資源或動作的權限（例如看得到專案但不能改、聲音不在授權或專案限制內） |
| 404 | 專案、角色等資源不存在，或這個帳號看不到 |
| 422 | 參數格式不對，例如不支援的引擎名稱 |
| 429 | 超過每把 key 每分鐘的上限（部署設定 `API_KEY_RATE_LIMIT_PER_MINUTE`，預設 300），依 `Retry-After` 秒數後重試 |
| 502／503 | 指定的上游引擎失敗或未設定 |

錯誤 body 為 `{"detail": ...}`。多台機台共用一把 key 時共用同一個上限。

## 瀏覽器前端直接呼叫（CORS）

部署的 `CORS_ALLOWED_ORIGINS` 列出的網站，可以在瀏覽器裡用 `fetch` 帶 `Authorization: Bearer <key>` 直接呼叫；沒列出的網站會被瀏覽器擋下（預檢請求拿不到 `Access-Control-Allow-Origin`）。不支援 Cookie 跨網域。要使用請提供前端的完整來源（例如 `https://kiosk.example.com`）給部署方。每個外部網站的呼叫會依來源與 key 記錄。

key 放在瀏覽器裡任何人都能從開發者工具取得，等同公開：請用專用帳號、只授權需要的專案與聲音，並在外洩時立刻撤銷重發。較安全的做法是由自家後端代理轉發，key 只留在伺服器。瀏覽器原生 WebSocket 不能自訂 Authorization 標頭，所以串流 ASR 仍需由後端代理連線，或改用批次辨識／瀏覽器內建辨識。

## 可直接執行的標準庫範例

Python 3.10+，不需要額外套件。腳本只從環境讀取 key，不保存 key、不更新帳號偏好。公開入口包含部署前綴；此處範例使用 `/openvman`，本機部署則依實際網址設定。

```bash
python scripts/integration_client.py --help

# 只探索，不辨識、不呼叫 LLM、不建立對話或合成音訊
python scripts/integration_client.py \
  --base-url https://api.example.com/openvman --discover-only

# 依剛取得的清單填入 ID；請求會建立一輪對話並使用推論服務
python scripts/integration_client.py \
  --base-url https://api.example.com/openvman \
  --project-id '<capabilities.projects 中的 project_id>' \
  --audio sample.wav \
  --asr-provider '<capabilities.asr.batch 中的 id>' \
  --tts-provider '<已授權的 TTS provider>' \
  --voice '<該 provider 的已授權 voice_id>' \
  --output reply
```

省略 `--project-id` 時使用能力回應中的預設專案，但該專案仍須在可用清單；省略兩個 provider 參數及 voice 則由後端依帳號預設與授權處理。腳本不重試 Chat，避免同一輪因網路重試重複落庫，並輸出新建的 `session_id` 供追蹤。

TLS 預設驗證憑證與主機名；內部 CA 用 `--ca-file /path/to/internal-ca.pem`，不提供跳過驗證選項。HTTP 重新導向會被拒絕，請直接設定正確入口，避免將 Bearer token 轉送到其他位置。腳本收到錯誤只顯示狀態碼，不印可能含敏感資訊的上游錯誤 body。

範例會依 MIME 將 `--output` 副檔名改成 `.wav`、`.mp3` 或 `.pcm`；檔案已存在時拒絕覆蓋，其他 MIME 與空音訊也拒絕保存。`/tts/stream` 名稱不保證內容一定分塊或一定是 PCM：VoxCPM 可為 WAV，Edge 為 MP3，Gemini 串流目前為 `audio/l16;rate=24000;channels=1` 的 **16-bit little-endian、單聲道 raw PCM**（本部署的位元序由 adapter 契約決定，不可只依 MIME 名稱猜測）。raw PCM 沒有檔頭，必須按實際 rate、channels、位元深度與位元序解碼或封裝成 WAV；不能直接將任意音訊 bytes 當成 AudioContext 可解碼檔案。

### 固定輸出 16 kHz PCM（MatesX 建議）

接 MatesX 等對嘴引擎時，請在 `/tts/stream` 的 JSON 加上 `"format": "pcm16k"`。不論實際走哪個引擎（含台語分流、引擎失敗後的備援、整段合成的 MP3），回應一律是**串流**的 16 kHz、單聲道、16-bit little-endian raw PCM，`Content-Type: audio/l16;rate=16000;channels=1`，每個 chunk 都是完整樣本（偶數 byte），可直接依序送進 MatesX，不必再自己判斷 WAV／MP3／24 kHz PCM。

| `format` | 行為 |
|---|---|
| 省略或 `""` | 照引擎原樣回傳（本服務前台使用，行為不變） |
| `"pcm16k"` | 轉成 16 kHz mono s16le raw PCM 串流 |
| 其他值 | 422 |

轉換在 Backend 端進行：24 kHz raw PCM 與 WAV 在程序內重採樣（濾波器狀態跨 chunk 保留，邊界不會爆音），MP3 交由 ffmpeg 邊收邊解碼。首包額外延遲約為：Gemini 5–9 ms、VoxCPM WAV 約 4 ms、16 kHz WAV 幾乎為 0、MP3 引擎（Edge、CosyVoice）80–100 ms。整段合成的引擎本來就要等全文合成完才有第一包，轉換不會讓它變成真正的邊合成邊播。標準庫範例可用 `--tts-format pcm16k` 試跑，輸出存成 `.pcm`。

## 串流辨識

Python 標準庫範例只實作批次辨識。需要即時字幕時，以可信任後端 WebSocket client 連線：

```text
wss://<host>/<部署前綴>/api/v1/asr/stream?project_id=<opaque-id>&engine=<已授權stream引擎>
Authorization: Bearer <環境中的帳號API key>
```

一般帳號可指定 `asr.stream` 中的已授權引擎；省略 `engine` 沿用帳號偏好，未授權回 `not_allowed`，Embed key 不能使用。等 `ready` 後傳 16 kHz、單聲道、16-bit little-endian PCM binary frames，接收 `interim`／`final`，結束送 `{"type":"end"}` 後等待尾句；不把整個 WAV 檔頭當 PCM frame 傳送。瀏覽器原生 WebSocket 不能自行加 Authorization 標頭，帳號 API key 接法供可信任後端 client 使用，不把 key 放在 query，也不替部署自動開啟 CORS。
