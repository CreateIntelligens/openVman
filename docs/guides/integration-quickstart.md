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

需要個別重新整理時可呼叫：

| 資源 | 帳號授權清單 |
|---|---|
| 專案 | `GET /api/v1/projects` |
| 角色 | `GET /api/v1/avatar` |
| 吉祥物／小助理 | `GET /api/v1/avatar/mascots` |
| 背景 | `GET /api/v1/backgrounds` |
| TTS 供應商及聲音 | `GET /api/v1/tts/providers` |

`GET /api/v1/characters` 是公開 SDK 清單；取得角色授權以 `/avatar` 或 capabilities 為準。

## 一輪 ASR → Chat → TTS

| 步驟 | 請求位置與內容 | 回應 |
|---|---|---|
| 能力探索 | `GET /api/v1/me/capabilities` | 上述 JSON |
| 批次辨識 | `POST /api/v1/asr/transcribe`；multipart `file`，選填 `project_id`、`provider`、`language_routes` | JSON `text`、實際 `provider`、`language` 等 |
| 對話 | `POST /api/v1/chat`；JSON `message`、`project_id`、`session_id`，選填 `metadata.speech_language` | JSON `reply` 等；通常會建立對話紀錄 |
| 念回答 | `POST /api/v1/tts/stream`；JSON `text`，選填 `project_id`、`provider`、`voice`、`speech_language` | 音訊 bytes，以實際 `Content-Type` 判斷格式 |

選填 batch ASR `provider` 必須在已授權且已設定的 `asr.batch`。非批次引擎回 422、未授權回 403、未設定回 503；指定引擎失敗回 502，不備援、不讓台語分流改用其他辨識引擎。省略或空白時沿用帳號偏好、部署預設與既有備援，備援限授權候選及原部署預設相容例外。舊流程失敗可能仍回 HTTP 200，必須檢查非空 `provider`、有效 `text`，避免把「（音訊轉錄失敗）」當成問題送入 Chat。

一般帳號可選擇跨供應商的已授權聲音；TTS `provider` 與 `voice` 必須符合聲音資源 metadata。省略 provider 但提供 voice 時由 metadata 推導，舊 metadata 缺漏僅沿用管理員設定的預設 provider；省略 voice 時使用帳號預設，供應商不匹配仍拒絕。受限 admin 的 `/tts/providers` 與 capabilities 也僅列權限上限內的聲音。聲音 ID 的音質與可用性取決於部署及上游，不應把特定 ID 永久當成失效。Embed key 維持綁定聲音限制。

2026-10-13 [正式環境實測](../plans/integration-capabilities-asr.md)已跑通 5 個批次及 3 個串流 ASR、兩專案知識庫對話，以及 IndexTTS／CosyVoice／Gemini／有效 VoxCPM 聲音。當時仍有過期聲音被列出、Edge 回 200 卻無音訊，以及 IP 入口憑證不匹配等問題；不能僅因 HTTP 200 或聲音在清單上便視為成功，仍需檢查非空音訊及可解碼性。此為當日狀態，排障時需重新驗證。

ASR 的 `provider` 是 form 欄位，TTS 的 `provider` 是 JSON 欄位，串流 ASR 的 `engine` 是 WebSocket query；這些選擇只影響本次請求或連線，不需要先 `PUT /settings/my-asr-provider` 或 `PUT /settings/my-preferences`。

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

## 串流辨識

Python 標準庫範例只實作批次辨識。需要即時字幕時，以可信任後端 WebSocket client 連線：

```text
wss://<host>/<部署前綴>/api/v1/asr/stream?project_id=<opaque-id>&engine=<已授權stream引擎>
Authorization: Bearer <環境中的帳號API key>
```

一般帳號可指定 `asr.stream` 中的已授權引擎；省略 `engine` 沿用帳號偏好，未授權回 `not_allowed`，Embed key 不能使用。等 `ready` 後傳 16 kHz、單聲道、16-bit little-endian PCM binary frames，接收 `interim`／`final`，結束送 `{"type":"end"}` 後等待尾句；不把整個 WAV 檔頭當 PCM frame 傳送。瀏覽器原生 WebSocket 不能自行加 Authorization 標頭，帳號 API key 接法供可信任後端 client 使用，不把 key 放在 query，也不替部署自動開啟 CORS。
