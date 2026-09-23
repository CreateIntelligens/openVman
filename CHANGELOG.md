# Changelog

## [Unreleased]

### Added

- **對話紀錄頁補齊 JTI 的歷史紀錄功能**（VH-388）：勾選後可「刪除已選」（新端點
  `POST /brain/sessions/batch-delete`，逐筆回報 deleted／missing，部分不存在不讓整批失敗）；
  列表每頁 50 筆分頁（摘要仍一次抓、排序篩選在前端，只切畫面）；匯出可勾「簡化格式」
  （`simple=true`，每則訊息只留 role、content、created_at）。JTI 的「依語言篩選」沒做：
  session 沒有記錄語言。

- **記憶召回改由 Jev 篩相關記憶**（`memory/auto_recall.py`，`AUTO_RECALL_USE_JEV_FILTER` 預設 true）：
  命中記憶在同一次呼叫逐筆問相關性，≥ 0.5 才條列給主對話，每輪省掉 LLM 摘要那次呼叫
  （實打 535–722 ms）；失敗退回原本的 LLM 摘要。會把記憶原文送 Jev（使用者同意）。
- **知識庫段落 Jev 篩選**（`search_knowledge`，`RAG_JEV_SCREEN_ENABLED` 預設 false）：逐段問能否當
  答案依據與是否夾帶指令。EVAK 50 題離線：答案段落 54/54 保留、其他段落濾掉 143/196、每題平均剩
  2.1 段；p50 520 ms。每輪強制檢索都會多這段延遲，所以預設關。

- **後台 Live「自訂語音」接上前端 TTS**：relay 在 `custom` 下會清掉 Gemini 音訊，但後台沒有接 TTS，
  一直無聲。`useLiveSession` 新增 `onAssistantTurnComplete`，每輪 `is_final` 時交出整輪文字，
  聊天頁用既有的 `playTts()`（使用者選的 TTS 供應商與聲音）播放。
- **語音打斷與 A2A 的 Jev 選用閘門**（backend `app/jev_client.py`，皆預設關）：
  `JEV_INTERRUPT_ENABLED` 讓規則判不出的長句改問 Jev（自寫 30 題規則 23/30、Jev 29/30；逾時 0.6 秒
  或失敗維持中斷）；`A2A_JEV_PREFILTER_ENABLED` 在 Jev 的 no_reply 機率 ≥ 0.9 時省掉整輪 Brain。
  backend 共用一條 Jev 連線，暖連線 330–410 ms。

- **save_memory 授權改由 Jev 判斷**（`core/jev_client.py`、`tools/builtin/memory_tools.py`）：
  原本的關鍵字 regex 看到「記」就放行、「幫我記下來」「把生日存起來」反而擋掉（自寫 20 題
  5/20，Jev 20/20，實打 Jev 0.89／0.06）。現在問 Jev「這句是否明確要求長期記住」，≥ 0.5 才寫；
  只送當前使用者訊息，2 秒逾時、沒 key 或失敗退回 regex。`JEV_MEMORY_GATE_ENABLED`（預設
  true）、`JEV_GATE_TIMEOUT_SECONDS`（預設 2）。
- **Jev 影子多問一題 prompt injection**：同一次呼叫加 `injection` noul，log 多 `injection_score`，
  只記不擋；現行 `guardrails.py` 只有 4 條英文 regex、中文攻擊全漏（自寫 20 題 11/20，Jev 20/20）。

- **Jev 意圖影子觀測**（`brain/api/core/jev_shadow.py`，預設關閉）：與既有 BGE
  影子並排，對 `/brain/chat` 的一般使用者回合抽樣呼叫 TypeSafe Jev，把
  chat／knowledge／web／clarify 建議分類記進 log，不改路由、prompt 或工具選擇。
  - 外送內容寫死：當前訊息（最多 1024 字）+ 與正式 LLM 相同的對話歷史
    （`select_recent_messages()`，只留使用者與助手）；不送 system prompt、工具
    結果、知識庫或帳號資料；測試直接檢查送出的 HTTP body。
  - 抽樣 5%、timeout 600 ms 不重試、失敗冷卻 60 秒、每 process 每 UTC 日上限
    2000 次（重啟時從帳本補回當日已用數）。
  - 成功呼叫以 `provider=typesafe`、`kind=intent_shadow` 記進 `usage.db`。
  - 新設定 `JEV_SHADOW_*` 與 `TYPESAFE_API_KEY`，見
    `scripts/experiments/jev/OPERATIONS.md`。

- **TTS 與 Gemini Live 的用量記帳**：在此之前只有 LLM 呼叫進帳本，Live 與 TTS
  完全沒有計量——`brain/api/live/` 與 TTS router 裡一行記錄都沒有，連「有沒有人
  在用 Live」都得靠猜。
  - 帳本新增 `unit_type` 與 `units` 兩個欄位。LLM 以外的用量不是 token 計價：
    TTS 按字元、Live 按音訊秒數，混進 `input_tokens`／`output_tokens` 會讓
    `total_tokens` 變成把不同單位相加的無意義數字。舊資料 migration 後一律是
    `tokens`，既有欄位與統計不受影響。
  - Gemini Live 逐 turn 累積上行與下行的音訊秒數，在 `turnComplete` 記帳。
    輸入與輸出分兩筆，因為兩者費率不同，合併記就無法還原成本。
  - TTS 記在 `_try_synthesize()`——fallback chain 的單一收斂點，所有 provider
    與 targeted／chain 兩條路徑都經過它。只記成功的 hop，失敗的不計費。
    串流路徑（Gemini TTS、VoxCPM、Edge、IndexTTS proxy）不經過 fallback chain，
    在各自開啟串流後另外記一筆；串流一旦開啟上游就已開始計費，所以不等讀完，
    客戶端中途斷線仍然算數。快取命中在呼叫 provider 之前就返回，不計費。
  - 彙總端點依單位分開加總：`summarize_usage()` 回傳 `chars` 與 `seconds` 兩個
    欄位，而不是一個籠統的 `SUM(units)`——把字元數和秒數相加沒有意義。
  - Admin 用量頁顯示這兩種單位：總覽新增「TTS 合成字元」與「Live 音訊」兩塊
    （沒有該類用量時不顯示，避免整排零值佔版面），明細表新增「其他用量」欄。
    秒數以 `formatDuration()` 轉成「1 分 32 秒」這類可讀長度，不直接丟 92.4。
  - 事件帶上歸屬：`SynthesizeRequest` 新增 `usage_scope`，由 `usage_scope_for()`
    從 `CurrentAccount` 產生。主體判定沿用 `brain_proxy` 既有的規則——帶 embed
    key 記成 `embed_key` 主體（保留 `user_id`），否則記成 `user`——這樣 TTS 與
    LLM 的用量在 Usage 頁面可以用同一組維度彙總。
  - 新增 `POST /brain/usage/events`（沿用既有的 `X-Internal-Token`）。TTS 在
    Backend、帳本在 Brain，讓兩個服務同時寫同一個 SQLite 檔會有鎖競爭，也會
    讓「誰擁有帳本」失去單一答案；因此 Backend 改用 HTTP 寫入，與它代理讀取
    `/brain/usage/summary` 的方向對稱。記帳失敗只留 warning，不影響合成結果。

### Removed

- **BGE embedding 意圖影子**（`core/intent_shadow.py`、`INTENT_SHADOW_*` 設定、
  `scripts/experiments/intent-shadow/evaluate.py` 與 `OPERATIONS.md`）：用 centroid
  相似度猜意圖，2026-09-23 dev 多輪對話實測只有 9/19，並有一筆知識庫問題誤判閒聊。
  改由 Jev 影子觀測；排程測試移到 `test_jev_shadow.py`。評估報告與逐筆結果保留。
  embedding 本身仍負責知識庫檢索，不受影響。舊 `.env` 留著 `INTENT_SHADOW_*` 不會出錯
  （設定忽略未知欄位）。
- **SemIf 本機語意分流實驗退場**: `scripts/experiments/semif/` 的 compose、runner 與
  操作手冊刪除——它教的是怎麼跑一個結論已定（21/32 題隨選項順序改答案，不採用）的
  實驗。逐筆結果、`cases.jsonl`（Jev 評估用同一份 fixture）、`runner_used.py`（產生
  穩定性結果時的程式快照）與 REPORT 保留並改名至 `semif-evidence/`，因為
  SemIf 報告本身與 `browser-intent/P0-COMPATIBILITY.md` 的結論都引用它們。
  五處引用改指新路徑或 Jev 報告。

### Experiments
- 新增隔離的 Jev 官方 API 分流／語音打斷離線實驗，沿用 SemIf 同一份 48 筆合成案例（fixture SHA256 相符）與統計方式，透過 `typesafe-sdk` 呼叫 `POST /v1/systemone` 的 Choice 問題類型；正反序各一輪共 96 次呼叫全數正確、零順序翻轉，p50 約 258–275 ms。憑證使用根目錄 `.env` 的 `TYPESAFE_API_KEY`，並在 `.env.example` 提供欄位；不變更正式服務路由。
- 保存 A2A 隔離私有圈的真實 Hub／SSE／Brain 回覆證據；完成派工、durable enqueue、雙向 ACK 與約 9.55 秒往返，正式 A2A 開關保持關閉。
- 追加 SemIf 固定輸入與全排列穩定性診斷：32 題 × 24 種選項順序 × 3 次，保存凍結排程、逐筆分數與輸入 hash，分開統計重跑差異及順序敏感性；同輸入三次完全一致，但 21/32 題隨排列改答案，維持不接管正式路由。
- 新增隔離的 SemIf 語意分流／語音打斷離線實驗，提供繁體中文合成案例、固定上游與模型版本、選項順序穩定性及延遲量測；不變更正式服務路由。


### Changed
- **用量頁篩選器**: 日期改為快捷區間（最近 7／14／30／90 天、自訂），選快捷時直接
  算好起訖日，不用開兩個日期欄位。Embed key 從手打 ID 改為下拉選單，清單只有
  admin 能讀，非 admin 靜默留空改用手動輸入；選了專案會把金鑰清單縮到該專案。
  `Select` 新增 `label` prop，欄位名稱顯示在觸發器內選中值前面，省掉外面那行標題。
- **虛擬人前端正式環境改送靜態檔**: `frontend/app` 的 image 原本 runner 跑
  `pnpm dev`——每個使用者打開頁面都在讓 Vite 現場轉譯 TypeScript，掛著 HMR client
  與 esbuild 常駐程序。改成在 builder 內 `pnpm build`，runner 換 `nginx:1.27-alpine`
  只送 `dist/`。`index.html` 設 `Cache-Control: no-cache`（它記著當前版的 chunk
  hash，被快取會讓舊分頁去要已不存在的 chunk 而白屏），`assets/` 永久快取。
  admin 的 proxy 設定不變。開發熱重載改由 `docker-compose.dev.yml` 以
  `build.target: builder` + `command: pnpm dev` 提供。
- **前端共用語音核心抽取（ASR / VAD / TTS / 偏好儲存）**：將 `frontend/app`（Vue）與 `frontend/admin`（React）各自維護且漂移的語音辨識、VAD、語音合成與儲存邏輯統一抽取至無框架 TypeScript 模組庫 `frontend/shared/speech/`（`@shared/speech`）。
  - **純音訊工具**：統一 `wav.ts` 音訊編解碼、重採樣與 RMS 音量分析。
  - **ASR 與辨識核心**：統一 `browser-recognizer.ts`、`server-recorder.ts`、`vad-recognizer.ts` 與決策狀態機 `controller.ts`；錯誤訊息集中管理（D6），支援預設伺服器引擎（D1）、瀏覽器故障自動記憶體降級（D2）、閒置自動停止（D3）、VAD 模式（D4/D5）、預設系統設定選項（D7）與樂觀更新還原（D8）。
  - **TTS 串流與排程**：抽取 `pcm-stream.ts`、`scheduler.ts`、`selection.ts`（D9 成對驗證）、`fallback.ts`（D10 讀取並展示 `X-TTS-Fallback-Reason` 後端原因提示）與 `cache.ts`（LRU 快取）。
  - **儲存與相容性**：提供 `storage.ts` 統一使用 `speech.*` 鍵名並具備舊鍵向後相容無縫遷移（D11，舊鍵讀取後遷移且保留不刪）。兩端前端改為純薄層轉接，並更新 Docker 與建置管線以保證兩端各自獨立 build、test 全綠。


- **後台聊天室接上 ASR 引擎選擇**: 後台聊天室原本寫死瀏覽器內建辨識，跟帳號授權
  與「語音」頁的設定完全無關——per-account 授權上線時漏了這個介面。現在依帳號
  生效的引擎決定行為：`browser` 維持連續聆聽、講完自動送；其餘引擎改為錄音後
  上傳 `/api/v1/asr/transcribe`，按一下收音、再按一次送出。輸入列多一個引擎選單
  （來源是授權清單 `allowed`，只有一個可選時不顯示）。引擎名稱與說明抽到
  `components/asrEngines.ts`，跟「語音」頁共用。後端未變更。
- **後台伺服器 ASR 引擎加上 VAD**: 伺服器引擎本身沒有斷句，原本只能「按一下錄、
  再按一下送」。改用 Live 模式既有的 Silero VAD（`useVad`，在瀏覽器本機執行，
  聲音不外送）切出每一句，包成 16 kHz WAV 上傳——操作變成跟瀏覽器辨識一樣：開著
  一直聽、講完自動送，「聆聽中／等待語音」也有真的訊號。VAD 起不來時（模型或
  ONNX WASM 載不到，後者來自 jsdelivr CDN）自動退回按鍵錄音。
- **虛擬人聊天室的伺服器 ASR 引擎加上 VAD**: 同一套 Silero VAD（新增依賴
  `@ricky0123/vad-web`，按麥克風時才動態載入）。模型與 worklet 直接用後台 nginx 在
  同源提供的 `/admin/vad/`，不在版本庫裡再放一份。一次按鍵收一句：講完自動收音
  結束並送出，跟瀏覽器辨識同一種操作；VAD 偵測到講話時提示換成「聆聽中…講完會
  自動送出」。VAD 載不到時退回按鍵錄音並直接開始錄；麥克風權限被拒則照實回報，
  不當成 VAD 故障。
- **聊天室語音引擎切換**: 使用者可以替自己的對話選語音辨識引擎，選擇存在帳號上，
  重開瀏覽器沿用。新增 `browser`（瀏覽器內建辨識，語音留在使用者裝置上，不送到
  伺服器），以及後台的「開放使用者自選」勾選區決定哪些引擎出現在聊天室選單裡。
  引擎由後端依帳號查，不接受呼叫端指定，否則管理者的開放清單形同虛設；選過但
  之後被關閉的引擎會自動回退成全站設定。瀏覽器辨識在不支援的瀏覽器、或使用者
  拒絕麥克風／沒有麥克風時，當場退回伺服器引擎。後台試辨識與聊天室都會顯示
  這一次實測到的轉寫耗時。Migration 12 為 `account_defaults` 新增 `asr_provider`。

### Changed

- **Gemini Live 升級到 `gemini-3.8-live`**：預設模型由 `gemini-3.1-flash-live-preview`
  換成 `gemini-3.8-live`（`brain/api/config.py`）。同時處理遷移文件列出的破壞性
  變更：3.8 一般版**不接受** `thinkingConfig.thinkingLevel`，帶上去會被 websocket
  以 1007 關閉，因此 `_build_setup_message()` 改成依模型判斷才送，設了卻用不到時
  留一筆 warning；`extended-thinking` 變體與舊的 3.1 preview 仍照送。遷移文件其餘
  項目對本專案是 no-op：從未使用 `enable_affective_dialog` 或 `proactive_audio`，
  工具宣告沒有設 `behavior`（沿用新的 `NON_BLOCKING` 預設），回覆模態本來就是
  `AUDIO` 搭配 `outputAudioTranscription`。`.env.example` 補上 `LIVE_GEMINI_MODEL`
  與 `LIVE_GEMINI_THINKING_LEVEL` 說明。
  以真實 API 驗證：`gemini-3.8-live` setupComplete 正常、單輪對話取得 14 個音訊
  chunk 與完整逐字稿；帶 `thinkingLevel` 則重現 1007「Thinking level is not
  supported for this model」。

### Fixed

- **Gemini 在模型吐出空參數 tool call 後整輪 400**：模型偶爾呼叫工具卻不帶參數（`arguments=""`），
  這筆寫回對話歷史後，Gemini OpenAI 相容端點下一輪回 400 `INVALID_ARGUMENT`（dev 實測重現：
  只有空字串參數是這個錯）。`llm_client` 建 `LLMToolCall` 時把空參數統一成 `"{}"`，參數缺漏
  交給工具 schema 驗證回報。非串流與串流兩條路徑都處理。
- **Gemini Live 的中文轉錄是簡體**：`inputAudioTranscription`／`outputAudioTranscription` 帶
  `languageCodes`（新設定 `LIVE_GEMINI_TRANSCRIPTION_LANGUAGES`，預設 `zh-TW`）後直接回繁體
  （2026-09-23 以 edge-tts 語音實測；單數 `languageCode` 會被 API 拒絕）。
- **後台 Live 模式完全沒有聲音**：2026-04 把 TTS 從 relay 移到前端時，`brain_live_relay.py` 不分
  `voice_source` 一律清掉 Gemini 音訊；avatar 送 `custom` 自己跑 `/tts_stream` 沒事，後台聊天頁的
  「Gemini 語音」只播 relay 送來的音訊，就一直無聲。現在只有 `voice_source=custom` 才清。
  後台「自訂語音」在 Live 下仍無聲（前端沒有接 TTS），另案處理。
- **Gemini Live 重連時送訊息可能 AttributeError**：`ensure_connected()` 之後又讀 `self._transport`，
  中間的 await 期間重連流程可能把它清成 None。改成 `ensure_connected()` 回傳這次的連線物件。
- **Gemini Live 的 save_memory 沒有任何授權檢查**：文字模式有「使用者明確要求才寫」，Live 的
  `_save_memory` 直接寫入，模型想存就存。現在兩條路徑共用同一個閘門。
- **embedding 批次峰值 VRAM 過高**：compose 預設 `EMBEDDING_BATCH_SIZE` 由 32 降到 8。32 段 8000 字
  實測峰值 5880→2810 MiB、耗時 8.5→5.5 秒；原本加上 VoxCPM 的 10 GB 幾乎吃滿 16 GB 的 A4000。

- **embedding 服務的 VRAM 只漲不降**：bge-m3 權重約 2 GB，但 PyTorch 會把大批次
  （`EMBEDDING_BATCH_SIZE=32` × `EMBEDDING_MAX_LENGTH=8192`）的峰值記憶體留在快取
  裡不還，跑了幾天的容器常駐到約 4.7 GB，擠壓同卡的 VoxCPM。現在每次推論後、
  仍持有 `EMBEDDING_MAX_CONCURRENCY` semaphore 時呼叫 `torch.cuda.empty_cache()`；
  以前只在 OOM 重試時才釋放。CPU 裝置不受影響。每次釋放超過 64 MB 會記一行
  `CUDA cache released texts=… reserved_mb=前->後 allocated_mb=…`，用來觀察常駐量
  是否仍隨時間上漲。

- **Gemini Live 沒有保存模型回覆，切回文字模式後上下文斷掉**：
  `live/gemini_live.py` 只在 `_save_input_transcription()` 存過使用者發言，模型
  回覆抽出文字後只推給前端顯示就丟掉，整支檔案的 `append_session_message`
  只被呼叫一次且 role 固定是 `user`。結果 Live 對話留在 session 的歷史全是
  user 訊息、沒有半句 assistant，使用者切回文字模式再問「我剛問了幾題」時，
  模型看不到可用脈絡，回答「這是我們在這段對話中的第一句」。
  改成比照文字模式的 `_flush_assistant_turn()`：逐則 `serverContent` 累積回覆
  文字，在 `turnComplete` 與 `interrupted`（已播出去的半句同樣要留）時併成
  完整一句寫入 `assistant`，並補上 `archive_session_turn()` 的 turn 歸檔。
  語音輸入也一併記錄 `_last_user_message`，否則語音回合歸檔時會少掉問句。

- **Brain 對模型空回覆回 400**: 模型連續回空（`agent_loop` 已催過一次仍空）時，
  `ValueError("LLM 沒有回傳內容")` 被 `routes/chat.py` 當成 guardrail 擋下的壞
  請求：回 400 讓前端不重試、`guardrail_blocks_total` 誤計，且該路徑不記 log，
  錯誤訊息只進 metrics。新增 `LLMEmptyReplyError`（仍是 `ValueError` 子類，
  fallback chain 靠 `except ValueError: raise` 讓空回覆不在下一個 hop 重試，型別
  不能改），route 改回 502 `LLM_OVERLOAD` + `retry_after_ms`，並在兩條錯誤路徑都
  記 `log_exception` 帶 trace_id。
- **按下麥克風後頭一兩秒收不到音**: 兩個前端的 VAD 每次按鍵都重新載套件、抓 ORT
  WASM 與 2 MB 模型、要麥克風、建 worklet，第一次一兩秒、之後幾百毫秒，而畫面在
  這段期間已顯示「等待語音」——開頭說的字其實收不到。改成實例只建一次、跨次按鍵
  重用（`pause()` 放掉麥克風軌、`start()` 再要回來，模型不重載，只有卸載才
  `destroy()`），並新增 `starting` 狀態：真的開始收音之前按鈕與輸入框顯示「麥克風
  啟動中…」，不假裝已經在聽。後台 Live 模式共用 `useVad`，一併受惠。`useVad`
  原本沒有測試，補了 7 個。
- **後台聊天室工具列蓋住輸入框**: 工具列原本 `absolute` 疊在 textarea 上，靠固定的
  `padding-bottom` 預留高度。加上 ASR 引擎選單後控制項換行，工具列長高蓋住正在打的
  字。改放正常流、在 textarea 下方，任何高度都不會蓋到內容。
- **虛擬人聊天室重整後設定變回預設**: 知識庫、人物、吉祥物、語音引擎、聲音、背景
  每次開啟都被帳號預設蓋掉。偏好其實有存，但開場抓清單時 `fetchProjects`／
  `fetchTtsProviders` 先把欄位清成空字串，store 的 `watch` 把空字串寫回
  localStorage，接著又直接套 `accountDefault()`。改成先記下還原的值再清空，並讓
  選過的值優先：仍在清單內就沿用，被收回授權或刪除才退回帳號預設。語音引擎與
  聲音當成一組判斷；背景的預設值是 `dark`，改用新增的 `hasPref()` 看有沒有存過。
- **虛擬人聊天室按了麥克風沒反應**: 按鈕的收音狀態永遠綁瀏覽器辨識，但切換用的是
  帳號選定的引擎。選了伺服器引擎時按下去其實有在錄音，按鈕卻毫無變化。改成綁
  實際在收音的引擎；AI 說話時暫停收音的邏輯有同一個錯，一併修正。
- **收音狀態看不出來**: 兩個前端都補上明確提示。虛擬人端：收音中按鈕有呼吸動畫
  （留在按鈕內，不外擴蓋到輸入框）、輸入框提示改成「收音中…」並變色、新增
  「辨識中」轉圈狀態，另有 `aria-live` 狀態給螢幕閱讀器。後台：按鈕文字依引擎
  顯示「收音中 · 再按送出」或「聆聽中／等待語音」，辨識中顯示轉圈且不可再按。
- **後台聊天室沒開 VLM 也有鏡頭按鈕**: 後台從來沒查過 `/vision/health`，按鈕一律
  顯示。新增 `useVisionAvailable`，規則與虛擬人端相同（問到之前與 401 都不顯示、
  5xx 才 fail-open），沒開 VLM 時按鈕整個不出現。
- **沒開 VLM 卻出現鏡頭按鈕**: 開場的 `/vision/health` 偶爾跑在工作階段就緒前面
  而拿到 401，前端的 fail-open 把它當成「後端掛了、先當作可用」。401/403 改為
  重問一次，仍失敗就維持不顯示；5xx 與網路錯誤照舊 fail-open。
- **Prompt 與專案模板預設強制純文字**: 在全域回答規則（`DEFAULT_ANSWER_RULES`、`NO_TOOLS_ANSWER_RULES`）與新專案模板（`WORKSPACE_TEMPLATES`）中明定純文字格式規範，嚴禁 Markdown 格式（`**` 粗體星號、`*` 斜體、`#` 標題、`-` 列表分點或反引號）與 emoji，防止 LLM 在規格與數值周圍輸出星號導致字幕顯示及前端樣式異常。
- **語音頁分頁不記位置**: `Tts.tsx` 用裸 `useState`，是後台唯一沒存的頂層分頁。
  改用 `useLocalStorageState`（`admin.tts.active_tab`，帶允許值清單）。順手補上
  該檔測試的 `localStorage.clear()`——分頁一旦會持久化，案例之間就會互相污染。
- **後台子視圖重整後掉回預設**: 只記了分頁沒記 `?view=`，從沒帶路由的網址進來
  （登入後轉址就是）會還原分頁卻掉子視圖。改記 `brain-active-sub-view`，且寫在
  正規化網址的 effect 裡而不是 `applyRoute`——從網址直接進來的路由不經過後者，
  寫在那邊會讓舊子視圖殘留到沒有子視圖的分頁上。
- **偏好寫入在無痕模式會炸掉畫面**: `writePref`／`readPref` 沒有 try/catch，
  Safari 無痕下 `setItem` 丟 `QuotaExceededError`，而它是從 store 的 `watch()`
  裡呼叫的，例外會竄進 Vue 的響應式系統。一併補上 `removePref`（同時清掉未綁定
  的舊鍵，否則 `readPref` 的舊值回退會把它復活）。
- **後台下拉選單樣式**: `select.input` 補上 `appearance: none`。先前只有頭像端的
  `CustomSelect` 修過，後台四處原生 `<select>`（帳號權限、角色、批次臨時帳號）
  仍由瀏覽器另外畫一層邊框與箭頭，看起來像沒套樣式。一併讓 option 跟著深淺色走。
- **回覆深度選項排版**: `.mode-toggle` 原本寫死兩欄，三個選項會排成 2+1，最後一個
  獨佔一列。改成依選項數平均分欄；窄螢幕仍疊成一欄（`grid-auto-flow` 需一併改回
  `row`，只覆寫 `grid-template-columns` 蓋不掉）。
- **ASR 試辨識上傳音檔**: 修正選了檔案卻顯示「未選擇任何檔案」——清空 input 的
  `value` 會一併清空 `files`，那行被放在讀取檔案之前。同時把真實檔名一起送出，
  先前寫死 `preview.webm` 會讓上傳的 mp3 在後端以 webm 解碼而轉檔失敗。

### Changed

- **Experiment Artifact Hygiene**: Move SemIf console logs to the ignored local logs directory while retaining structured evaluation evidence. Ignore runtime logs and gateway temporary data; scope catalog PDF/CSV exclusions to the actual local artifacts.

- **Operations Documentation Cleanup**: Retire the outdated live-pipeline verification draft, move intent-shadow instructions alongside its experiments, and remove stale account rollout details and unverified GPU deployment assumptions. Correct the admin delegation verification checklist.

- **Documentation Organization**: Group specs, operations and integration guides under a single docs index; archive early task plans, research and one-off notes with original statuses intact. Refresh repository references and remove missing-document navigation.

- **Browser Intent Navigation**: Link browser-model compatibility notes and related experiment reports from the documentation index.

- **A2A Validation Readability**: Consolidate absent/blank input and length checks, simplify optional context normalization, and share task/group type regression cases without changing errors or outbound payloads.

- **Intent Shadow Readability**: Separate centroid initialization from query scoring, centralize observation input limits, and remove redundant test setup without changing classification or scheduling behavior.

- **Avatar Page Modules**: Split character, background, and mascot panels into `components/avatar/`, with shared asset styles and a `useMascotSnapshotQueue` hook. The page retains form state, asset loading, and the snapshot iframe; tab and upload behavior are unchanged. The snapshot comment now correctly describes recapturing missing thumbnails or URLs outside `/static/mascots/`.
- **Embed Key Repository Module**: Move Embed key storage to `auth/embed_keys_repository.py` and shared exception/time primitives to `auth/_repository_base.py`. Keep the existing `auth.repositories` import entry point and declare its public repositories, errors, batch types, constants, and helpers in `__all__`, so wildcard imports include account repositories as well as Embed key symbols. Database transactions and authorization behavior are unchanged. See `docs/operations/account-administration.md` for module boundaries.

### Added

- **Embedding Intent Shadow**: Add opt-in, sampled BGE intent observations for ordinary chat and SSE without changing routing, prompts, or forced knowledge search. Limit each process to one background task with no queue, HTTP timeout, no retries, and failure cooldown; pin embedding identity and omit message text from observation logs. Add fault-injection tests and a frozen 64-case evaluation (52 correct; one knowledge-to-chat error), so predictions remain observational.

- **Collapsible Navigation Groups**: Workspace, Knowledge, and System now collapse independently on desktop and mobile. Group preferences are account-scoped and shared across both menus; the active group opens on initial load and navigation, while other groups default to collapsed.

- **TTS Preview**: Add `/admin/tts` with authorized provider/voice selection, editable sample text, direct speech playback, cancellation, and actual-provider fallback feedback. Preview uses the existing authenticated speech API and does not create chat history.

- **Administrator Delegation**: Administrators can now create administrators and manage the accounts they created directly, instead of every administrator action above `user` requiring ROOT. Role changes and password resets stay ROOT-only, and no administrator can manage its own account through the account APIs.

  Delegation narrows monotonically, enforced in the database transaction:
  - A new administrator inherits its creator's ceiling at creation time. Previously a missing scope row meant *unrestricted*, so a scoped administrator could create a subordinate and reach resources outside its own ceiling through it.
  - Shrinking a ceiling now cascades down the `created_by` chain, clamping every descendant administrator's scope and revoking the grants and defaults each level can no longer support. Previously only the target's direct grants were revoked, so a subordinate kept resources its delegator had lost.
  - A scoped administrator cannot hand out an unrestricted ceiling, and can only assign a subset of its own.

  The account list shows the whole delegation subtree, but only directly created accounts are editable — releasing the whole subtree would let a demoted intermediary still reach its grandchildren.

### Fixed

- **A2A Skill Validation**: Reject non-string task/group fields, boolean delegation hops, and invalid or oversized context IDs before contacting Backend. Normalize blank context IDs to absent, document the existing UTF-8 byte limit, and align tool declarations. Replace stale error-message expectations with field-specific regression tests and a loopback HTTP transport check.

- **Interruption Guard**: Handle single-word stop commands before noise filtering; ignore recognized acknowledgements, continue/negated-stop phrases, and quoted background speech while preserving later corrections and new questions. Treat transcript-free `client_interrupt` events as explicit stop controls, preserving the avatar stop action. Add classifier and WebSocket/task-cancellation regression coverage; no model inference is introduced.

- **Docker Publish Reuse**: Replace last-commit path filtering with fingerprints of committed Docker build inputs, including automatically discovered COPY/ADD sources and ignore files. Reuse only matching published source tags, so multi-commit pushes and cancelled or failed builds cannot relabel stale `latest` images. Pin Backend builds to the resolved base manifest digest, log the complete push range and decision, and run image-reuse regression tests before publishing. The first run rebuilds images that lack fingerprint tags.
- **Voice Default Consistency**: Derive the provider from registered voice metadata on every defaults write, preserving explicit provider choices for legacy metadata. Grant narrowing now skips replacement voices with unknown providers and clears both voice fields when none are usable; login stays available while the provider list is empty and TTS fails closed. Regression tests cover malformed metadata, login/TTS authorization, all defaults write paths, descendant batch visibility versus mutation rights, and the repository import contract. Correct repository iterable and optional-value type hints.
- **Administrator Scope Fail-Closed**: Runtime lookup errors now abort administrator resource resolution instead of granting unrestricted access. Scope regression tests cover runtime/repository failures, explicit repository injection, resource lists, and ROOT behavior. The account administration guide clarifies existing zero-grant account creation and required access-update validation.
- **Knowledge Upload Limits**: Admin knowledge and workspace uploads now fetch `GET /api/v1/uploads/limits` before sending files instead of enforcing a hard-coded 5 MiB limit. Backend applies `DOCUMENT_MAX_UPLOAD_BYTES` to raw uploads and text passthrough uploads as well as converted documents, and blocks generic proxy paths from bypassing those handlers.
- **Midnight Date Boundaries**: Dreaming compares completion timestamps in `DREAMING_TIMEZONE` (legacy timestamps without an offset are UTC) and uses one configured local date for each cycle's daily memories and report. Admin Usage now uses `Asia/Taipei` for its default dates, inclusive date selection, event display, and trend buckets, sending UTC half-open query boundaries. The timeseries endpoint accepts `report_timezone=UTC|Asia/Taipei` (default UTC).

### Breaking Changes

- **Unified API Route Families**: The Backend HTTP and WebSocket surface collapses into three families — `/api/v1/*` for the application API, `/v1/audio/*` for OpenAI-compatible endpoints, and `/static/*` for served files. Only `/healthz`, `/metrics`, `/metrics/prometheus`, `/docs`, `/redoc`, and `/openapi.json` stay at the root. Every retired path returns **404** from the Backend and from both nginx configurations: there is no redirect, alias, rewrite, or transition period, and the `410` stubs for the iframe-era embed routes are deleted. Update every caller before deploying.

  | Old | New |
  |---|---|
  | `/api/auth/*` | `/api/v1/auth/*` |
  | `/api/users/*` | `/api/v1/users/*` |
  | `/api/temporary-accounts/*` | `/api/v1/temporary-accounts/*` |
  | `/api/projects*` | `/api/v1/projects*` |
  | `/api/avatar*` | `/api/v1/avatar*` |
  | `/api/backgrounds*` | `/api/v1/backgrounds*` |
  | `/api/vision/*` | `/api/v1/vision/*` |
  | `/api/knowledge/upload\|fetch\|youtube` | `/api/v1/knowledge/upload\|fetch\|youtube` |
  | Brain proxy `/api/{path}` (chat, knowledge, sessions, memories, personas, search, health, identity, protocol, metrics, embed, dreaming, skills, tools) | `/api/v1/{path}` |
  | `/characters` | `/api/v1/characters` |
  | `/v1/tts/providers` | `/api/v1/tts/providers` |
  | `/tts/stream` | `/api/v1/tts/stream` |
  | `/v1/usage/events`, `/v1/usage/summary` | `/api/v1/usage/events`, `/api/v1/usage/summary` |
  | `/uploads` | `/api/v1/uploads` |
  | `/jobs/{id}` | `/api/v1/jobs/{id}` |
  | `/admin/dlq` | `/api/v1/dlq` |
  | `/documents/convert` | `/api/v1/documents/convert` |
  | `/ws/{client_id}` | `/api/v1/ws/{client_id}` |
  | `/internal/enrich` | `/api/v1/internal/enrich` (still internal-token only) |
  | `/v1/audio/speech` | unchanged |
  | `/assets/{id}/…` | `/static/characters/{id}/…` |
  | `/mascots/{id}/…` | `/static/mascots/{id}/…` |
  | `/backgrounds/{id}/…` | `/static/backgrounds/{id}/…` |
  | `/openvman-avatar-sdk.js` | `/static/sdk/openvman-avatar-sdk.js` |
  | `/sdk/runtime/*` | `/static/sdk/runtime/*` |
  | `/healthz`, `/metrics`, `/metrics/prometheus`, `/docs`, `/redoc`, `/openapi.json` | unchanged |

  Asset URLs returned by the mascot, background, and character APIs (`vrm_url`, `thumbnail_url`, `url`) now start with `/static/`. The Avatar SDK's documented script URL is `/static/sdk/openvman-avatar-sdk.js` and its default `assetsBaseUrl` is `/static/characters/`.

### Added
- **888a2a-lite Agent-to-Agent Network Integration**: Added an optional Backend-owned inbound SSE bridge and Backend-facaded Brain skills for the legacy `/hub/v1` Hub. Private-circle access uses an injected registration-only `A2A_HUB_KEY`; durable SQLite WAL enqueue-before-ACK, replay deduplication, Redis leader coordination, bounded delivery, and anti-echo suppression protect at-least-once processing. Gated by `A2A_ENABLED=false` by default.
- **2md Web Tool Herd Protection**: Standardized the immutable `TWO_MD_BASE_URLS` order for `2md.aiurl.tw`, `2md.glsoft.ai`, and `create360.ai`; added bounded sequential fallback, shared deadlines, full-jitter delays, local single-flight, optional Redis circuit/half-open coordination, usage-safe telemetry, and explicit exclusion of OCR/deep-crawl async features from synchronous chat.
- **Temporary Login Password History**: Admin batch records now show full login passwords with copy controls instead of internal `tmp-…` usernames. New batches save account-bound Fernet ciphertext in auth schema migration 10 while retaining bcrypt login verification. Admin-only batch responses expose nullable `accounts[].password` with `Cache-Control: no-store`; legacy or undecryptable records show「密碼未保存」. `AUTH_TEMPORARY_PASSWORD_SECRET` optionally separates encryption from the session secret. See `docs/operations/account-administration.md` for key preservation and rotation.
- **Embedding Gateway & Client Exponential Backoff Retries**: Added resilient HTTP retry handling with exponential backoff, jitter, and `Retry-After` header parsing across `GeminiApiProvider`, `OpenAiApiProvider`, and `VoyageApiProvider` in `brain/embedding/registry.py`, as well as `GatewayRemoteTextEmbedder` in `brain/api/memory/embedder.py` for handling HTTP 429 and transient 5xx responses under high concurrency. Local BGE embeddings catch CUDA out-of-memory errors and automatically retry with batch size 1. Configurable via `EMBEDDING_MAX_RETRIES`, `EMBEDDING_RETRY_BASE_DELAY`, and `EMBEDDING_RETRY_MAX_DELAY`.
- **Admin Account Management Tabs**: Reorganized the Admin Accounts page into two keyboard-accessible top-level tabs:「建立帳號」(Create Account) and「編輯／管理」(Edit / Manage). The page title and concise tab labels share a compact header without repeated subtitles. Formal account lists and temporary batch history live under management, separate from creation forms. Batch history supports an all/unused/active/expired/revoked status dropdown, matching counts, and refresh without resetting the filter. Newly generated temporary passwords remain available when switching between the main tabs. Account actions retain their resource grants, resource ceilings, credential resets, suspension, session revocation, and safe deletion controls. See `docs/operations/account-administration.md` for the workflow.
- **Administrator Resource Scopes**: Added fine-grained resource ceilings that ROOT can assign to administrators (`admin_resource_scopes` and `admin_scope_state` tables, `AdminScopeRepository`, `GET/PUT /api/v1/users/{user_id}/scope`). Scoped administrators can only see and grant resources within their assigned pool; narrowing a scope transitively revokes out-of-scope grants and repoints dangling defaults, caps assignable options in `/api/v1/users/access-options`, and provides an inline management panel (`AdminScopePanel`) in the Admin Accounts page.
- **CosyVoice3 TTS Provider**: Added `CosyVoiceAdapter` (`backend/app/providers/cosyvoice_adapter.py`) supporting 臺灣台語 synthesis via CastAgent-compatible `/v1/*` endpoints, integrated into the router fallback chain (IndexTTS → VoxCPM → CosyVoice → Gemini → GCP → AWS → Edge-TTS), health probes (`cosyvoice`), buffered endpoint on `POST /api/v1/tts/stream`, and configured via `TTS_COSYVOICE_URL`, `TTS_COSYVOICE_API_KEY`, `TTS_COSYVOICE_DEFAULT_VOICE`, and `TTS_COSYVOICE_EXCLUDED_VOICES`.
- **CDI GPU Device Reservations**: Switched compose GPU definitions to Container Device Interface (`driver: cdi`, `nvidia.com/gpu=all`), preventing systemd `daemon-reload` from clearing container GPU cgroup permissions.
- **Admin Usage Page**: New 用量 page showing total LLM calls and tokens, average tokens and latency per call, the average number of LLM calls per conversation turn, provider and model breakdowns, and the recent events grouped by trace so a turn's calls sit together. Filters cover date range, project, principal type (account or embed key), and principal id.
- **Embed-Key Principal**: Third-party pages can now drive a conversation with a public `X-Embed-Key` instead of a session. A key binds one project, an exact-origin allowlist, default character/persona/voice, a per-minute rate limit, and a daily quota; the fail-closed auth middleware resolves it into a restricted principal limited to chat, characters, TTS providers/stream, speech, health, and character files, emits CORS only for keyed requests, and forwards `X-Principal-Type`/`X-Principal-Id` so the usage ledger can be summarised per key. Administrators manage keys at `/api/v1/embed-keys` and on the new Admin **Embed 金鑰** page.
- **Video Character Mascots**: Admins can register an existing video avatar character as the corner mascot. Mascot visibility follows both mascot and character grants, and host-played TTS is forwarded as 16 kHz mono PCM so the video runtime can lip-sync without duplicate audio output.
- **First-Class NEN LLM Provider**: Added dedicated `NEN_API_KEY` and `NEN_BASE_URL` settings and explicit `nen:<model>` fallback hops. NEN continues to use the OpenAI-compatible transport while retaining its own provider identity in routing, health, metrics, and usage records, so it no longer occupies the shared primary-provider or OpenAI settings.
- **Token Usage Ledger**: Brain now records every LLM call (input / output / cached / reasoning tokens, provider, model, latency) into an append-only SQLite ledger at `brain/data/usage.db`, attributed to the user, project, session and trace of the request via a context scope. Streaming calls request `stream_options.include_usage` (toggle `LLM_STREAM_INCLUDE_USAGE`). `/brain/chat` responses carry a per-turn `usage` summary, Brain exposes `/brain/usage/summary` and `/brain/usage/events`, and Backend fronts them at `/api/v1/usage/*` with non-admin accounts scoped to their own user id.
- **VoxCPM Provider**: Added `VoxCPMAdapter` (`backend/app/providers/voxcpm_adapter.py`) calling the VoxCPM360 gateway's CastAgent-compatible `/api/v1/tts/synthesize`, wired into the fallback chain after IndexTTS, the Admin provider/voice registry, the backend health payload (`voxcpm`), and configured via `TTS_VOXCPM_URL` / `TTS_VOXCPM_API_KEY` / `TTS_VOXCPM_DEFAULT_VOICE`.
- **Repository Security Audit Skill**: Added the versioned `.agents/skills/security-audit` methodology and lock record so future audits use the same reproducible checks. Local Claude/KiloCode symlink aliases remain ignored.
- **Admin Session Management Page**: Added a dedicated Sessions workspace for cross-persona browsing, filtering, sorting, batch export, deletion, and one-click deep links back into Chat.
- **Filtered Chat Session Export**: Added Admin JSON export for one, selected, or all filtered sessions, including the supported public message metadata while excluding internal-only fields.
- **Scoped Portal Project Editing**: Allowed portal-enabled formal and temporary accounts to edit explicitly granted project content while reserving project creation, deletion, and global resource mutation for administrators.
- **Watchtower Docker 29 Compatibility**: Configured the default deployment to use Watchtower Docker API `1.44`, matching Docker Engine 29's minimum API requirement while retaining label-only updates.
- **Docker Hub Multi-Architecture CI/CD**: Added `docker-publish.yml` using Node.js 24-compatible Docker actions, Buildx, and QEMU. Backend, Admin, and Avatar images publish `linux/amd64` + `linux/arm64`; CUDA/PyTorch Brain API and Embedding images publish `linux/amd64`.
- **Worktree HMR Compose Override**: Made `docker-compose.yml` the production-first, public-registry deployment with Watchtower enabled by default, and added `docker-compose.dev.yml` to restore source mounts, Python reload mode, frontend HMR volumes, and Watchtower isolation for Git worktrees.
- **GitHub Actions Node.js 24 Runtime**: Upgraded the protocol-contracts workflow to `actions/checkout@v6` and `actions/setup-python@v7` so action internals no longer target the deprecated Node.js 20 runtime.
- **External Tool Feature Flags**: Added `URL2MD_SEARCH_ENABLED`, `URL2MD_READ_ENABLED`, and `WIKI_PUBLISH_ENABLED`, all defaulting to `true`; disabled tools are removed from HTTP tool registration and Gemini Live declarations after Brain restart.
- **2md Web Tools and David888 Wiki Publisher**: Replaced the legacy URL-only web tool with `search_web(query)` and `read_web_page(url)` backed by `2md.aiurl.tw`, `2md.glsoft.ai`, and `create360.ai` fallback order. Added `publish_wiki(path, markdown)` for long reports and sharing; the tool returns only the public `shareUrl`, never the private edit URL. The same tools are available in HTTP chat and Gemini Live sessions.
- **ROOT Account Role**: Added a single `ROOT` role above `admin` (`ROOT > admin > user`) with a centralized actor/target policy (`backend/app/auth/policy.py`) enforced at the repository layer, so no access path can skip it. ROOT can create, disable, delete and reset administrators; administrators can only manage regular and temporary accounts and cannot promote themselves. ROOT itself cannot be created, deleted, demoted or reassigned through the admin API. High-privilege operations write audit events that never contain passwords or hashes, and role or password changes immediately revoke the target's sessions. The ROOT username defaults to `ai360` and is configurable through `AUTH_ROOT_USERNAME`.
- **Shared Inference Endpoints**: Exposed the embedding and VLM services through the edge nginx under `/api/embedding` and `/api/vlm`, both Bearer-authenticated with rate and connection limits. The embedding base URL is itself the embed endpoint, and an OpenAI-compatible path (`/api/embedding/v1/embeddings`) lets consumers point an off-the-shelf OpenAI client at the service.
- **Gemini TTS Provider**: Added `GeminiTTSAdapter` (`backend/app/providers/gemini_tts_adapter.py`) integrating the Gemini TTS Console API into the backend's TTS fallback chain, with dedicated config settings (`TTS_GEMINI_*`) and pytest coverage (`test_gemini_adapter.py`, `test_gemini_config.py`).
- **Dynamic Gemini Model Discovery**: Implemented a dynamic model discovery service (`model_discovery.py`) using the `google-genai` SDK to query, filter (for `generateContent` actions), and sort available models dynamically (Pro -> Flash -> Flash-Lite -> Others) with a thread-safe 10-minute TTL cache.
- **Dynamic Fallback Chain Generation**: Overhauled fallback chain generation (`models_config.py` and `fallback_chain.py`) to lazily initialize a Gemini client and dynamically expand Gemini provider hops into the dynamically discovered model list.
- **Fallback Graceful Degradation**: Added graceful degradation safety net that falls back to static `FALLBACK_MODELS` if dynamic API discovery fails due to network or credential errors.
- **Dynamic Model Fallback Testing**: Added comprehensive pytest coverage for dynamic discovery, sorting logic, graceful degradation on error, and fallback chain integration (`test_llm_fallback_chain.py`).

### Changed / Fixed
- **Restore Account Creation Resource Permissions**: Restored resource permissions selection directly within the formal account creation form, allowing administrators to configure grants and default resources during user creation while still retaining the ability to modify permissions from the account list afterwards.
- **VoxCPM Streaming TTS Endpoint**: Connected VoxCPM360's low-latency streaming endpoint (`/api/v1/synthesize/stream`) via `VoxCPMAdapter.open_stream` and `/api/v1/tts/stream`, returning `audio/wav; rate=48000` streams directly from the GPU. Integrated with `frontend/app` (`useTtsStreamer.ts`) for real-time PCM resampling and lip sync, and with `frontend/admin` (`synthesizeSpeech`) to cut synthesis latency down to ~1s without waiting for full MP3 transcoding.
- **Mascot Auto-play**: When the mascot is expanded, AI text replies automatically play TTS with lip-sync; collapsing it stops the reply that is playing and disables auto-play until it is expanded again. Live voice conversations are not affected by the mascot state.
- **RRF Retrieval Fusion**: `search_knowledge` now fuses the per-query result lists (AI-rewritten queries plus the original user message) with Reciprocal Rank Fusion instead of comparing raw distances across queries, so a chunk surfaced by several queries ranks first; the fused list keeps up to `KNOWLEDGE_SEARCH_MERGE_LIMIT` (default 5) chunks rather than a single query's `top_k`. Records expose `_rrf_score`.
- **Admin Streaming TTS Playback**: The Admin chat now plays `/api/v1/tts/stream` responses as they arrive: PCM chunks are scheduled into an AudioContext while the rest is still being synthesised, the mascot receives volume and 16 kHz PCM from the same chunks, and the finished stream is rebuilt into a proper WAV for cache replay. The stream endpoint is used for the automatic provider too, and the Backend routes an unspecified provider to VoxCPM's stream when IndexTTS is not configured.
- **Follow-up Round Cap**: After the parallel first search round the model may add at most `CHAT_MAX_FOLLOWUP_TOOL_ROUNDS` (default 1) more tool rounds before tools are withdrawn and it must answer, bounding a turn to three LLM calls in the worst case; the prompt also tells the model not to re-search just to double-check.
- **Web Search Relevance Filter**: `search_web` results are reranked by embedding similarity to the user's question (`WEB_SEARCH_MIN_RELEVANCE`, `WEB_SEARCH_RELEVANCE_RATIO`) and a configurable domain blocklist (`WEB_SEARCH_BLOCKED_DOMAINS`) drops generic pages such as encyclopedia entries; the tool schema now asks the model for specific, place- and entity-qualified queries. Reranking is best-effort and falls back to the engine order when embedding is unavailable.
- **Parallel First Search Round**: The first LLM call now uses `tool_choice=required` instead of pinning `search_knowledge`, so the model decides in one shot which searches a turn needs; `search_knowledge` is added automatically with the raw user message when it is left out, and knowledge base and `search_web` run in the same parallel round. A question that needs the web now costs two LLM calls instead of three. `FORCED_TOOL_MAX_TOKENS` defaults to 400 to leave room for several calls.
- **Strict Two-Pass Chat Turn**: An ordinary user turn now always searches the knowledge base before answering. The first LLM call pins `tool_choice` to `search_knowledge` (`CHAT_FORCE_KNOWLEDGE_SEARCH`, default on, applied only when that tool is registered for the persona/project and never over a slash-command forced tool), and later calls drop `search_knowledge` while keeping every other tool such as `search_web` (`CHAT_ANSWER_PASS_EXCLUDES_KNOWLEDGE_SEARCH`, default on), so the model can neither answer from memory nor re-query the knowledge base, yet can still reach the web for questions like the weather; an empty provider reply is nudged once before failing. Streaming moved to the answering call, which is the pass that produces the long text; a provider that ignores the forced `tool_choice` and returns text has that text accepted as the answer with a warning instead of looping. Turning both settings off restores the previous `tool_choice=auto` multi-round behaviour.
- **Bounded Crawler DNS Resolution**: Added a five-second DNS lookup timeout before crawler provider requests so slow or stalled resolution cannot hold a fetch indefinitely.
- **Security Audit Remediation**: Hardened project authorization for dreaming and session mutations, bound gateway job visibility to submitting accounts, and required administrator access for DLQ inspection. Memory deletion now rejects LanceQL expression syntax; API-managed skills cannot replace executable `main.py` files. Added private-IP SSRF blocking to crawler and 2md URL reads, strict TTS provider/voice authorization, fail-closed embedding authentication, 32-byte JWT secret enforcement, bounded QA image reads, canonical workspace containment, and trust-boundary checks for LLM tool output and long-term memory writes. Removed hardcoded browser WebSocket credentials, wildcard credentialed CORS, Grafana anonymous/default access, widget wildcard messaging, and unsandboxed graph iframe execution.
- **Admin UI Consistency**: Standardized semantic colors, shared page headings, buttons, and inputs across the Admin portal without changing their behavior.
- **Production Admin Runtime**: Changed the default Compose stack and Docker Hub workflow to build the Admin `runner` stage instead of the Vite development stage. The runner now retains the shared HTTPS nginx edge routes while serving the pre-built Admin bundle; the worktree override alone selects Vite/HMR.
- **Memory Listing Runtime Dependency**: Replaced the Admin memory list's implicit pandas conversion with LanceDB's native Arrow records, preserving date ordering, pagination, and vector exclusion without requiring pandas in the production Brain API image.
- **Single-File Default Deployment**: Removed the registry-only Compose override. A fresh host now uses `docker compose up -d --remove-orphans`, defaults to the public `tbdavid2019` namespace, and falls back to Dockerfile builds only when a published image is unavailable.
- **Temporary Credential Redaction**: Temporary accounts previously stored the one-time password itself as the account `username`, so it surfaced in audit-visible fields. The accounts are now renamed to `tmp-<id>`. A first attempt at this migration silently applied to zero rows — it compared the case-preserving locator against the lowercased `username_normalized` — and is superseded by a corrected migration.
- **Retired `/api/gpu/*` Prefix**: Shared inference now lives at `/api/embedding` and `/api/vlm`. The prefix described a deployment detail rather than the interface, and inference services do not necessarily run on a GPU. `POST /api/embedding/embed` still resolves for consumers already wired to it.
- **AnyDoc Document Conversion**: Adopted Firecrawl AnyDoc's Rust-backed Python binding for fallback and direct conversion while retaining the existing pdf-inspector and Docling ingestion stages.
- **Keyless Avatar SDK**: Changed the public Avatar JavaScript SDK to accept host-provided complete audio or 16 kHz mono PCM chunks through `playAudio()` and `pushPcm()`. Removed the public Embed backend API, API-key middleware/store/CLI, and Embed Keys admin page while preserving internal frontend API, WebSocket, and TTS routes.
- **`.env` Consolidation**: Merged `backend/.env`, `brain/.env`, and the root `.env` into a single root-level `.env` / `.env.example`. `docker-compose.yml`'s `api` and `backend` services now both use `env_file: ./.env`, so deployment only requires maintaining one file (`cp .env.example .env`) instead of three. Along the way, removed a duplicated dead-write `TTS_GEMINI_URL` entry, backfilled missing documented settings (Docling, PDF Inspector/Repair, Avatar uploads, TTS Cache) that existed in `config.py` but not in any example file, and deleted `infra/.env.example` / `backend/index-tts-vllm/.env.example` (never actually wired to an `env_file:` — those values were always sourced via compose `${VAR}` interpolation from the root `.env`).

## [0.10.0] - 2026-05-25

### Added
- **Vue 3 Migration**: Migrated the frontend application (`frontend/app`) from React to Vue 3 for improved reactivity, performance, and structure.
- **Privacy Filter & Egress Scanning**: Added a privacy filter service featuring real-time egress scanning, CPU/CUDA fallback support, and warning event notification for PII detection in both user inputs and LLM responses.
- **Prometheus & Grafana Observability**: Integrated Prometheus and Grafana for monitoring backend services, performance tracking, and health status dashboard.
- **Public Iframe Embed Channel**: Implemented API-key protected routes (`/embed/*`, `/api/embed/*`, `/ws/embed/*`), the `<vman-avatar>` loader, and administrative key management.
- **Gemini Live Upgrades**: Added support for Gemini thought signatures, multi-query tool search citations, improved tool grounding, and display of tool call duration/references in message metadata.
- **Active Memory Recall**: Integrated active memory recall to enhance contextual retrieval.
- **Multi-Provider TTS Support**: Hardened avatar reconnect UX, extracted the settings modal, and added multi-provider TTS backup configurations.

### Removed
- **VibeVoice TTS**: Fully removed the VibeVoice provider, its dedicated Docker service, adapters, and configuration files, prioritizing the fallback chain `IndexTTS → GCP → AWS → Edge-TTS`.
- **Embed Page**: Removed the legacy standalone Embed page in favor of the new iframe embed channel.

### Changed / Refactored
- **TTS Synthesis Relocation**: Moved TTS synthesis from the backend relay directly to the frontend stream endpoint.
- **Streamlined Chat API**: Replaced the streaming chat API with a synchronous response endpoint and streaming chat turn with first-iteration dispatch.
- **Rem-Based Frontend Sizing**: Converted all layout dimensions from pixel (`px`) to relative (`rem`) units in the frontend to enhance responsive design.
- **Helper Centralization**: Refactored and centralized admin API helpers for cleaner codebase organization.
- **Backend Dockerfiles**: `brain/api` and `backend` Dockerfiles use `uv` with BuildKit cache mounts for dependency installs, significantly reducing rebuild time.

### Fixed
- **UI Recovery & Reconnection**: Fixed admin UI recovery issues after backend reconnection and added user recovery controls.
- **Initialization & Configuration**: Fixed `docling` converter cache initialization and set the `Asia/Taipei` timezone in service Dockerfiles.

## [0.9.1] - 2026-04-22

### Added
- **Forced Tool Call Routing**: Brain pipeline can now force a specific skill invocation per request, with dynamic skill registry sync so newly registered skills become callable without restart (`pipeline.py`, `tool_registry.py`, `skill_manager.py`).
- **Direct Chat Route**: Pure conversational messages bypass tool-instruction assembly, reducing prompt size and latency when no skills are needed (`pipeline.py`, `prompt_builder.py`).
- **Chat Action Request Flow**: New end-to-end "action request" flow — Brain emits structured action proposals via `tools/actions.py`; admin UI renders an `ActionRequestCard` so the operator can approve/deny tool calls inline (`chat.ts`, `ChatInput.tsx`, `useChatSession.ts`).
- **Knowledge Graph (graphify)**: New `graphify` skill + graph HTTP endpoints; admin knowledge base gains a "Graph" tab for graph visualisation alongside files/records (`brain/skills/graphify/`, `routes/knowledge.py`, `pages/KnowledgeBase.tsx`).
- **Admin Slash Autocomplete**: `/skill` dropdown in chat input with live skill filtering and keyboard navigation (`ChatInput.tsx`, `SlashDropdown.tsx`, `useSlashAutocomplete.ts`).
- **Chat Input History**: Up/Down arrow keys cycle through previous user messages (seeded from the current session), with history taking priority even when a slash command is visible in the field (`useInputHistory.ts`, `ChatInput.tsx`).
- **Unified Admin Navigation**: New `NavigationContext` centralising route state across `AppSidebar` / `ChatSidebar` / pages, plus redesigned design-token palette.
- **Idle Timeout Management**: Backend introduces idle-timeout handling for live sessions; frontend upgraded to `nanoid` v5.
- **Brain Route Modularisation**: Brain HTTP surface split into dedicated modules under `brain/api/routes/` (chat / knowledge / tools / internal routes), replacing the previous monolithic router.

### Changed
- **Admin Frontend Redesign**: Overhauled design tokens in `tailwind.config.js` + `index.css`; all semantic colours now expose RGB channels so Tailwind opacity modifiers (`bg-primary/20`, etc.) render correctly. Sidebar, TTS controls, and skill management views updated to the new tokens.
- **TTS Controls Relocation**: Moved TTS provider/voice controls into the chat input bar; `identity.emoji` field removed from persona schema.
- **Brain API Dockerfile**: Rewritten as multi-stage `builder → runner` with `uv` dependency caching, significantly reducing image size and rebuild time.
- **SSE Finalisation Ordering**: `server.done` SSE event is now emitted before `finalize()` completes, preventing client races that blocked the live relay.

### Added (earlier)
- **Live Voice WebSocket Pipeline**: Implemented an end-to-end real-time voice interaction loop connecting frontend ASR, backend orchestration, and Brain streaming.
- **Frontend Live Runtime**: Created a new interactive runtime in `frontend/app` with VAD (Voice Activity Detection), automatic turn detection, and audio-driven lip-sync.
- **Smart Interruption (Barge-in)**: Added a `Guard Agent` powered interruption mechanism allowing users to interrupt the avatar mid-sentence with low-latency reflexes.
- **Handshake & Protocol**: Formalized the live control protocol with `client_init`, `set_lip_sync_mode`, and `server_stop_audio` events.
- **Audio Playback Queue**: Implemented a robust frontend queue for seamless decoding and playback of streamed audio chunks.
- **Microsoft VibeVoice Integration**: Replaced `IndexTTS` with the `VibeVoice` family (0.5B Real-time and 1.5B High-quality) for low-latency, emotional, and Taiwanese-accented speech synthesis.
- **Standalone TTS Service**: Decoupled TTS from the backend container into a dedicated `vibevoice-serve` Docker service, improving resource isolation and GPU scheduling.
- **Standalone Redis Service**: Offloaded the internal Redis server from the backend container to a standalone `redis:7-alpine` service.
- **Taiwanese Accent Support**: Introduced "Reference Voice" (Zero-shot) cloning logic, using 5-10s Taiwanese audio prompts to achieve authentic regional prosody.
- **Gemini Live Full-Duplex**: Brain-owned `GeminiLiveSession` with persistent Gemini WebSocket, audio relay, tool calling, auto-reconnect with exponential backoff, and keepalive. Backend acts as a stateless relay between frontend and Brain.
- **Admin Chat Live Mode**: Text/Live mode toggle in admin Chat page. Live mode connects via WebSocket to backend `/ws/{client_id}`, supports microphone audio capture (MediaRecorder → PCM16 → `client_audio_chunk`), real-time audio playback queue, live transcript with chat bubbles, and `user_speak` text input.
- **Admin Custom Select Component**: Replaced native `<select>` dropdowns with a custom `Select` component featuring keyboard navigation, dropUp detection, and click-outside close.
- **Admin Unified Scrollbar Styling**: Global thin scrollbar CSS for all scrollable areas.
- **Live Voice Source Toggle**: Admin Chat Live mode voice source selector (Gemini 語音 / 自訂語音). Frontend sends `voice_source` in `client_init` capabilities; backend `BrainLiveRelay` either passes through Gemini native audio or intercepts text to synthesize via `TTSRouterService`.
- **Live Session Continuity**: Text-mode chat history carries over to Live mode — frontend passes `chatSessionId` through `client_init → relay_init`, Brain loads the last 20 messages into Gemini system instruction on connect.
- **Live System Instruction Injection**: Brain composes IDENTITY + SOUL + chat history + top-5 memory records into `system_instruction` for Gemini Live sessions, enabling persona-aware real-time conversations.
- **Live Conversation Persistence**: Brain `internal_live_bridge` persists user and assistant turns to `SessionStore` via `_persisting_event_sink`, so Live conversations appear in session history.
- **Gemini Live Tool Calling**: `save_memory` and `get_chat_history` tools available during Live sessions for on-the-fly memory writes and history retrieval.
- **Docling Integration Config**: Added `docling_serve_url`, `docling_timeout_ms`, `docling_api_key`, and `docling_fallback_to_anydoc` settings to `TTSRouterConfig`.

### Removed
- **Index-TTS (vLLM)**: Excised the legacy `index-tts-vllm` directory and all related code/dependencies, significantly reducing the backend container's footprint and complexity.

### Changed
- **Backend Container Slimming**: Switched the `backend` base image from `vllm/vllm-openai` to `python:3.11-slim`, focusing on business logic rather than heavy model inference.
- **TTS Fallback Strategy**: Updated `TTSRouterService` to prioritize `VibeVoice-0.5B` -> `VibeVoice-1.5B` -> `Edge-TTS`.
- **Infrastructure Overhaul**: Refactored `docker-compose.yml` and `start-backend-container.sh` to support the new decoupled microservice architecture.
- **LiveVoicePipeline TTS Router**: Switched from `VibeVoiceAdapter` to `TTSRouterService` for TTS synthesis in the live voice pipeline.
- **Gemini Live API Format**: Updated `realtimeInput` from `mediaChunks[]` array to `audio` object; `clientContent.turnComplete` changed to `realtimeInput.audioStreamEnd`.
- **Protocol Schema Alignment**: `server_stream_chunk` now allows empty `text`/`audio_base64` fields. `server_init_ack` status normalized to `"ok"`. `server_error` requires `timestamp` and uppercase `error_code` values.
- **Live Status Bar UI**: Moved Live mode connection status panel to a sticky position above the scroll area, no longer scrolls with messages.
- **Admin Auth Token Removed**: Removed hardcoded `ADMIN_AUTH_TOKEN` from frontend; auth flow simplified.

### Fixed
- **Brain Timezone**: Added `tzdata` to Brain container requirements to fix `ZoneInfo("Asia/Taipei")` failure in Docker.
- **Brain Module Imports**: Fixed `_build_memory_context` and `_save_memory` to use correct module paths (`memory.retrieval`, `memory.embedder`) instead of non-existent `embedding.*` package.
- **Live `server_error` Protocol**: Added missing `timestamp` field and fixed lowercase `"internal_error"` to uppercase `"INTERNAL_ERROR"` in backend relay error events.
- **Live Mode Scroll**: Fixed Live mode not scrolling to bottom on mode switch; uses instant scroll on first enter, smooth scroll for subsequent messages.
- **Voice Source Switch Stability**: Fixed `voiceSource` toggle clearing live messages by using a one-shot seed gate (`seededRef`) and reconnect generation counter to distinguish intentional vs unexpected disconnects.
- **Gemini Live Timeout Logging**: Downgraded expected 1008 policy violation (session timeout) from ERROR to WARNING level.

## [0.9.0] - 2026-03-26

### Added
- **Admin Web Light Mode**: Implemented a comprehensive theme-aware system supporting both Light and Dark modes.
- **Persistent Theming**: Integrated `ThemeContext` with `localStorage` to preserve user theme preferences across sessions.
- **Adaptive UI Refactor**: Systematic update of all administrative pages (Chat, Knowledge, Memory, Tools, Health, etc.) and shared components (Modals, Alerts, FileTrees) with theme-aware Tailwind classes.
- **Theme Toggle**: Added a theme switcher UI in the sidebar footer for seamless mode transitions.

## [0.8.0] - 2026-03-25

### Added
- **Knowledge Base Admin Panel**: Implemented a modular, IDE-inspired interface for managing knowledge base documents.
- **Recursive KB Explorer**: New `FilesTree` component supporting deep nested folder structures and visual LanceDB sync status.
- **Universal Markdown Editor**: Split-pane markdown editor with live preview and automated background re-indexing flow.
- **Admin Navigation**: Integrated the "KB Admin" tab into the primary sidebar of the administration console.

## [0.7.0] - 2026-03-25

### Added
- **Nervous System Architecture**: Implemented the core architecture as defined in `docs/superpowers/specs/2026-03-25-vman-nervous-system-architecture.md`.
- **WebSocket Session Manager**: `backend/app/session_manager.py` now manages active connections and associated tasks.
- **Guard Agent & Interrupt Sequence**: `backend/app/guard_agent.py` provides fast-reflex interruption logic based on `asyncio.Task.cancel()`.
- **Punctuation Chunker**: `backend/app/utils/chunker.py` splits text streams for natural TTS pacing.
- **Frontend ASR & State Machine**: `frontend/app/src/services/asr.ts` and `frontend/app/src/store/avatarState.ts` manage speech input and avatar states.
- **Frontend WebSocket Integration**: `frontend/app/src/services/websocket.ts` handles communication with the backend.
- **AnyDoc Integration Test**: Added `backend/tests/ingestion/test_anydoc.py` to validate native document conversion.
- **Unit Tests**: Added comprehensive tests for `SessionManager`, `PunctuationChunker`, and `GuardAgent`.

### Changed
- Refactored `Session` (backend) to be a pure Python class, removing `pydantic` dependency to improve startup time.

### Fixed
- Corrected `PunctuationChunker` regex to properly handle spaces after punctuation.

### Developer Note (Next Steps)
- **Brain Integration**: The Brain cognitive core (including `SkillManager`, `ToolRegistry`, and `MessageEnvelope`) has been perfectly implemented by the team previously (see v0.5.0). The final integration step is to handle the `user_speak` event in `backend/app/main.py`: call the existing Brain streaming API, and feed the generated text into the newly written `TTSRouter` and `PunctuationChunker` pipeline to complete the Nervous System loop.

## [0.6.0] - 2026-03-23

### Added
- **Pluggable Frontend Rendering**: Established a strict threefold architecture (`Wav2Lip`, `DINet`, `WebGL`) for virtual avatar lip-sync, formally deprecating the legacy fallback methods.
- **WebGL CSR Strategy**: Introduced `WebGLStrategy` supporting `.ktx2` high-compression texture states for zero-server-cost kiosk environments.
- **Edge ONNX Strategies**: Formalized lifecycle mocks for `Wav2LipStrategy` (WebGPU) and `DinetStrategy` (CPU/WebGL HTTP fallback) for client-side AI inference.
- **Precise Video Sync**: Enhanced `VideoSyncManager` strictly binding WebAudio `AudioContext.currentTime` with HTMLVideoElement, guaranteeing zero frame drift.

### Changed
- Refactored `LipSyncManager` to act purely as an orchestrator, removing obsolete Viseme payloads from WebSocket event streams.
- Dropped legacy Canvas BBox overlay and Viseme-based interpolation in favor of unified `IRenderingStrategy` interface.

## [0.5.0] - 2026-03-21

### Added
- **Brain Gateway Integration**: Backend reverse-proxies all `/brain/*` and `/api/*` traffic to brain service, with OpenAPI schema auto-merge.
- **Frontend Unified Routing**: Admin frontend traffic routed through backend gateway; removed standalone nginx proxy.
- **Index-TTS Background Init**: Model loads in background thread; port binds immediately, health returns 503 until ready.
- **Stale CUDA Lock Cleanup**: Detect and remove leftover `build/lock` from killed containers; pre-compile BigVGAN CUDA kernels on main thread.
- **Aggregated Health Check**: `/healthz` probes all downstream services (brain, index-tts, redis) in parallel and returns unified status with `ok`/`degraded`.
- **TTS Chat Playback**: Speaker button on assistant messages with auto-play on new replies, abort support, and Object URL lifecycle management.
- **Brain Tool Loop**: `agent_loop.py` with `ToolRegistry`, `ToolExecutor`, and `SkillManager` — model can call tools, observe results, and continue reasoning.
- **Brain Provider Fallback**: `ProviderRouter` with `KeyPool` round-robin, per-key cooldown, and `FallbackChain` for cross-provider/model failover.
- **Brain Session Persistence**: SQLite-backed `SessionStore` replacing in-process memory; sessions survive container restarts.
- **Brain Memory Governance**: `memory_governance.py` with importance scoring for memory lifecycle management.
- **Brain Input Guardrails**: `guardrails.py` for input validation and content filtering.
- **Brain Observability**: `observability.py` structured logging and routing metrics.
- **Brain Message Protocol**: `MessageEnvelope` with trace ID, channel, and type standardization; `ProtocolEvents` for SSE.
- **Brain Multi-Persona**: `personas.py` with persona-aware retrieval and isolation.
- **Brain Retrieval Service**: Unified `retrieval_service.py` coordinating knowledge + memory search with configurable strategy.
- **Internal Enrich Endpoint**: `/internal/enrich` for gateway-to-brain document forwarding.
- **Multi-GPU Architecture**: `TORCH_CUDA_ARCH_LIST=8.6;8.9` supporting both RTX A4000 (Ampere) and RTX 4090 (Ada Lovelace).
- **434 unit tests** across backend (175) and brain (259).

### Changed
- Consolidated single-container backend with embedded Index-TTS and Redis.
- Removed redundant sub-project `docker-compose.yml` files (backend, brain).
- Extracted WebSocket headers into shared nginx snippet.
- Health payload simplified: removed redundant top-level `redis`/`temp_storage` fields in favor of `dependencies` object.
- TTS endpoints deduplicated via shared `_tts_response()` helper; cached `speaker.json` reads.
- `_fetch_brain_openapi` reuses shared `httpx.AsyncClient` instead of creating per-call clients.

## [0.4.0] - 2026-03-19

### Added
- **Unified Python Backend**: Consolidated TS gateway, Node server, and TTS router into a single FastAPI service on port 8200.
- **Image Ingestion**: Vision LLM description (OpenAI GPT-4o compatible) with pytesseract OCR fallback (chi_tra+eng).
- **Audio Ingestion**: Whisper API transcription (OpenAI or local binary) with graceful error handling.
- **Video Ingestion**: ffmpeg frame extraction (1 fps) with per-frame Vision LLM description.
- **MediaDispatcher**: MIME-based routing with configurable timeout (`asyncio.wait_for`).
- **Forward-to-Brain**: Fire-and-forget POST to brain `/internal/enrich` endpoint via httpx.
- **Dead-Letter Queue (DLQ)**: Failed jobs pushed to Redis list with `GET /admin/queue/dlq` endpoint.
- **Plugin System (Python)**: `IPlugin` protocol with singleton lifecycle management.
  - **CameraLive**: Periodic HTTP snapshot + Vision LLM description, per-session asyncio task management.
  - **ApiTool**: YAML registry with `${ENV_VAR}` interpolation, sliding-window rate limiting, multi-auth support.
  - **WebCrawler**: readability-lxml extraction, domain blocking, in-memory TTL cache.
- **156 unit tests** covering all new and existing modules.

### Changed
- Removed old TS `backend/gateway/`, `backend/server/`, consolidated `backend/tts_router/` into `backend/app/`.
- Updated `Dockerfile` to include `tesseract-ocr` and `tesseract-ocr-chi-tra`.
- Updated `docker-compose.yml` (root and backend) with new env vars for Vision LLM, Whisper, Camera, ApiTool, Crawler, Brain URL.
- Updated `nginx/default.conf` routing from `tts-router` to `backend` with `/upload` and `/health` locations.
- Removed unused `rag_top_k` from brain config; removed dead `summarize_supporting_context` from brain reflection.
- Fixed contracts CI workflow by removing missing `brain/web/` steps.

## [0.3.0] - 2026-03-18

### Added
- **RAG v2 Architecture**: Transitioned to a multi-modal, hybrid search architecture.
- **AnyDoc Integration**: Support for PDF, DOCX, XLSX, and more through the document ingestion service.
- **Header-Based Chunker**: Semantic splitting based on Markdown headers (H1-H3).
- **Hybrid Search (BM25)**: Enabled combined vector and text search in LanceDB.
- **Backend Gateway**: New independent microservice handling multi-modal media ingestion (images, audio, video) to offload the core backend.
- **Gateway Task Queue**: Implemented BullMQ/Redis for asynchronous request scheduling and media preprocessing.
- **Gateway Plugin System**: Introduced `Camera Live` (RTSP/WebRTC), `API Tool` (REST proxying), and `Web Crawler` (headless extraction) plugins.
- **Device-Adaptive Lip-Sync**: Introduced `LipSyncManager` supporting DINet (low-end devices, 39 Mflops) and Wav2Lip (high-end devices with GPU) AI lip-sync.
- **Video Sync Manager**: Built high-precision audio-video synchronization tying Web Audio to `HTMLVideoElement.currentTime`.
- **Canvas Feathering**: Added radial gradient masking for seamless mouth overlay blending.

### Changed
- Moved root specification files to the `docs/` directory for better organization.
- Extracted frontend codebase from `brain/web` to an independent root `frontend/` directory.
- Removed residual `web` and proxy configurations from `brain/docker-compose.yml`.
- Updated `readme.md` with RAG v2 highlights, document map, and new adaptive lip-sync architecture.

## [0.2.0] - 2026-03-18

### Added
- **Brain Skills System**: Implementation of a modular plugin system in `brain/skills/`. Supports dynamic tool registration with namespacing.
- **LLM Failover (DR Mode)**: Formalized `fallback_chain` logic for cross-provider and cross-model failover (Gemini, OpenAI, Groq).
- **ToolRegistry Enhancements**: Support for dynamic skill-provided tools.
- **Example Skill**: Added a `weather` skill at `brain/skills/weather/` for verification.
- **Unit Testing**: Added `test_skills.py` for verifying the skill management system.

### Changed
- Updated `03_BRAIN_SPEC.md` to include Skills System and Failover specifications.
- Updated `README.md` with the latest architecture highlights.
- Adjusted `requirements.txt` to include `PyYAML` for skill manifest parsing.

## [0.1.0] - 2026-03-11

### Added
- Initial architecture specifications (00-03).
- Basic project structure for Backend, Brain, and Frontend.
- core-protocol defined for WebSocket JSON communication.
- Initial project plan (08_PROJECT_PLAN_2MONTH.md).
