# Changelog

## [Unreleased]

### Added
- **知識庫文件批次操作**：檔案樹「多選」後可勾選多個檔案（資料夾一次勾底下全部），批次移動到資料夾、設定語言或刪除。逐檔呼叫既有 API、不新增端點；顯示進度，部分失敗照樣做完並列出原因（例如目標已有同名檔），失敗的保持勾選可重試。
- **前台訪客模式與迎賓體驗**（UX 審查 2026-10-06）：網址 `?kiosk=1` 藏起設定與帳號列、登出（標題連點三下可暫時叫出）、先顯示「點一下開始對話」解鎖音訊並開始收音；標題改成角色名稱加狀態（在線／聆聽中／思考中／說話中），不再是「openVman 控制台」；收音時輸入框右側有即時音量條（另開一條麥克風串流只量音量）；還沒開口前在輸入框上方列出快速問答的推薦問題（各主題輪流取題、最多 4 題，手機 2 題）；訪客模式閒置 2 分鐘清空對話、關麥克風、回到開始畫面，下一位來賓看不到上一個人的對話；手機點輸入框時舞台縮成一小條讓出位置給鍵盤（viewport 加 `interactive-widget=resizes-content`）。
- **後台聊天「修正成 QA」**：AI 回答的操作列可以把這一輪的問答改好後直接存進問答節點，沿用知識庫手動輸入問答的 API 與檔案格式，存完自動重建索引；同題只改答案，預設不出現在前台快速問題按鈕。
- **後台語音辨識分頁改成完整的測試台**：可以編輯專案詞表（`ASR_PROMPT.md`，顯示幾個詞、幾條誤聽對照）；勾語言分流；批次試辨識一次勾多個引擎、同一段音檔同時送出比較，輸入有 VAD 收音（講完一句自動送出，可連續講）與上傳，顯示實際引擎、耗時、套用的分流與詞表、台語判斷，填參考文字就算錯字率（跟 voice_e2e 同算法），最近 5 段可回放；新增串流試聽，邊講邊出字。後端：`/api/v1/asr/preview` 多收 `project_id`、`language_routes`，跟正式對話一樣套詞表與台語判斷（引擎照選的跑），回傳 `glossary`、`language_check`、`language_routes`；`/api/v1/asr/stream` 多一個只有管理員能用的 `engine` 參數。原本錄音鈕用到不存在的 `btn-secondary` 樣式，一起改掉。
- 講話中插話的分類端點（預設不用）：新增登入保護的 `POST /api/v1/voice/interrupt`（`{transcript, reply_text}` → `{action: "STOP" | "IGNORE"}`），先丟掉完整出現在回答裡的文字（當成喇叭回音），再交給既有 GuardAgent／Jev 判斷。前台串流辨識接好了，但開關 `INTERRUPT_WHILE_SPEAKING`（`useAvatarVoiceInput.ts`）預設關：回音過濾只擋完全相同的文字，辨識錯一個字就擋不住，現場喇叭與麥克風的回音消除還沒實測，開了可能讓虛擬人自己打斷自己。虛擬人出聲時所有引擎照舊停止收音。


### Fixed

- **後台錯誤訊息是「Request failed: 500」或整頁 HTML**：後端沒給說明時改依狀態碼講人話（例如 502／503／504「後端服務暫時連不上（可能正在重新部署），請等一分鐘再試」、409「資料剛被別人改過」），部署中 nginx 回的 HTML 錯誤頁不再原樣塞進訊息，欄位驗證錯誤（422）只列出是哪些欄位，連不上伺服器時說網路；後端給的中文說明照用。工具確認卡片與 TTS 試聽的錯誤也改用同一套。
- **前台聊天出錯時直接顯示「BRAIN_ERROR: HTTP 500」這類原文**：改成白話說明（例如「現在詢問的人比較多，請稍候再問一次」「網路連線中斷，請確認網路後再試」），全螢幕錯誤的標題也不再是錯誤碼；原始錯誤碼與訊息寫在瀏覽器 console。
- **OpenAI Whisper 的中文辨識結果是簡體**：其他引擎都轉繁體，只有 Whisper 原樣回傳。現在中文轉繁體；有日文假名就不轉（會把「学校」改成「學校」）。
- **後台試辨識上傳長檔時，R2T2 串流的定稿少了後半段、R2T2 批次多等 20 幾秒**：同一段音檔同時送到同一台的批次和串流會互相排隊；串流送完後只等 3 秒沒新定稿就收，排隊晚到的後幾句被截掉。全部引擎照樣同時送（跟正式環境多人同時用一樣；同一台同時收到批次和串流時，秒數含排隊時間），R2T2 串流改成等伺服器關線才收（它收到 EOS 一定回最後一則定稿再關，最多等 30 秒）；Gemini 不會自己關線，維持靜下來就收。上傳的檔案串流引擎改用 4 倍速送，不用乾等整段長度，秒數旁標「4 倍速送」；麥克風講的照真實速度送。串流引擎那一列辨識中會即時顯示目前聽到的字（已定稿加上講到一半的暫定字幕），定稿後換成最終結果。
- **R2T2 批次辨識也把西文、日文、韓文當中文解碼**：`/transcribe` 的 `language` 寫死 `Chinese`，跟串流同一個問題。現在 `transcribe()` 多收 `routes`，R2T2（`r2t2`、`r2t2-dev`）照專案生效的分流帶語言，規則與串流共用 `language_routes.r2t2_language`：只有一種語言帶該語言，多種語言帶 `zhen`，沒有分流或只有台語當華語（自動判斷可能把台語判成英文、葡萄牙文；串流原本沒有分流時送 `zhen`，一併改成華語）。非中文輸出不轉繁。兩台批次端點實測：指定語言時中英西日韓全對。聊天附件等沒有分流的批次辨識照舊當華語。
- **R2T2 dev 串流（`r2t2-dev-live`）經過前台一句都收不到**：辨識中會送一則空的 `{}`，backend 把沒有 `status` 的訊息當成失敗，整條連線斷掉、前台退回批次。現在沒有 `status` 的訊息當心跳略過，只有明確不是 `success` 才算失敗。
- **R2T2 串流把西文、日文、韓文都當中文解碼**：握手的 `language` 寫死 `Chinese`，R2T2 不會自己判斷語言，西文「bomba」被聽成「炸彈」、日韓夾進中文字。現在照這條連線的分流帶語言：只有一種語言時帶 `English`／`Spanish`／`Japanese`／`Korean`／`Chinese`，多種語言時送 `zhen` 讓 R2T2 自己判斷。非中文的輸出不再做簡轉繁（會把日文「学校」改成「學校」）。實測五種語言各 3 句，指定語言全對。多語言專案含西日韓時仍要另外決定語言來源。
- **鶴記dev 檢索時沒有圖譜擴充**：`scripts/project_mirror.py sync` 只複製了 `graphify-out/` 檔案，檢索用的 LanceDB `note_graph` 表沒帶過去，測試專案的檢索跟正式不一樣。現在 `sync` 一併複製、`check` 一併比對（差異顯示為 `lancedb:note_graph`）；鶴記dev 已重新同步。
- R2T2 串流實驗腳本 `scripts/experiments/r2t2/stream.py` 改讀 `.env` 的 `ASR_R2T2_SECRET_KEY`，跟正式設定同一個來源，不再在腳本裡另寫一份。
- **voice_e2e 跑完沒有刪掉測試對話**：刪對話要專案的編輯權限，測試帳號 voice-e2e-test 只有讀取，`/api/v1/sessions/batch-delete` 一直被 Backend 回 404，對話留在鶴記dev。用 `--user` 跑時改在 api 容器裡刪（跟簽 token 一樣進容器），`--token` 打遠端時照舊走 API。
- **合併補句時舊回答可能仍寫入 Brain**：可合併 HTTP 回合加入 `turn_id`／遞增 `turn_revision`，答案先暫存，前台完整接收目前版本後透過 `/api/v1/chat/accept` 確認，才原子寫入問題與回答並執行日誌／記憶更新。取消、被取代或未接收的答案不落庫；確認重試不重複寫入，下一輪等待上一輪確認以保留完整歷史。後台 Chat、外部 SDK 與未提供回合欄位的 API 維持既有流程。
- **`/api/v1/tts/stream` 指定 Edge 卻回 200 空音檔**：只要設了 IndexTTS 網址，這個端點不管指定哪家都先送 IndexTTS；IndexTTS 沒在跑時連上就斷，回空音檔。現在只有沒指定或指定 IndexTTS 才走它，VoxCPM 失敗也直接退到 Edge。前台 Edge 聲音本來走整段合成，不受影響；voice_e2e 的念回答步驟被影響。voice_e2e 念回答的秒數原本把回應當 wav 算，Edge 回 mp3 時記成 0，改用 ffprobe 讀實際長度。
- **一次問好幾件事時，英文提問被用中文回答、逐條列出查不到的項目，念到 50 秒**：fast 模式模型想再查資料被擋下時，程式補一句中文催促「手邊資料沒有的內容就說明查不到」，這句是模型最後讀到的話，蓋過了 system prompt 的回答語言與長度。現在催促訊息改成「查不到的部分合併成一句帶過，不要逐項說明」，後面再附一次這一輪的回答語言與長度。鶴記dev 同一批 36 題：英文最長 63 → 29 個單字、超過上限 1/12 → 0/12，Markdown 列點 1 → 0 題。
- **「¿Quién eres?」這類短西語問句被用中文回答**：兩個字以下的句子歸專案主要語言，但 ¿、¡、ñ 只有西語會用；現在有這些符號就判成西語。
- **部署時 Brain 重啟那半分鐘，台語分流被默默關掉**：Backend 查不到專案語言分流就退回「只有中文」，那段時間講台語都被當華語。現在查不到時沿用上次查到的設定（即使快取已過期）；只有從沒查到過的專案才退回中文。
- **簡轉繁出現「着」「裏」「爲」這類台灣不用的字形**：OpenCC 從 `s2t` 改成 `s2tw`（台灣標準字形），「自動着脫裝置」變成「自動著脫裝置」；不用 `s2twp`，它會把「軟件」這類詞改成台灣說法，等於改寫使用者講的話。影響小米、R2T2 的辨識結果與文件匯入。
- **快速問答選了英文、西語，按鈕還是中文；後台隱藏的主題前台照樣顯示**：介面文字（返回、關閉、載入中、空分類）改成跟著路徑上的語言分類（中文／English／Español，也認日本語、한국어）切換，還沒選語言時用中文；前台每一層都略過後台設成隱藏的主題。
- **停用的知識文件仍會經由知識圖譜被帶回答案**：向量檢索會略過後台停用的文件，但知識圖譜擴充直接按路徑抓相鄰文件的段落，沒有檢查是否停用。鶴記把英西問答改成快速問答後停用了原本的 `EVAK_QA.en.md`／`.es.md`，英文、西語提問的引用來源仍出現這兩份。現在圖譜擴充也略過停用的文件。
- 後台在取得帳號可用專案清單前不載入專案頁面或小助理；無權限使用 default 的帳號先回退至清單中的可用專案，再發出頁面請求，清單載入失敗可重試。沒有可用專案時阻擋專案頁面並保留專案／帳號管理入口。
- 從非預設專案的對話紀錄開啟 Chat 時保留專案參數；桌面、手機與對話側欄連結改由目前專案狀態產生，避免開新分頁時落到 default。
- 後台子頁改用可直達的固定路徑：語音辨識、知識圖譜、Avatar 背景／小助理、記憶新增、帳號建立／管理皆由 URL 決定畫面；保留舊 `?view=` 深連結並正規化。明確頁面網址省略專案時採用 default，避免保存偏好覆蓋分享網址；Chat 指定對話參數保留到 lazy 頁面消費。側欄使用帶專案與公開前綴的原生連結，支援新分頁開啟。

### Documentation

- 產品筆記實驗第三輪（`scripts/experiments/product-notes/round3/`，交辦 `TASK.md`，結論在 `REPORT.md` 第三輪一節）：加對照組 D（全部 15 篇筆記、不給篩選工具），沿用 12 題再加 8 題新題、每題每組跑 3 次。60 份回答（對／部分對／錯）：A 9／14／37、B 14／19／27、C（篩選工具）55／2／3、D 45／10／5；C 對 D 同題同次 14 勝 41 平 5 敗，贏在漏款、排序與必要限定。新題 C 87.5% 低於舊題 94.4%；C 有 2 次條件解析失敗，C／D 參考資料格式長度也不同，優勢不能全歸給篩選運算。重新生成的 15 篇筆記規格、正文與出處檢查 0 錯；篩選工具與第二輪逐位元組相同。鏡像檢查 exit 0、workspace／LanceDB 未變；正式程式與知識庫未變。
- R2T2 實驗報告的部署表改成新的主機與 dev 機，並補 10/05 晚的複測：正式路徑送 `Chinese`＋詞表，型號題 17/24、錯字率 8.6%；dev 機新版送 `zhen` 會逐句自動判斷語言，中英西日韓 15/15、型號題 18/24、台語不再判成葡萄牙文（錯字率 0.78），同語言連講時第二句起串流字幕幾乎等於定稿。
- R2T2 實驗報告加 2026-10-05 多語複測：指定語言時中英西日韓全對、不指定會把西日韓當中文；Gemini 3.5 transcribe 多語全對但型號只聽對 6/24（R2T2＋詞表 17～19/24）；另補同時多路、經過 backend 的串流驗證，以及台語真人 75 句（R2T2 錯字率 0.78～1.03，台語仍只能走 Breeze 0.36）。
- 新增 `scripts/experiments/product-notes/`：AI 產生 Obsidian 式產品筆記能不能改善跨產品選型問答。比現行檢索（A）、加最相近 3 篇筆記（B）、再加 frontmatter 篩選工具（C）。第一輪 EUS（型錄沒有逐型號規格）10 題：A 5／3／2、B 9／1／0、C 9／1／0（對／部分對／錯）；第二輪 EUB-M＋EDW 完整規格表 12 題：A 2／1／9、B 2／4／6、C 11／1／0。C 看得到全部規格、B 只有 3 篇，進步還不能全歸功於篩選；筆記數字 0 錯但正文有語意與出處錯誤，不能直接入庫。資料夾整理成單一 `README.md`／`TASK.md`／`REPORT.md`，各輪資料放 `round1/`、`round2/`。只動實驗目錄，正式程式與知識庫未變。
- `docs/plans/thin-entry-refactor.md`、`docs/plans/r2t2-streaming-asr.md` 標為 Done（已提交並部署，使用者授權結案）；`full-duplex-voice.md` 改為進行中，並列入 `docs/README.md`。
- 新增 `docs/plans/full-duplex-voice.md`（Draft）：語音對話不再一問一答的評估。現況是虛擬人思考與講話時麥克風寫死關閉、新的一句取代舊的；計畫分兩階段：思考中補一句合併回答（含 Brain 接收確認後落庫），講話中插話（需先在現場實測瀏覽器回音消除）。
- 供應鏈報告恢復 Azure、D-ID、HeyGen 真人方案說明，保留遠端算圖與費用差異；依本次調查補充 MatesX／DHLiveMini2 最符合目前真人效果、本地運算與成本需求的結論。

- 供應鏈報告全文改用直接中文，真人比較表只列候選方案，分開列出「建立人物需要的素材」與「說話時怎麼對嘴」。

- 供應鏈報告將 DHLiveMini2 列為真人 Avatar 核心替換 P0；修正 three-vrm 的功能等效判斷，新增真人串流／自架商業與寫實 3D 路線比較，保留外部 TTS、素材重建與部署驗收邊界。

- 補齊後台 Canonical Routes 與子頁直達、網址正規化與部署行為說明，更新前端規格中的早期路由描述。
- 新增前台費茨法則評估與紅色供應鏈替代方案調查；本次維持前台與供應鏈程式碼現狀。

### Reliability

- **R2T2 dev 引擎**：新增可授權的 `r2t2-dev`（批次）與 `r2t2-dev-live`（串流），設定 `ASR_R2T2_DEV_URL`、`ASR_R2T2_DEV_STREAM_URL`、`ASR_R2T2_DEV_SECRET_KEY`。帳號自己選了才用，失敗不換台，也不排進其他引擎的備援順序；批次只等 `ASR_R2T2_DEV_TIMEOUT_SECONDS`（預設 20 秒），等不到交給下一家引擎。
- **VoxCPM 推論 worker 死掉時，每句都等 120 秒才退到 Edge**：VoxCPM 的 health 照回 ok，openVman 每次合成都等滿 120 秒逾時才退到 Edge（2026-10-01 持續約 7 小時）。現在 VoxCPM adapter 合成前先查 `/api/v1/health`（最多等 2 秒、結果快取 10 秒），回 503 或連不上就立刻失敗退到下一家；health 沒有 worker 欄位時回 200 就照常合成。
- 專案詞表缺失、讀取失敗或編碼錯誤時不再中斷對話；快取改用奈秒時間、大小與檔案身分，提示以跳脫的 `<glossary>` 標記為參考資料。
- 串流辨識啟動加入世代隔離與 ready 逾時；停止期間才取得的麥克風立即釋放，重複啟動共用同一次收音。停止後最多保留 5 秒接最後定稿，重新啟動或卸載會清理舊連線。
- 回應攜帶自身語言上下文，獨立視覺回答不再繼承上一句台語的 VoxCPM 分流；補上華語、打字及過期回應的行為測試。
- 後端 ASR 串流離開前等待雙向工作取消完成，接收工作例外會回報前端以啟動備援。
- 修正檢索門檻實驗的結論邊界，補回語音授權與 VAD 部署限制。

### Changed

- **後台試辨識不用重傳、也能比串流和瀏覽器辨識**：音檔留在頁面上，之後再勾的引擎直接拿畫面上的幾段（最多 5 段）去跑，取消勾選只是隱藏、勾回來不重跑；每段有「重跑」，改了分流或詞表可以用同一段再比。Gemini Live、R2T2 串流也能勾：同一段音檔照真實速度送進 `/api/v1/asr/stream` 取定稿，秒數是講完到定稿（4 倍速送時文字一樣，但 R2T2 要追積壓、時間多 2～4 秒，所以不加速）。瀏覽器內建辨識只能聽麥克風，按「開始講話」時跟 VAD 一起聽，每段歸給 VAD 切出的那一句；上傳的音檔與重跑時標示不能用。`GET /api/v1/asr/engines` 多回 `stream`（設定齊全的串流引擎）。
- **R2T2 主機與 dev 機對調**：`r2t2`／`r2t2-live` 與 `r2t2-dev`／`r2t2-dev-live` 對應的機器互換，只改部署設定（`ASR_R2T2_*`、`ASR_R2T2_DEV_*`）。引擎 id 與授權不變，已授權 `r2t2-live` 的帳號（含 80 個臨時帳號）之後都送新的主機。後台與前台的引擎說明、`.env.example`、README、Backend 規格與實驗腳本的變數對應一起改。
- **後台語音頁搬到 `/admin/voice`**：TTS 試聽 `/admin/voice`、語音辨識 `/admin/voice/asr`（原本語音辨識掛在 `/admin/tts/asr` 底下）。舊的 `/admin/tts`、`/admin/tts/asr` 不轉址；內部頁籤 key 由 `Tts` 改為 `Voice`。
- **後台試辨識同時送給勾選的引擎**：原本一家一家依序送，最慢的那家要等前面都回來才開始。每家是不同機器，一家各送一句不會互相排隊，耗時照舊由後端各自量。收音一律走 VAD（講完一句自動送出，可以連續講），拿掉「錄一段」與另外的「自動斷句」開關；上傳音檔保留。
- **後台試辨識只列設定齊全的引擎**：新增管理員用的 `GET /api/v1/asr/engines`（`{"engines": [...]}`，照 fallback 順序），沒設定網址或金鑰的引擎（例如已停用的小米）不再出現；原本選了會被備援接走，看起來像它辨識的。
- **共用 VAD 移除 `per-utterance` 模式與 `commitMode` 選項**：原本給前台用（講完一句就關麥克風），前台改連續收音後已沒有呼叫端。`VadRecognizer`／`createSpeechController` 一律連續收音，雜音轉不出字時安靜略過；admin 三個呼叫端拿掉 `commitMode: "continuous"`。
- Brain `SessionStore` 寫入訊息、偵測語言、裁掉舊訊息抽成共用函式，`append_message` 與合併回合的 `accept_chat_turn` 不再各寫一份。
- **語音打斷改由 Jev 判斷規則判不出的長句（預設開）**：`JEV_INTERRUPT_ENABLED` 預設改 true。自寫 30 題規則 23/30、Jev 29/30，附和、對旁人說話不再誤停；只有規則判不出的那段長句多等最多 0.6 秒，沒有 `TYPESAFE_API_KEY`、失敗或逾時都維持中斷。
- **移除 A2A 的 Jev 預先過濾**：`A2A_JEV_PREFILTER_ENABLED`、`A2A_JEV_NO_REPLY_THRESHOLD` 刪掉；正式環境 A2A 沒開（佇列資料庫從未建立），預先過濾也從未啟用。A2A 本身不變，要不要回仍由 Brain 決定。
- **Jev 每次呼叫都記進用量**：記憶寫入把關、語言背景校正、串流定稿判斷、召回篩選共用的 `core/jev_client.jev_nouls` 每次呼叫（成功、失敗、逾時都算）記一筆 `provider=typesafe`、`kind=jev_<用途>`，附 token 數與 `raw.status`。原本只有影子觀測會記，正式環境又看不到 info log，數不出各功能每天打幾次。
- **移除 Jev 影子觀測與知識庫段落 Jev 篩選**：兩者預設關閉、正式環境從未開啟，影子還會把對話送到外部。刪掉 `core/jev_shadow.py`、`_jev_screen` 與 `JEV_SHADOW_ENABLED`／`_SAMPLE_RATE`／`_TIMEOUT_SECONDS`／`_COOLDOWN_SECONDS`／`_DAILY_CALL_CAP`、`RAG_JEV_SCREEN_ENABLED`／`_EVIDENCE_THRESHOLD`／`_INJECTION_THRESHOLD`。Jev 網址改名 `JEV_BASE_URL`（舊名 `JEV_SHADOW_BASE_URL` 照讀）。
- **回答長度改成硬上限，拿掉「要詳細規格可以更長」的例外**：上一版「約 N 字為原則，要詳細規格或一次問好幾件事時最多約 40 秒」上線後實測鶴記同一批 36 題，中文中位 79 字、超過 80 字 5/12，英西超過 30 個單字 6–7/12，模型常拿例外當理由寫長。改成 jtai 的寫法「每次回覆嚴格不超過 N 字，超過即違規，寧可精簡也不可超過；一次問好幾件事時每件只講重點」（中日韓 80 字、英西 30 個單字），同一批題目中文中位 49 字、超過 1/12，英文超過 2/12、西文 0/12。只改提示詞，不截斷回答。
- **回答長度改用「念多久」限制，中文也一起管**：原本只有英西有「約 40 個單字」，中文沒有上限；實測鶴記同一批問題中英西回答中位數都要念 16–18 秒，一次問好幾件事的題目念到 35–46 秒。現在每種語言都寫「以 20 秒內念完為原則，要詳細規格或一次問好幾件事時最多約 40 秒」，再依實測語速換成字數（VoxCPM 一般中文句每秒 3.1 字、Edge 4.7 字，取 4 字；英西每秒約 1.5 詞）：中日韓約 80／160 字、英西約 30／60 個單字。同一題中英西念的秒數差不到一成，西語念得久是寫得長、不是語速慢。
- 入口與大型模組依職責拆分：前台 `App.vue` 僅組裝畫面與 composables；Backend `main.py` 將 TTS／ASR／文件端點、OpenAPI、監控與生命週期委派至對應模組；Brain `main.py` 委派啟動預熱及 HTTP 監控，Gemini Live 將傳輸、訊息編碼及工具執行與會話分開。維持既有 API、授權、串流及備援行為，加入入口邊界及自有正式程式千行上限檢查。

- **連不上的 ASR 引擎自動暫停 60 秒**：小米 CocktailASR 那台（.19）停機後仍在備援順序裡，Breeze 一掛每句話都要先白等 3.3 秒連線失敗才換 SenseVoice。批次辨識現在遇到連線層失敗（`httpx.ConnectError`／`ConnectTimeout`、`openai.APIConnectionError`）就把那個引擎暫停 60 秒不排入，時間到由下一個請求再試；HTTP 錯誤碼不算（機器還活著）；全部都暫停時照樣全試。另外部署設定已停用小米：根目錄 `.env` 註解掉 `ASR_XIAOMI_URL`，使用者可自選的引擎拿掉 xiaomi。
- **Brain 啟動時預熱台語判斷**：部署重啟後的第一句台語，Brain 判斷要 2.5 秒（之後約 1.2 秒），超過 Backend 的上限，被當成不是台語；每次 push 觸發 watchtower 重新部署都會碰到。多出來的是第一次載入 google-genai（1.2 秒）與建 client（0.17 秒）。背景預熱現在最先載入套件、建好共用 client、呼叫一次 `models.get`（不花 token，約 0.1 秒）。
- **台語判斷回報結果與耗時**：批次辨識（`/api/v1/asr/transcribe`）在台語分流時多回 `language_check: {"result", "ms"}`，`result` 是語言代碼、`timeout` 或 `failed`。原本逾時和「判成華語」回應長得一樣（`language: null`），只能翻 log 數逾時，數錯過一次（見下一條）；語音模擬（`scripts/voice_e2e/`）的彙總表多了「判斷逾時」「判斷ms」兩欄。
- **台語判斷少等 0.25–0.35 秒**：台語分流時，Breeze 轉寫約 1 秒就好，要等台語判斷（2.5 秒上限）才送出。Brain 端判斷耗時 p50 從 1.54 降到 1.24 秒、p90 從 1.73 降到 1.51 秒（真人台語 21 句，同時 1–3 句各跑 4 輪）。逾時本來就少：這批測試只有 Brain 部署重啟後的第一句逾時（碰上啟動預熱與 Gemini 冷啟動）；先前記的「同時 2–3 句約 15–20% 逾時」是數 log 時沒帶時區、把容器啟動以來的逾時都算進去，已更正。拆開量：Gemini flash-lite 聽音檔 1.2–1.7 秒是大宗（只送前 3 秒幾乎沒變快、沒有思考 token、提示詞太短用不上脈絡快取），另外 Backend 每次跑 ffmpeg 0.15 秒、Brain 每次新建 Gemini client 0.1–0.18 秒。現在上傳的已是 16 kHz 單聲道 WAV（前台 VAD 的格式）就直接送，Brain 重複使用同一個 client。
- **定稿在句子裡夾進別種文字就用暫定字幕**：中文、韓文同時勾時，韓文「이 펌프의」定稿成「이 泵의」，Jev 覺得兩句都合理（0.77／0.72）挑不出來。暫定字幕是純韓文、定稿在韓文句子裡夾漢字（或中文句子夾諺文、假名）時直接用暫定字幕，不問 Jev；日文不套（定稿把假名轉漢字是正常的）。
- **Jev 判斷定稿的語言情境跟著這一輪走**：原本讀後台設定的整份分流，現在 Backend 把這條連線實際生效的分流（前台臨時關掉的語言不算）一起送給 `POST /brain/internal/asr-judge`（新增 `languages` 欄位），跟每輪動態產生的回答語言提示一致。
- **虛擬人講完自動恢復收音**：回答期間麥克風會停（免得收到自己的聲音），以前講完不會恢復，每輪都要重按麥克風。現在回答結束（含 TTS 合成第一段聲音前的空檔、播放、字幕）後自動恢復，6 秒沒開口才關（剛按下麥克風時仍是 10 秒）；回答中使用者自己按掉麥克風就不會自動打開。Gemini Live 串流辨識在回答期間改為正常關閉連線、講完再連，避免閒置連線被斷掉後被當成「串流不可用」而一直退回批次辨識。
- **Gemini Live 辨識的語言提示跟著專案走**：原本全站共用 `ASR_GEMINI_STREAM_LANGUAGES`（zh-TW、en-US、es-ES），現在前台連線帶專案與語言分流，依分流產生（已備好日文 ja-JP、韓文 ko-KR 的對應，以後開日韓專案不用改串流這段）；沒帶專案才用環境變數。
- **英文、西語回答縮短**：虛擬人會念出回答，同一句拒答中文 67–89 字約 15 秒，西語 330–400 字元要講 25–30 秒（模型翻中文固定句時順手加長）。每輪指定回答語言時，英西多一句「資訊量跟中文一樣，2 到 3 句、約 40 個單字以內，要詳細規格時才寫長」。
- **知識庫距離門檻 0.85 → 1.0**：鶴記中英西各 12 題相關提問，0.85 只命中 34 題（「絕緣等級是什麼」「著脫座要怎麼選」的正確段落在 0.89–0.90 被擋掉），1.0 全部命中；西語、英文不少題的正確段落落在 0.86–1.05。代價是閒聊題會多帶幾段不相關的知識庫內容（醫院 4 題閒聊從 2 段變 9 段，鶴記 9 題閒聊仍是 0 段），由模型判斷不採用，top_k 上限不變。評估腳本與結果在 `scripts/experiments/kb-cutoff/`。
- **虛擬人前台暫時藏起「即時」對話模式**：設定視窗的「對話模式」（即時＝Gemini Live 當對話模型／標準＝一般 Brain）整塊隱藏，一律用標準模式。原因是「Gemini Live 即時語音」容易跟 ASR 選單的「Gemini Live」辨識搞混，實際也沒在用。以前存成即時的帳號與瀏覽器開啟時當成標準。程式保留，`frontend/app/src/types/voiceMode.ts` 的 `LIVE_VOICE_MODE_AVAILABLE` 改回 `true` 即恢復。
- **後台 Chat 也藏起 Live 模式**：標題列的 Text／Live 切換拿掉，一律用 Text（一般 Brain 回答），同樣是沒人在用、名稱又跟 ASR 的「Gemini Live」辨識撞名。存過 live 的瀏覽器開啟時退回 Text。程式保留，`frontend/admin/src/pages/Chat.tsx` 的 `LIVE_CHAT_AVAILABLE` 改回 `true` 即恢復。
- **ASR 選單的「Gemini 串流」改名為「Gemini Live」**：只改顯示名稱，引擎代號（`gemini-live`）與行為不變。
- **拔掉後台的「全站預設 ASR 引擎」**：原本 ROOT 可在後台「語音」頁替所有沒選過引擎的人指定引擎（正式環境被設成 xiaomi，蓋過 `.env` 的 breeze），前台與後台 Chat 的選單也有一個看不出是哪家的「預設（依系統設定）」。現在沒選過的人一律用部署設定 `ASR_PROVIDER`，選單直接顯示實際在用的引擎（沒授權給該帳號也列出來）；移除 `GET/PUT/DELETE /api/v1/settings/asr-provider`，auth 資料庫 migration 14 刪掉殘留的設定。試辨識改為 `POST /api/v1/asr/preview`（限 admin），可帶 `provider` 指定引擎、只影響這一次，回傳實際辨識的引擎（備援接手時看得出來）。正式環境沒選過引擎的帳號會從 xiaomi 換成 breeze。
- **前台下拉選單改成自己畫的清單**：虛擬人前台的下拉原本是原生 `<select>`，收起來的框有套樣式，點開的選項清單卻由作業系統畫（白底、系統字型、藍色選取條），CSS 管不到。`CustomSelect.vue` 改成按鈕加 HTML 選項清單，外觀與操作對齊後台 `Select.tsx`：主題色標示選中項、滑過變色、方向鍵／Home／End／Enter／Esc／打字跳選、點外面收起、下方空間不夠往上開。清單以 `position: fixed` 擺放，不會被設定視窗的捲動區裁掉；Esc 只收清單、不關設定視窗。所有下拉共用這個元件，用法（`v-model`、`change`）不變。
- **語言分流改成排序、不再過濾文件**：原本分流會把其他語言的文件整批濾掉，只勾英、西時中文文件（以及判斷不出語言、歸為中文的文件）永遠查不到，等於中文非勾不可；只有中文寫到的內容，英文提問也拿不到。改成所有文件都查得到，語言只決定誰先進 top_k：使用者語言優先，不夠再用主要語言、最後其他語言補；回答照樣用使用者的語言。鶴記這種中英西三版本的型錄仍拿同語言的原文（去重時其他語言版本讓位）。使用者語言沒勾分流時不為它擴查整個知識庫。文字與 Live 查詢遇到「hi」這類短句改用主要語言，不再固定中文。後台「分流」說明同步更新。
- **短句與語言優先順序**：「hi」「ok」「hola」這種一兩個字的短句判斷不出語言，改歸專案主要語言（知識庫分流排第一的，後台「分流」可用上移調整順序、第一個標「主要」），標籤與 AI 回覆都用主要語言，不再標英文卻回中文；有中文字就是中文；短句不送 Jev。分流順序改為後台排定的優先順序。

### Added

- **虛擬人還在想時可以補一句，兩句一起回答**：前台麥克風原本在虛擬人「思考中」就關掉，補的那句收不到；就算收到，也會取消前一句、只答後一句。現在麥克風只在虛擬人出聲（合成聲音、播放、字幕還在跑）時關；思考中（回答還沒回來）再講或再打一句，前台中止還在等的請求，把兩句用換行接起來重送一次，對話裡也只留一則合併後的使用者訊息。回答一到就不再合併，之後講的話照舊當新的一輪。快速問答帶著出處，不參與合併。Breeze（台語分流）用的 VAD 從「講完一句就關麥克風」改成連續收音，跟串流辨識一樣在虛擬人出聲時暫停、講完自動恢復；瀏覽器內建辨識一次只收一句，不支援補一句。延遲量測多一種 `outcome: "merged"`（被合併的前一輪，不算失敗），Backend `/api/v1/metrics/turn` 一併接受。講話中插話（階段 B）尚未實作，見 `docs/plans/full-duplex-voice.md`。
- **回答長度改成每個專案自己填秒數**：後台知識庫的「分流」設定多一欄「回答長度上限（秒）」，旁邊即時換算成各語言字數（20 秒＝中日韓約 80 字、英西約 30 個單字；語速由 Brain 的 `speech_rates` 提供，前後端不各寫一份）。預設 20 秒，填 0 不加長度規則。上午的 80 字上限原本套在所有專案，ESG 要照抄完整 QA 答案也被要求縮短；現在 ESG 設 0，元復醫院、釣魚的人設本來就寫 40 字，設 10 秒讓兩邊一致。Brain `GET/PUT /brain/knowledge/settings` 多 `reply_seconds`（PUT 不帶就保留原值）與唯讀的 `speech_rates`。
- **測試專案鏡像（`scripts/project_mirror.py`）**：語音模擬與提示詞實驗改在「鶴記dev」跑，測試對話與每日記憶摘要才不會寫進正式鶴記。`check` 比對兩邊的知識庫、原始資料、詞表、人設、文件設定與語言分流，不一樣就 exit 1；`sync` 由正式複製到測試專案（先備份、沿用正式專案的知識圖譜、重建索引）。`scripts/voice_e2e/run.py` 的 `--project` 是測試專案時會先檢查，不一致就停下。voice_e2e README 補上「會寫進專案每日記憶摘要」這項副作用（原本誤寫為不會）。鶴記題庫 `heji.json` 改成預設跑在鶴記dev，測試帳號 `voice-e2e-test` 的專案權限也從鶴記換成鶴記dev。

- **批次辨識多一個引擎 Confucius4-R2T2（`r2t2`）**：網易有道開源、Qwen3-ASR-1.7B。`/transcribe` 帶 `language` 與專案詞表 `context`，輸出簡體轉繁體；設 `ASR_R2T2_URL` 才排進備援順序，使用者可在聊天室選它。鶴記 10 題合成語音帶詞表：錯字率 6.9%、專有名詞 13/18、p50 0.28 秒，Breeze 5.8%、14/18、約 1.0 秒；R2T2 會把台語寫成台語漢字，台語分流照舊用 Breeze。
- 前台新增 Confucius4-R2T2 串流引擎 `r2t2-live`，與 Gemini Live 並存、與批次 `r2t2` 分開授權。Backend 依帳號偏好轉接 R2T2、帶專案詞表、重切 PCM 片段、增量累加與繁體定稿；停止時補齊尾段再送 EOS。未設定或上游失敗沿用批次備援，台語分流維持 Breeze。

- **語音對話模擬（`scripts/voice_e2e/`）**：不用對著前台講話，也能測完整的一輪語音對話。腳本用系統自己的 TTS（edge-tts、VoxCPM 等）念題目，或讀真人錄音，照前台的節奏送進串流辨識（`/api/v1/asr/stream`，每 0.1 秒 3200 bytes）與批次辨識（`/api/v1/asr/transcribe`），再問 `/api/v1/chat`，也可以用 `/api/v1/tts/stream` 念出回答；每一輪記錄錯字率、專有名詞有沒有聽對、回答有沒有講到預期的字，以及各段耗時。`--user` 在 backend 容器裡替帳號簽短效 token，不用存密碼；可以混入雜訊；跑完刪掉建立的對話。題庫在 `scripts/voice_e2e/cases/`：鶴記 10 題（合成語音）、台語連續劇真人錄音 75 句（批次辨識＋台語判斷；一次一句 69/75 判成台語，同時 3 句則全部超過 2.5 秒逾時），打分與題庫格式有單元測試（`tests/test_voice_e2e.py`）。
- **專案詞表也帶給 Breeze 與 OpenAI 辨識**：Breeze-ASR-360 1.4 起 `/transcribe` 多了選填的 `prompt` 欄位（Whisper 前文；gb10 那邊實測 12 句含「污泥泵」「DIVA」「沉水泵」「EUBL」「泵浦」的合成音 12 句修正，台語 40 句回歸沒有硬塞詞表的字，延遲 +0.01 秒）。Backend 語音辨識前向 Brain 新的內部端點 `GET /brain/internal/asr-glossary` 取專案詞表（快取 60 秒），帶給 Breeze 與 OpenAI（gpt-4o-mini-transcribe 的 `prompt`）；Xiaomi、SenseVoice、Gemini Live 不吃提示詞，照舊。只帶正確的詞：`ASR_PROMPT.md` 裡「常見誤聽：A→B」這類對照行只給對話模型看，送給辨識引擎會把錯字也教給它。同一專案每次送同一串字，Breeze 才能併批。
- **專案詞表幫 Brain 對回語音誤聽**：Gemini Live 辨識會把「沉水泵」聽成「沉睡泵」、「DIVA」聽成「低瓦」，而轉錄模型不吃背景知識（實測 `systemInstruction` 給不給結果一字不差）。Brain 每輪對話提示多一段：訊息可能是語音辨識結果、這個專案的專有名詞有哪些（讀專案 workspace 的 `ASR_PROMPT.md`，原本給 Whisper 的詞庫，2026-07 起沒人讀）；模型在理解問題與寫知識庫查詢時自己對回，不多一次模型呼叫。鶴記實測：「低瓦有攪拌器嗎」從答非所問變成答對；詞表加「常見誤聽：UNI本→污泥泵」這類對照後，原本修不回的三句都答對；「奔騰電腦」這類無關問題不被帶偏（`scripts/experiments/asr-glossary/`）。畫面上的使用者文字仍是原本辨識的結果。
- **語言分流可以選日文、韓文**：後台知識庫的分流、文件語言、對話紀錄篩選與備份、前台語言開關都多了日本語、한국어。使用者訊息有假名就是日文、有諺文就是韓文（依比例判斷，中文句子夾一個日文品牌不會整句變日文），不再一律算中文；日韓不送 Jev 校正（Jev 只問中英西，會被校回中文）。每輪的回答語言提示多了日本語、한국어，長度比照中文 2 到 3 句。Gemini Live 辨識的語言提示對應 ja-JP、ko-KR。實測（合成語音，`scripts/experiments/ja-ko/`）：串流辨識日韓字錯率 4% 以內；用日韓文問鶴記型錄 8 題全查到；Jev 判斷定稿 7 組對 5 組、沒有改錯。TTS 實測：Gemini TTS 與 Edge-TTS 的日韓聲音念得完全正確，VoxCPM 可念但有錯字，CosyVoice 較差，IndexTTS 不能念日韓；中文與韓文可以同時勾。
- **虛擬人前台可以打斷回答**：前台原本就有打斷功能（`chat.interrupt()`），卻沒接到任何按鈕，只能等虛擬人講完或趕快講下一句。現在虛擬人在想、在講或字幕還在跑時，送出鈕變成「停止」（輸入框打了字時仍是送出，送出會先停掉目前的回答），沒開視窗時按 Esc 也會停；沉浸模式下 Esc 先停講話，再按一次才離開。標準模式回覆一到狀態就回 IDLE，所以「回答中」同時看播放與字幕。
- **前台設定跟著帳號走**：虛擬人前台設定視窗按「套用」的專案、人設、角色、語音引擎與聲音、標準／即時模式、回覆深度、背景、VRM、鏡頭預覽大小，原本只存在瀏覽器，換電腦或清掉瀏覽器資料就回到預設。現在同時存到帳號（新端點 `GET/PUT /api/v1/settings/my-preferences`，auth 資料庫 migration 15 `account_preferences`），開場先拿帳號存的設定（最多等 3 秒）再挑專案與聲音；帳號還沒存過時，把這台瀏覽器之前存的上傳。只合併這次改到的欄位，兩台裝置各改各的不會互蓋。嵌入金鑰（訪客共用）不存。
- **整輪延遲量測**：前台每一輪記下開始講話、講完、ASR 回來、送出、Brain 回完、TTS 第一段聲音、開始播放的時間點，送到新端點 `POST /api/v1/metrics/turn`（需登入），每輪一行 JSON 寫進 `backend/logs/turn_timing.jsonl`（主機掛載，部署不會清掉），附分段 `durations_ms`（asr／send／brain／tts_first_audio／to_playback／total）與專案、ASR 引擎、TTS 等資訊；用 `jq` 撈法見 README「整輪延遲量測」。
- **Gemini 串流語音辨識**：前台 ASR 選單新增「Gemini 串流」（`gemini-live`），經新 WebSocket `/api/v1/asr/stream` 邊錄邊送 16 kHz PCM 給 gemini-3.5-transcribe-live：講話中顯示暫定字幕，停頓約 0.5 秒後定稿（實測中英兩句都在講完 0.5–0.7 秒內定稿），同一連線可連續多句，不需前端偵測靜音。帳號要在帳號頁被授權；連不上或未授權自動退回 VAD＋批次辨識；台語分流時改用 Breeze 批次。用量以音訊秒數記帳。

### Fixed

- **離題問句在 fast 模式回 502**：fast 模式查完知識庫就不再提供工具，模型卻照系統提示呼叫 `search_web`，參數照抄 `search_knowledge` 的 `queries`，被拒絕幾次後回空白，Brain 回 502，使用者收不到回答（語音模擬「棒球英豪是什麼意思」三題重現）。agent loop 現在不執行這一輪沒提供的工具，改請模型直接用文字作答；參數正確也不執行，否則等於繞過 fast 模式的上網限制。曾試過同時把上網工具從 fast 模式的提示拿掉，但天氣題因此不再呼叫天氣技能，離題問句也改用模型自己的知識作答，所以沒有採用。
- **Gemini Live 辨識講長句會被截斷**：閒置計時只在定稿時重算，暫定字幕不算，一句話講超過 10 秒沒停頓就被關掉。收到暫定字幕也重新計時。
- **串流辨識的定稿把對的暫定字幕蓋掉**：Gemini Live 辨識講話中的暫定字幕是「who am i」，停頓後的定稿卻送出「OMI」「O and I」，偶爾定稿成韓文。定稿跟最後的暫定字幕不同時，Backend 問 Brain 新的內部端點 `POST /brain/internal/asr-judge`：兩段文字各自問 Jev 像不像正確辨識的一句話（情境帶專案名稱與語言分流，閒聊也算合理），暫定字幕高出 0.2 以上才換，否則照定稿；不重送音訊，只有兩者不同時多約 0.3 秒。離線 20 組 18 組挑對、0 組把對的定稿換掉（`scripts/experiments/asr-final-judge/`）。每次判斷記在 `backend/logs/asr_final_judge.jsonl`。
- **長回答的字幕講到一半整段跳出來**：標準模式的字幕是前端打字機（約 22 字／秒）跟著語音逐字顯示，但 TTS 一下載完（還沒播完）就把剩下的字一次倒出來，回答越長越明顯；句與句之間斷音兩次，3 秒的欠載看門狗也會倒字。改成打字機自己跑完，只有出錯、停止播放或打斷時才一次顯示；聲音一恢復就取消看門狗。
- **西語隨便問都撈到無關的知識庫段落**：關鍵字（FTS）比對命中的段落原本不看距離一律放行。鶴記加了西語版型錄後，「¿Qué tiempo hará mañana?」這種跟產品無關的問題也因為「qué」撈回 3 段問答。現在 FTS 命中的段落會補算與問題的距離，超過 `rag_fts_distance_cutoff`（預設 1.1，一般門檻 0.85）就丟掉；型號這類字面命中但語意偏遠的相關段落（約 0.94）仍保留。
- **語音辨識回報的引擎不準**：`POST /api/v1/asr/transcribe` 回傳的 `provider` 原本是帳號偏好的引擎，偏好的掛掉、由備援接手時仍寫偏好的那個；改成實際辨識的引擎，全部失敗時為空字串。
- **台語分流時偶爾一句話要等二十幾秒才回**：開了台語分流的專案，語音辨識要等 Breeze 轉寫和「是不是台語」的判斷都回來才繼續。判斷通常 1.9 秒（真人語料 p50），但 95 句裡有一句拖到 22.7 秒，原本要等到 35 秒逾時。改成判斷最多等 `ASR_LANGUAGE_CHECK_TIMEOUT_SECONDS`（預設 2.5 秒），逾時就當不是台語、照原本的 TTS 回答。
- **Breeze 把同一句話轉成兩三遍**：真人台語朗讀 20 句有 3 句整句重複 2–3 次，原樣送進 Brain 等於使用者講了三遍。整段剛好是同一句重複時收成一次（4 個字以下不動，部分重複不動）。
- **西語提問卻用中文回答**：下午加的「本專案主要語言：繁體中文」會被模型當成回答語言，鶴記西語提問 6 題裡 2 題整句回中文（照抄人設裡「型錄資料未提及此規格」「請洽詢鶴記企業…」等中文固定句），另 2 題夾雜中文。改成每一輪在 system prompt 明講「這一輪的回答語言」（規則判斷；短句用主要語言、台語語音用繁體中文、判斷不出來才請模型看原句），並要求知識庫與人設的中文固定說法翻成回答語言；改後同樣 6 題全用西語。Live 的預設語言句改成只在判斷不出來時適用。
- **前台設定每次打開又回到預設**：設定 store 以前用 watch 把每次變動都寫回 localStorage，開場抓清單時的暫時清空、清單失敗時退回帳號預設也被存下去：專案清單 502 一次或載入到一半就重整，存的專案、人設、語音、VRM 就永久變回預設；2D 清單失敗一次還會把模式存成 3D。改成只有按「套用」才寫入（`saveSettings()`），開場一律以存過的值（`savedSettings()`）挑選，退回只影響這次。設定視窗改成只記使用者動過的欄位：清單還在載入時打開、看一下別的專案再切回來、換引擎後按取消再打開，都不會再把空值或預設值當成選擇存下去。「自動」語音引擎可以還原；語音引擎與聲音成對寫入；後台 Chat 載入時退回的 TTS 不再寫回與前台共用的鍵；帳號自己的舊鍵優先於未登入時遷出的鍵。
- **語言分流不必含中文**：後台「分流」拿掉各語言的說明文字；至少勾一條、不一定是中文（純英文知識庫只勾 English）。只有一條不分流；多條時第一條（zh、en、es、nan 順序）是查不到時的退路。前台臨時開關同樣至少留一條。
- **台語分流不該每句都換 VoxCPM**：原本只要專案開了台語分流，打字、快速問答、講華語也全被換成 VoxCPM（同事選 Gemini TTS 卻聽到 VoxCPM）。改成這一輪是語音且 ASR 判成台語（`speech_language=nan`）才換；前台記住上一句是否為台語語音，後端同條件核對。
- **前台（/openvman/）白畫面**：589c303 把虛擬人前台改成靜態 build 後，index.html 以 `/assets/index-*.js` 載入，但主機 nginx 的根目錄轉發清單沒有 `assets`，CSS 回 HTML、JS 404。template 加上 `assets`；同時把主機上被直接改過、template 沒有的 `client_max_body_size 100m` 補回 template，免得部署時被拿掉又出 413。
- **備份讀取不清除對話**：預覽與正式備份改用單一 SQLite 快照讀取摘要與訊息，不觸發聊天的 TTL 清理，保留尚在資料庫的過期對話。
- **ASR 撤權後忽略舊偏好**：設定 API 與 worker 共用目前授權判定；正式／臨時帳號撤權後不再把舊引擎當 preferred，既有系統預設與 fallback 策略維持不變。
- **錄音閒置與 fallback 狀態**：continuous 模式持續說話不會被 10 秒閒置計時停錄；VAD 啟動失敗後的舊回傳不再覆寫錄音器狀態與自動停止計時器。
- **語言搜尋候選不足**：逐步擴大候選窗，確認完整候選後才退回中文；擴展詞向量在單次查詢內重用。Live 文字新回合清除前一句語音語言判定。
- **Live 用量歸屬與關閉清算**：Backend 以已驗證的呼叫者產生帳號／金鑰身分標頭，Brain 將其寫入秒數事件；中途離開也清算剩餘音訊，listener 取消不會中斷已開始的入帳，正常完成後關閉不重複記錄。

### Changed

- **台語分流接上前台語音**：前台 app 的語音一律先經 Backend ASR（Live 模式也是），所以台語分流改在這裡生效：
  交集含台語時 ASR 改用 Breeze、另請 Brain 聽是不是台語（新 `POST /brain/internal/audio-language`），結果隨訊息
  `speech_language` 存成訊息語言並讓知識庫查台語文件；TTS 原本不是 VoxCPM／CosyVoice 就改 VoxCPM（先於帳號聲音授權）。
  前台設定視窗新增「語言分流」，只能在後台開的範圍內臨時關掉／勾回（`GET /api/v1/language-routes`，存在瀏覽器、依專案分開）。
  Live 文字回合的語言判定綁定該回合：先清前一句，再套這一句帶的 `speech_language`。
- **主模型預設改 gemini-3.5-flash-lite**：`config.py` 的 `llm_model` 與 `.env.example`、文件範例跟正式環境一致（正式本來就由 `.env` 設 3.5-flash-lite，行為不變）；文件裡的備援鏈範例也換成正式用的 gemini → openai → groq → nen。

### Added

- **台語辨識實驗與 Live 音訊語言判斷**（`scripts/experiments/taigi/`）：合成醫院情境台語 8 句，Breeze 8/8 直接翻成
  華語、Xiaomi 約 4/8、Gemini Live 3.8 只聽懂 2/8、OpenAI 約 1/8、SenseVoice 0/8（全吐日文假名）；gemini-3.1-flash-lite
  判斷語言 13/13（含華英西對照）。據此新增 `LIVE_AUDIO_LANGUAGE_ID_PROJECTS`：Live 每句語音在背景判斷 zh／nan／en／es
  並寫進訊息語言，不改變回答（影子）；對話紀錄與備份多「台語」。
  判斷模型預設 gemini-3.5-flash-lite（台語 8/8、p50 1.4 s；3.5-flash 漏 1 句台語），呼叫逾時 30 秒。
  只有轉錄成中文字的句子才送音訊、且只在判成台語時覆寫；中英西沿用轉錄文字的判斷。
  真人語料重跑（`real_run.py`、`real.json`）：戲劇台語判對 42/50、朗讀台語 20/20、華語誤判 2/24，判斷 p50 1.9 s；
  Breeze 戲劇台語意思對 46/50，朗讀台語 3/20 整句重複。
  分流改由知識庫設定勾選（`GET/PUT /brain/knowledge/settings`、後台知識庫標題列「分流」按鈕），不看有哪些文件：
  勾台語才多聽這一次；只勾中文就不做語言篩選。拿掉 `LIVE_AUDIO_LANGUAGE_ID_PROJECTS`。Live 查知識庫最多等 3 秒拿
  台語判斷結果，台語就查台語文件（文件語言也認台羅與台語漢字，可手動標）。
- **文件語言判斷修正**：長篇中文文件某處一個 ñ 會被判成西語；改成漢字多於拉丁字就先判中文。
- **對話紀錄模糊搜尋**：搜尋框以空白分成多個關鍵字，每個都要出現在同一段對話但不管順序；繁簡與
  「污／汙」「後台／後臺」互通（OpenCC t2s，Brain 新增 `opencc-python-reimplemented`）。對話紀錄頁、
  匯出與聊天側欄都適用。
- **知識庫依語言分流**：同一份內容可放中英西三個版本，使用者用哪種語言問就只查同語言的文件、用原文回答，
  查不到才退回中文（文字與 Live 都適用，Graph RAG 相關段落也同語言）。文件語言依內容自動判斷並存在
  `.doc_meta.json`，後台知識庫可手動指定（檔案樹標出 EN／ES）；只有中文文件的專案行為不變。
- **對話備份依語言分檔**（VH-389）：Brain 每天 03:00 把所有專案的對話匯出到
  `/data/backups/sessions/<時間>/<專案>/{zh,en,es}.jsonl`，保留最近 30 份，同時只跑一個、先寫暫存再改名。
  後台「對話紀錄」頁對 ROOT 顯示備份區塊（預覽＝dry-run、立即備份、最近 5 份）；對外只有 Backend
  `/api/v1/backups/sessions`（限 ROOT），catch-all 代理擋掉 `backups`。設定見 `.env.example` 的 `SESSION_BACKUP_*`。
  備份與正式資料同一個資料卷，異地保存要另外同步。
- **訊息存語言，Jev 背景校正**：`messages.language` 新欄位，使用者訊息寫入時先用規則判，再在背景問 Jev，
  結果不同才改寫（`JEV_LANGUAGE_ENABLED` 預設 true）。只分 zh／en／es，其他語言與判斷不出來的都算中文。
  36 句比較：Jev 36/36、規則 33/36、主對話 LLM 33/36（`scripts/experiments/lang-detect/`）。
  舊訊息用 `brain/api/scripts/backfill_message_language.py` 逐則問 Jev 補齊（正式 136 則已補：Jev 改掉規則
  判錯的 3 則，含中英混雜的 A2A 測試句與亂碼「su3cl」）。

### Changed

- **回覆語言跟著使用者**：文字對話回答規則（`core/prompt_templates.py`）與 Live 系統指令
  （`internal_routes.py`）從「除非使用者要求，一律繁體中文」改成「用使用者最新一句話的語言回答，
  中文或無法判斷時用繁體中文」。專案 SOUL.md 若寫死語言仍以 SOUL 為準。
- **Live 收音轉錄從沒存進歷史**：Gemini 把 `inputTranscription` 包在 `serverContent` 裡，程式只看頂層，
  語音模式下使用者講的話沒有 `user_transcription` 事件、也沒寫進對話紀錄（`live/gemini_live.py`）。
- **Live 回覆與記憶封存每輪重複**：f6d58a1（09-22）讓 `GeminiLiveSession` 自己存回覆與封存，但
  `internal_routes` 的 Live bridge 原本就會再存一次；正式環境 7 組相鄰 assistant 有 6 組完全相同。
  bridge 改成只存打字輸入的使用者訊息，其餘交給 `GeminiLiveSession`。既有重複資料未清。
- **Live 英西字幕黏字**：逐段輸出轉錄被 `strip()`，字間空格落在段落頭尾而被吃掉（"suciade"），
  字幕、自訂語音送 TTS 的文字與存進歷史的回覆都受影響（`live/gemini_live.py`、`internal_routes.py`）。
  實測小鶴 Live 3.8：中英西語音提問都以同語言回覆，講完到出聲 1.7–3.7 秒。
- **正式環境設定 `WHISPER_API_KEY`**（沿用 OpenAI key）：openai 轉錄引擎可用，也會進所有專案的
  ASR 備援鏈（本地引擎全掛時才用）。

### Added

- **對話紀錄頁補齊 JTI 的歷史紀錄功能**（VH-388）：勾選後可「刪除已選」（新端點
  `POST /brain/sessions/batch-delete`，逐筆回報 deleted／missing，部分不存在不讓整批失敗）；
  列表每頁 50 筆分頁（摘要仍一次抓、排序篩選在前端，只切畫面）；匯出可勾「簡化格式」
  （`simple=true`，每則訊息只留 role、content、created_at）。
- **對話紀錄依語言篩選**（VH-388 最後一項）：session 摘要多 `language`，列表與匯出都可帶
  `language=` 篩選，後台加「語言」下拉與每筆語言標籤。以最後一則使用者訊息的字元與常用字
  判斷（中日韓看字元、英西看 ¿¡ñ 與常用字），不呼叫模型也不加欄位，舊對話直接可篩。

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
- **OpenAI ASR 把英文、西語硬轉成中文**：`_transcribe_openai` 寫死 `whisper-1` 與 `language="zh"`，
  西語句子被翻成中文且翻錯、中文是簡體；base URL 還誤讀 `VISION_LLM_BASE_URL`，設了 VLM 就把語音
  送到 VLM 閘道。改成不指定語言、模型可設（`ASR_OPENAI_MODEL`，預設 `gpt-4o-mini-transcribe`，中文出
  繁體、西語正確）、獨立的 `ASR_OPENAI_BASE_URL`。多語實測見 `scripts/experiments/asr-multilingual/REPORT.md`。
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
