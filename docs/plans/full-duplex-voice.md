# 語音對話不再一問一答：插話與連續追問

狀態：進行中（2026-10-05）。階段 A 已上線（`e52b7d7`）；階段 B 程式已寫好但前台開關關著，等現場回音實測。

實作進度：階段 A 已加入前端收音／合併與 Brain 接收確認流程，驗證結果見文末。
階段 B 的插話分類端點與前台串流收音已寫好，但前台開關 `INTERRUPT_WHILE_SPEAKING`
預設關（2026-10-02 晚）：回音過濾只擋完全相同的文字，現場回音沒測過。GuardAgent
規則維持上午測過的版本（下午曾加入「嗎／什麼／多少／？」，會讓「對嗎」「好嗎」
這類附和也判成停，已撤回）。部署改回 push → CI → watchtower，本機 Compose 覆寫不再使用。
使用者確認前維持 Draft。

## 目標

使用者可以：

1. 虛擬人還在想的時候補一句，兩句一起回答（「沉水泵多深？還有馬力多大？」）。
2. 虛擬人在講的時候開口，講的是新問題或「等一下」就停下來聽；只是附和（「對啊」「嗯」）就繼續講。

## 實作前現況（2026-10-02 讀程式確認）

- **麥克風是寫死關掉的，沒有設定可以改。**虛擬人一進入「思考中」或「講話中」，`useAvatarVoiceInput.ts:237-249` 就停掉收音；等它講完、字幕打完、聲音播完才重開（`:251-258`），重開後 6 秒沒講話再關。
  - 串流辨識（R2T2、Gemini）是整條連線停掉；Breeze 用的 VAD 每句講完就停，回答後也不會自己重開；瀏覽器內建辨識一次只收一句。
- **回音消除只開了一部分。**串流辨識與 VAD 的麥克風有開瀏覽器的 `echoCancellation`；按住說話的錄音沒開。虛擬人的聲音走 Web Audio（`scheduler.ts`），瀏覽器的回音消除能不能把它扣掉，要看瀏覽器與喇叭／麥克風，程式管不到，**沒有實測過**。
- **新的一句會取消舊的一輪，只送新的那句。**前台目前主要是文字模式（HTTP `/api/v1/chat`，沒有 WebSocket）：送新訊息時中止上一個請求、丟掉舊回覆，不合併。
- **Brain 要等回答完整才寫入「問題＋回答」，但瀏覽器取消不等於 Brain 取消**（`chat_service.py` 的 finalize）。原先 HTTP 路由沒有檢查前台是否收到回答，舊請求仍可能寫入紀錄。階段 A 因此加入版本與接收確認：先暫存答案，只有前台接受的目前版本才能寫入。
- **插話判斷已經準備好但沒人用。**backend 的 `client_interrupt` 會用規則＋Jev（2026-10-02 預設開，自寫 30 題規則 23/30、Jev 29/30）判斷「這句要不要停」，但只有 WebSocket 模式會送，而且前台送的辨識文字一律是空的，所以永遠是「直接停」。文字模式沒有對應的端點。

## 做法：分兩階段

### 階段 A：思考中可以補一句，兩句合併回答（低風險，先做）

虛擬人在想的時候不出聲，沒有回音問題。前台（`frontend/app`）修改收音與合併；
Brain 加入回答接收確認，Backend 公開代理端點，以避免舊請求留下重複紀錄。

**進度（2026-10-02）**：步驟 1–4、6 已實作，測試紀錄以文末最新結果為準；步驟 5 實機驗收還沒做。跟下面步驟不同的地方：

- VAD 直接改用 `continuous` 模式（步驟 2 的第二種做法），不在上傳後重開：講完到辨識回來約 1 秒，這段時間麥克風若是關的，補的那句會漏掉。`continuous` 遇到雜音轉不出字會安靜略過，不再跳「辨識失敗」。共用層的 `per-utterance` 模式現在沒人用，留著沒刪。
- 延遲量測新增 `outcome: "merged"`。Backend 的 `TurnTiming` 用 `Literal` 驗證 outcome，所以 `backend/app/turn_timing.py` 多加一個值（只有這一行）；前後台的 outcome 清單有測試比對，不會各改各的。
- 快速問答（帶 `sourcePath`）不合併，兩句接在一起出處就對不上了。
- 思考中沒出聲就結束（出錯、按停止）時，麥克風還開著，改成從那時開始倒數 6 秒。

**先懂的兩件事**

- 前台主要跑**文字模式**（`useAvatarChat.ts` 的 `_sendMessageText`，HTTP `/api/v1/chat`）。回答一到，`state` 就從 `THINKING` 變回 `IDLE`，接著才合成、播放聲音（`ttsPending`、`audio.isPlaying`）。所以「講話中」不能只看 `state === 'SPEAKING'`，要看「`ttsPending` 或 `audio.isPlaying` 或 `isTyping`」（就是 `avatarResponding` 去掉 `THINKING` 那一項，`useAvatarConversation.ts:203-209`）。
- 「思考中」＝文字模式 HTTP 請求還沒回來（`state === 'THINKING'`）。合併只發生在這段時間；回答一到（第一個字出來）就不再合併，之後講的話照原本流程當新的一輪。

**步驟**

1. **麥克風只在講話中關**（`frontend/app/src/composables/useAvatarVoiceInput.ts:237-258`）
   - 現在 `watch(chat.state)` 在 `THINKING` 或 `SPEAKING` 就暫停／停止收音。改成：`THINKING` 不動麥克風；新增一個 computed `avatarSpeaking`（`ttsPending || audio.isPlaying || isTyping || state === 'SPEAKING'`），它變 true 時才暫停（串流照舊 `stop()`，其他 `pause()`），並設 `resumeAsrAfterReply = true`。
   - `avatarSpeaking` 要從 `useAvatarConversation` 傳進來（現在只傳了 `avatarResponding`），或在那邊算好一起傳。
   - 思考中不倒數 idle（照舊 `clearAsrIdleTimer`），避免使用者在等回答時麥克風自己關掉。
2. **VAD（Breeze／台語分流）講完一句要自己重開**（`frontend/shared/speech/asr/vad-recognizer.ts:281-283`、`frontend/app/src/composables/useVadAsr.ts:45`）
   - 現在 `per-utterance` 模式在 `onSpeechEnd` 先 `stop()` 再上傳，所以思考中收不到第二句。改成：上傳後若沒被使用者手動關掉、也沒在講話中，就立刻重新 `start()`（或改用連續模式，只在 `avatarSpeaking` 時暫停）。
   - 瀏覽器內建辨識（`continuous: false`）先不處理，在文件註明它不支援補一句。
3. **思考中的新訊息改成合併重送**（`frontend/app/src/composables/useAvatarChat.ts:458-531`）
   - 加兩個狀態：`pendingUserText`（目前在等回答的那句）、`pendingUserMessageIndex`（它在 `messages` 裡的位置）。
   - `sendMessage`：若 `currentMode === 'text'` 且 `state === 'THINKING'` 且 `pendingUserText` 有值，就把 `pendingUserText + '\n' + 新的一句` 當成要送的文字；把 `messages` 裡那一則改成合併後的內容（不要多一則氣泡），再照原本的 `stopActiveResponse()` → `_sendMessageText(merged)`。`speechLanguage` 用新的一句的（兩句不同語言時以後一句為準，寫進註解）。
   - `_sendMessageText` 開始時設 `pendingUserText`，回覆到了、錯誤、被中止時清掉。
   - 注意 `useAvatarConversation.ts:232` 的 `turnTiming.begin()` 會把舊的一輪記成 `superseded`；合併時要記成同一輪（或新增 outcome `merged`），延遲統計才不會把合併算成失敗。
   - live（WebSocket）模式目前沒在用（`LIVE_VOICE_MODE_AVAILABLE = false`），先不改，在文件註明。
   - 每一輪另有 `turn_id` 與 `turn_revision`：補句沿用 ID、版本加一，Brain 的 `chat_turns` 先登記目前版本。過時版本不能暫存或確認。
   - Brain 回傳 `requires_accept: true` 時，前台完整解析 JSON、再次確認請求仍有效，才關閉合併視窗並送 `/api/v1/chat/accept`。先確認落庫再播放；下一輪等上一輪確認完成才送出，避免歷史缺漏。確認回應遺失最多重試一次，每次逾時 10 秒。
   - 版本比對、問題／回答兩則訊息與確認標記，在 SQLite 同一交易內完成。尚未接收的舊答案就算已生成，也不會進對話、每日歸檔或自動記憶；模型與已開始的工具工作不保證能取消，也不撤銷工具本身的副作用。
4. **測試**（`frontend/app` 用 `pnpm test`，也就是 `node --test`）
   - `src/composables/__tests__/useAvatarVoiceInput.lifecycle.test.mjs`：思考中不暫停收音；開始播放才暫停；播完恢復。
   - 新增 `useAvatarChat` 的測試：思考中送第二句 → 第一個請求被中止、第二個請求的 `message` 是兩句合併、`messages` 只有一則使用者訊息；回答到了之後再送一句 → 不合併。
   - `src/__tests__/App.asr-resume.test.mjs` 若綁了舊的暫停時機，一起更新。
   - 跑 `pnpm test`、`pnpm type-check`、`pnpm build`；有改 `frontend/shared` 的話，`frontend/admin` 也要跑 `pnpm test`、`pnpm build`。
   - Brain 測舊回答晚到、已生成但未接收的答案被取代、重複確認、跨帳號／人設隔離與多 worker 版本保護。Backend 驗證代理端點、登入及專案授權。
5. **實機驗收**（鶴記dev、帳號 voice-e2e-test，辨識引擎用 r2t2-live；切偏好用 scratchpad 的 set_pref 方式或後台設定，測完改回）
   - 連講兩句，第二句在第一句回答出來前講（間隔 1–3 秒）：回答同時涵蓋兩句；對話紀錄只有一則合併的使用者訊息、一則回答。
   - 單句：延遲跟現在一樣（看 `backend/logs/turn_timing.jsonl`）。
   - 虛擬人講話時講話：照舊收不到（階段 A 不處理講話中）。
6. **文件**：`frontend/app` 的 README 或 `docs/specs/02_FRONTEND_SPEC.md`補「思考中可以補一句」；`CHANGELOG.md`；本文件狀態維持 Draft，等使用者確認再改。

代價：被取消的那次模型呼叫白算（fast 模式約 2 次呼叫、幾百 token）；合併後要重新等一次回答。

### 階段 B：講話中可以插話（要先實測回音）

1. 講話中也**保持收音**（只限串流辨識；Breeze 批次照舊講話中關麥克風）。
2. 收到插話的辨識文字（定稿，或暫定字幕超過 N 字）：
   - 先過濾回音：辨識文字跟虛擬人正在念的回答很像（例如 70% 以上的字出現在回答裡）就丟掉，那是它自己的聲音。
   - 送 backend 判斷要不要停：文字模式要新增一個端點（例如 `POST /api/v1/interrupt/classify`，內部用現有的 `GuardAgent`），WebSocket 模式改送帶文字的 `client_interrupt`。
   - 判斷要停：停播放、停字幕，把這句當新的一輪送出；判斷不停（附和）：繼續講，這句丟掉。
3. 「停止」按鈕與 Esc 照舊直接停。

驗收：鶴記現場的喇叭與麥克風，虛擬人講話時：
- 不講話：不能被自己的聲音打斷（連續 20 輪 0 次誤停）；
- 說「對啊」「嗯」：不停；
- 說「等一下」或新問題：1 秒內停下並開始回答新問題。

## 還不知道的事

- **瀏覽器回音消除對 Web Audio 播放的效果**：沒在現場的喇叭、麥克風、音量下量過。效果差的話，階段 B 的回音過濾要更嚴，或需要指向性麥克風／耳麥。這是階段 B 做不做得成的關鍵，要先在現場實測。
- 收音一直開著時，R2T2 串流同時連線數會變多（每個開著的前台一條），.37 跟 Breeze 共用 GPU。
- 合併時兩句的接法（空白、換行、「另外」）對回答品質的影響，要實測。

## 不做的事

- 不做「講話中把插話跟原本的問題合併重答」：插話通常是改問別的，直接當新的一輪比較自然。
- 不改按住說話（push-to-talk）的行為。

## 階段 A 驗證紀錄（2026-10-02）

- 前台 `pnpm test`：277 通過；`pnpm build`（含型別檢查）通過。
- 後台 `pnpm test`：522 通過；`pnpm build` 通過。共用 VAD 的註解更新與前台使用 continuous 模式不改後台策略。
- Brain：於現有 api 容器 `/tmp` 的隔離程式快照測試，非 integration 套件 1,103 通過、1 跳過、15 deselected。正式程式與資料未被替換。
- Backend：相關代理、接收確認的登入／專案授權、`merged` 計時與補齊快照後的回歸，24 通過。完整套件最初 1,086 通過，另有快照缺少檔案造成的 6 項失敗（已補齊後重測通過）、備份路由的 introspection 測試失敗與 1 項 HTTP client teardown 的 `Event loop is closed`。備份路由失敗已在 HEAD 程式快照重現，與 FastAPI 0.142 的巢狀 router 有關；teardown 在單獨測試通過，整套測試的 client／event loop 相互影響尚未修復，不能宣稱 Backend 全套綠燈。
- 使用 agent-browser 與本機已安裝的 Chromium 跑真正瀏覽器，載入目前的 `useAvatarChat` 與 Vue：兩次送出產生同一回合的版本 1／2、舊請求被取消、只有一個合併使用者氣泡、只有版本 2 被確認後播放。另驗證停止後晚到的答案不確認。網路回答為模擬，不代表 ASR、TTS 或現場硬體驗收。
- 契約生成 `--check`、入口／檔案大小測試 5 項與 `git diff --check` 通過。

已部署本機 api、backend、gateway-worker、avatar。需依第 5 步做雙句語音與單句延遲驗收；
階段 B 的現場回音測試仍未執行。未暫存、提交或推送，計畫狀態維持 Draft。

## 本機部署與階段 B（2026-10-02）

- 使用 `docker-compose.local.yml` 唯讀掛載部署，無重建 GPU 依賴；前台 production build 通過。
- 插話分類新增 7 項、連同既有 GuardAgent／Jev 共 64 項 Backend 測試通過；公開 nginx 上登入分類 4 項通過，未登入回 401。
- 公開 nginx 上帶版本的 chat、accept 與重複 accept 通過。
- 鶴記dev 一題合成語音→Breeze 批次辨識→Brain→TTS 通過，辨識錯字率 0，辨識約 724 ms、回答約 3375 ms；這是合成語音，並非真人麥克風。
- 測試帳號的串流辨識回 `not_allowed`，未更動帳號偏好或授權。實體回音 20 輪與插話低於一秒未驗證。
- 回音過濾目前只忽略正規化後完全包含於回覆的文字；使用者照念回覆也可能被忽略，ASR 錯字仍可能誤判。
- 延遲分類不會停止已結束或已換回覆的播放；分類失敗／逾時維持播放。瀏覽器內建、Breeze／批次不支援播放中插話；Admin 與外部 SDK 未改動收音策略，隱藏 Live 路徑沿用既有 GuardAgent。

公開主頁以 Chromium 驗證，登入頁載入目前 production bundle。兩筆測試對話已在 api 容器內精確清除；測試專案的用量及記憶摘要仍依既有測試機制留存。
