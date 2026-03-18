## ADDED Requirements

### Requirement: Gateway 接收多模態素材並分派解析
Gateway 服務 SHALL 接收來自前端（透過 Backend 轉發）的多模態附件，並根據素材類型（圖片、影片、音訊、文件）自動分派至對應解析模組，最終產生文字描述或轉錄結果。

#### Scenario: 使用者上傳 JPEG 圖片
- **WHEN** `user_media_upload` 事件中 `media.type` 為 `image/jpeg`
- **THEN** Gateway SHALL 呼叫 Vision LLM（GPT-4o Vision 或本地 LLaVA）取得圖片的中文描述，並將描述以 `{ "type": "image_description", "content": "..." }` 格式加入增強訊息的 `enriched_context` 陣列

#### Scenario: 使用者上傳 MP4 影片（≤60 秒）
- **WHEN** `user_media_upload` 事件中 `media.type` 為 `video/mp4` 且 `media.duration_sec` ≤ 60
- **THEN** Gateway SHALL 以每秒一影格採樣關鍵影格，每影格透過 Vision LLM 取得描述，合併後加入 `enriched_context`

#### Scenario: 使用者上傳音訊（MP3/WAV）
- **WHEN** `user_media_upload` 事件中 `media.type` 為 `audio/mpeg` 或 `audio/wav`
- **THEN** Gateway SHALL 呼叫 Whisper API（或本地 Whisper 模型）完成語音轉錄，結果以 `{ "type": "audio_transcript", "content": "..." }` 格式加入 `enriched_context`

#### Scenario: 使用者上傳文件（PDF/DOCX）
- **WHEN** `user_media_upload` 事件中 `media.type` 為 `application/pdf` 或 `application/vnd.openxmlformats-officedocument.wordprocessingml.document`
- **THEN** Gateway SHALL 呼叫 MarkItDown 將文件轉為 Markdown，並分段加入 `enriched_context`

#### Scenario: 媒體解析超時
- **WHEN** 任何媒體解析模組在 `MEDIA_PROCESSING_TIMEOUT_MS`（預設 5000ms）內未完成
- **THEN** Gateway SHALL 跳過該素材的解析，於 `enriched_context` 加入 `{ "type": "processing_error", "reason": "timeout" }`，且主回應管線應繼續執行

#### Scenario: 素材類型不支援
- **WHEN** `media.type` 不在支援類型清單中
- **THEN** Gateway SHALL 回傳 `400 Unsupported Media Type` 錯誤，拒絕處理

### Requirement: 媒體解析優先使用 Vision LLM，提供備援機制
Gateway 的圖片解析 SHALL 優先呼叫 Vision-capable LLM（透過 Brain 層共用的 provider router），若失敗則降級至 OCR（Tesseract）作為備援。

#### Scenario: Vision LLM 呼叫失敗（5xx 或 timeout）
- **WHEN** Vision LLM API 回應 5xx 或逾時
- **THEN** Gateway SHALL 自動切換至 OCR 備援，並在日誌中記錄 `media_ingestion_fallback` 事件
