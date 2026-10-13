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
- 既有前後台沿用相同清單與語音請求，無需 UI 改版；Brain 無程式變更。正式服務尚未部署，帳號與 key 未更動，未 stage／commit／push。
