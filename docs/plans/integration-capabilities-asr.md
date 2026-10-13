# 串接能力探索與單次 ASR 選擇

狀態：Draft（2026-10-13；待使用者驗收）

## 目標與契約

- 新增 `GET /api/v1/me/capabilities`，沿用帳號／API key 的授權邊界，彙整專案、角色、吉祥物、背景、可用聲音、ASR 與帳號預設值。公開 `/characters` 不作為帳號授權來源。
- ASR 清單區分已授權及部署已設定，以及 batch／stream／browser；configured 僅表示必要設定齊全，不宣稱上游健康。
- `POST /api/v1/asr/transcribe` 增加選填 form `provider`。有值時驗證為已授權、已設定的批次引擎，只影響此請求，不寫入帳號偏好；明確指定失敗回 502，不暗中換引擎。省略或空白沿用既有帳號偏好、部署預設與備援流程。
- `WS /api/v1/asr/stream?engine=...` 允許一般帳號指定已授權的串流引擎，保留管理員試聽與 embed 限制。
- 明確指定 ASR 時不讓台語分流覆蓋指定引擎；未指定維持既有台語 Breeze 分流。備援限定於帳號授權及部署預設的既有相容路徑。
- 普通帳號可選所有明確授權的 TTS 聲音，provider 以聲音資源 metadata 驗證；預設值僅用於省略參數。舊 metadata 缺漏僅沿用管理員設定的預設 provider；embed 仍限 key 綁定聲音。
- 保留 opaque `project_id`；文件清楚區分 label 與 ID、JSON/form/query 位置及實際音訊 Content-Type。

## 涉及介面

- Backend：能力探索、批次／串流 ASR、TTS 聲音清單及合成授權、OpenAPI。
- 文件：README、CHANGELOG、Backend spec、API key 串接指南與可執行串接範例。
- Brain 無新路由／資料格式；既有前台及後台可維持原呼叫方式，不需 UI 改版。前台選單沿用 TTS providers，會自動取得跨 provider 授權聲音。
- 不修改帳號授權、既有 key、專案 ID；不自動 commit、push 或重啟正式服務。

## 驗證

- 同帳號兩個同時上傳各自使用指定引擎，偏好不變；拒絕未授權／錯誤模式／未設定引擎，明確指定失敗不備援。
- 能力探索與個別清單一致、隔離其他帳號資源，覆蓋正式／臨時帳號、root/admin、API key、撤權與未登入。
- 跨 provider 聲音可列出及合成，仍拒絕未授權聲音及 provider 不匹配；保留 embed 邊界。
- 跑 focused 與 Backend 全套測試、contracts check、entry boundary；於容器內用隔離測試環境安裝本次程式並實際執行 HTTP/WS 驗證。

## 實作與驗證紀錄（2026-10-13）

- Backend 全套：1,299 passed、2 skipped；最後補齊的 OpenAPI 錯誤契約另含於 focused 135 passed。
- CLI、entry boundaries、Brain protocol contracts 合跑：47 passed；generated contracts check 通過。
- 容器內最新副本的集中回歸：168 passed（另有既有 Starlette/httpx 棄用提示）。
- 在既有 Backend 映像內安裝隔離程式副本，使用隔離資料庫驗證 HTTP／WebSocket：能力隔離、OpenAPI、同帳號雙 key 各自指定辨識引擎、跨 provider 聲音、串流選擇、撤銷立即生效。推論與 Brain 傳輸使用測試替身，未驗證所有真實上游的可用性。
- 額外修正受限 admin 聲音清單：個別 TTS providers 與能力探索均遵守權限上限。
- 既有前後台沿用相同清單與語音請求，無需 UI 改版；Brain 無程式變更。以上為推送前的隔離驗證，後續正式部署與實測結果如下；帳號授權及 key 未更動。

## 正式環境實測（2026-10-13 11:32 起，UTC+8）

以下保留真實上游測量結果；帳號、專案及部署位址已改為匿名示例，並非曾對示例網址執行測試。

結果：主要串接流程通過，但仍有 TTS 與 TLS 問題，不能宣稱所有列出的聲音皆可用。計畫維持 Draft。

### 環境與方法

- 正式入口 `https://api.example.com/openvman`，完整驗證 TLS；未走測試 app、替身上游或內部直連以取代對外 API。
- 使用既有正式 user 帳號的 API key，非 root/session 替代憑證。未建立、撤銷或更改 key，未修改帳號預設或授權；文件不記錄實際帳號名稱、帳號 ID 或金鑰識別碼。
- Backend 正式容器的 `routes/asr.py`、`routes/capabilities.py`、`gateway/asr_stream.py`、`auth/voice_access.py`、`routes/admin.py` SHA256 與當時 HEAD `62be2877` 相同，含 `eafc960` 的串接功能。
- 音檔由正式 IndexTTS/hayley 合成「忘記帶健保卡可以掛號嗎？」，轉成 16 kHz、單聲道 PCM WAV，長 3.115 秒。這是合成語音的功能探測，非真人麥克風、長音檔、壓力或準確率基準測試。
- 所有 ASR／Chat／TTS 均呼叫真實上游；以 ffmpeg 解碼及音量偵測確認成功音訊非空、非全靜音。未驗證瀏覽器喇叭、對嘴或 Kiosk 現場音效。
- 詳細 JSON／音訊暫存於正式 Backend 容器 `/tmp/openvman-production-wgt0rxnm/`，容器替換後可能消失，不包含憑證。

### 能力、權限與對話

- capabilities 回 200，列出兩個授權專案（工業示範專案（開發）／醫院示範專案）、14 個角色、5 家 TTS 的 78 個聲音、5 個 batch 與 3 個 stream ASR。
- 實際再呼叫 projects／avatar／mascots／backgrounds／tts providers 五支個別清單，全部回 200，內容與 capabilities 各區塊完全相同；CLI 結束後也再次確認帳號 ASR 偏好未變。
- 未登入 capabilities 回 401；OpenAPI 回 200，含 capabilities 及 ASR multipart `provider`；匿名 WebSocket 升級前回 403。
- 非批次 `provider=browser` 回 422；TTS provider／voice 不匹配、未知聲音及未授權專案均回 404，未送入推論。
- 醫院：ASR 文字送 Chat，4.90 秒回有效答案，含 3 筆知識庫引用，接續 IndexTTS 合成及解碼成功。
- 工業示範專案（開發）：「沉水泵浦有哪些用途？」6.44 秒回有效答案，含 2 筆知識庫引用。
- 原封不動執行 `scripts/integration_client.py`，以正式入口、Breeze、IndexTTS/hayley 跑完一輪並產出可解碼的 `cli-reply.wav`。
- 此次新增 3 筆測試對話，前綴為 `production-smoke-`（2 筆）及 `integration-`（1 筆），保留供追溯；沒有更動原有對話。

### 真實 ASR

時間為客戶端完整請求／串流測量，單次樣本，不作效能基準。

| 模式／引擎 | 結果 | 秒數 | 文字觀察 |
|---|---|---:|---|
| batch openai | 200，實際 provider=openai | 4.12 | 健保卡正確 |
| batch r2t2 | 200，實際 provider=r2t2 | 3.53 | 健保卡辨成「鑑寶卡」 |
| batch breeze | 200，實際 provider=breeze | 1.40 | 健保卡正確 |
| batch r2t2-dev | 200，實際 provider=r2t2-dev | 1.27 | 健保卡辨成「鑑寶卡」 |
| batch sensevoice | 200，實際 provider=sensevoice | 1.35 | 健保卡辨成「健寶卡」 |
| stream r2t2-live | ready、interim、final | 7.09 | 健保卡辨成「鑑寶卡」 |
| stream r2t2-dev-live | ready、interim、final | 4.32 | 健保卡辨成「鑑寶卡」 |
| stream gemini-live | ready、interim、final | 4.76 | 最終文字健保卡正確 |

openai 與 r2t2 以同一把帳號 key 同時請求；醫院專案當時啟用 zh/nan 分流，仍各自使用指定 provider，沒有被 Breeze 覆蓋。全部 batch／stream 結束後，帳號偏好仍為 `value=""`、`effective="breeze"`，與測試前一致。

### 真實 TTS

| provider／voice | 結果 | 秒數 | 音訊 |
|---|---|---:|---|
| indextts／hayley | 通過 | 4.44 | WAV，503,852 bytes，16 kHz，15.744 秒；完整醫院答案 |
| cosyvoice／child-female-01 | 通過 | 6.97 | MP3，26,637 bytes，24 kHz，6.600 秒 |
| gemini-tts／Kore | 通過 | 3.15 | raw PCM，201,600 bytes，24 kHz mono s16le，4.200 秒 |
| voxcpm／voxcpm2-cosy-young-female-01 | 通過 | 2.85 | WAV，506,924 bytes，48 kHz，5.280 秒 |
| voxcpm／barbet-hung-yi-lee | 失敗 | 0.96 | HTTP 200 audio/mpeg，0 bytes |
| edge-tts／zh-TW-HsiaoChenNeural | 失敗 | 0.79 | HTTP 200 audio/mpeg，0 bytes |
| edge-tts／zh-TW-YunJheNeural | 失敗 | 0.87 | HTTP 200 audio/mpeg，0 bytes |

### 已確認的待修問題

1. **過期 VoxCPM 聲音仍被列出**：`barbet-hung-yi-lee` 不在正式上游 catalog／voices，且部署已設為 excluded，但帳號授權資源清單仍含此聲音並選作該組 default_voice。呼叫上游回 422（內建參考聲音不存在）。改用現行有效聲音即成功，不能將此結果寫成 VoxCPM 服務故障。
2. **TTS 空串流被回成成功**：VoxCPM 錯誤被捕捉後轉到 Edge；Edge 對上游語音 WebSocket 握手遭 403 拒絕，`StreamingResponse` 已先送 200，因此用戶收到 0 bytes。明確錯誤應在送出 200 前處理；明確指定供應商時的備援行為也需釐清，不能以空音訊冒充成功。當時正式 `edge-tts` 為 7.2.8；尚未確認上游拒絕的根因，不宣稱升級即可修復。
3. **IP 入口憑證不匹配**：`https://192.0.2.10:8787` 使用自簽憑證，SAN 只有 localhost／openvman.local／127.0.0.1，未涵蓋 192.0.2.10。只匯入 CA 仍會主機名驗證失敗；應使用憑證有效的網域，或重新簽發涵蓋實際入口的憑證。測試未略過 TLS 驗證。

本輪僅實測、診斷及更新紀錄，尚未修復以上問題；未重新部署、重啟服務或修改正式設定。
