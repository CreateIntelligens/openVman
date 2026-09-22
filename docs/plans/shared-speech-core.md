# 兩個前端共用語音核心（ASR／VAD／TTS）

狀態：Draft。範圍：把 `frontend/app`（Vue）與 `frontend/admin`（React）各自實作的
ASR、VAD、TTS 邏輯抽成一份無框架的 TypeScript 核心，兩邊只留薄薄一層綁定。
不改後端 API 合約（第 6 階段除外，那是新增端點）。

給實作者的話：這份文件假設你沒讀過這兩個前端。每一階段都有「驗收」小節，做完
一階段就提交一次，不要一次做完再提交。每一階段結束時兩個前端都要能 build、
測試全綠、部署後實際按過麥克風。

---

## 0. 為什麼要做

兩個前端的語音功能是各寫一份的，而且已經在漂。2026-09-21～22 兩天內修的 bug
（麥克風按了沒反應、頭一秒收不到音、VAD 每次重載）每個都要修兩次。盤點結果
（詳見附錄 A）裡最嚴重的不是重複，是**兩邊做了相反的產品決定**：

| 決定 | app | admin |
|---|---|---|
| 引擎設定還沒載到時預設用哪個 | 伺服器引擎 | 瀏覽器內建 |
| 瀏覽器辨識壞掉（沒權限、不支援）自動改用伺服器引擎 | 有 | 沒有，麥克風按鈕直接死掉 |
| 收音閒置自動停 | 沒有——按鍵錄音忘了按停會一直錄 | 10 秒（VAD）／60 秒（按鍵錄音） |
| VAD 收音方式 | 一次按鍵收一句 | 開著連續聆聽 |
| 後端 TTS 換了引擎（fallback）使用者知不知道 | 完全不知道，沒讀 header | 讀了 header，但畫面寫死「已切換至 Edge TTS」，原因丟掉 |
| 同一個錯誤的訊息文字 | 五種狀況有四種跟 admin 不同 | |

這些不是 bug，是沒有人決定過。抽共用層的第一個價值就是**逼著把決定做一次**。

## 1. 目標架構

```
frontend/shared/speech/          ← 純 TypeScript，零框架依賴，零 DOM 框架 import
  audio/
    wav.ts                       encodeWav、encodePcm16、downmixToMono、resamplePcm、rmsVolume
    pcm-stream.ts                TTS 串流解碼：WAV 標頭剝除、取樣率偵測、串流重採樣
    scheduler.ts                 PCM 排程播放（gapless、generation、音量分析）
  asr/
    engines.ts                   引擎 id、顯示名稱、說明、BROWSER_ASR 常數
    errors.ts                    錯誤碼 enum + 錯誤碼→中文訊息的唯一一張表
    browser-recognizer.ts        Web Speech API 包裝（class）
    server-recorder.ts           MediaRecorder 錄音上傳（class）
    vad-recognizer.ts            Silero VAD 切句上傳（class）
    controller.ts                引擎選擇狀態機：選引擎→選收音方式→閒置計時→fallback
    client.ts                    fetchMyAsrProvider／setMyAsrProvider／transcribeOnServer
  tts/
    selection.ts                 provider+voice 配對驗證、帳號預設回退
    fallback.ts                  X-TTS-Fallback-Reason 解析 + 使用者訊息
    cache.ts                     LRU + SHA-256 key
  http.ts                        HttpAdapter 介面（fetch-like + 錯誤映射），由兩邊注入
  storage.ts                     帳號範圍 localStorage（合併 storageUtils／scopedStorage）
  index.ts

frontend/app/src/composables/    ← 薄層：把 core 的 subscribe 接到 ref
frontend/admin/src/hooks/        ← 薄層：把 core 的 subscribe 接到 useState
```

### 1.1 核心層的形狀

每個有生命週期的東西（recognizer、recorder、VAD、controller、scheduler）都是同一種形狀：

```ts
interface SpeechUnit<State, Events> {
  readonly state: Readonly<State>
  subscribe(listener: (state: Readonly<State>) => void): () => void
  on<K extends keyof Events>(event: K, handler: Events[K]): () => void
  dispose(): void
}
```

- 狀態是一個不可變物件，每次變更整個換掉並通知。薄層只做一件事：
  `subscribe` 進來就 `ref.value = state`（Vue）或 `setState(state)`（React）。
- 不用 RxJS、不用 EventEmitter 套件。手寫 `Set<listener>` 就夠。
- 沒有 `window`／`navigator` 以外的全域依賴。`fetch` 透過 `HttpAdapter` 注入。
- `dispose()` 是唯一的清理入口。薄層在 `onUnmounted`／`useEffect` cleanup 呼叫它。

### 1.2 為什麼不用 pnpm workspace

repo 目前沒有 workspace、沒有根 `package.json`，三個前端各有 lockfile。`contracts/`
已經用「vite alias + tsconfig paths + Docker `COPY`」的方式被 admin 消費，證明可行。
跟著這個先例走，風險最低：

- `frontend/shared/` 是一個目錄，**不是** package，沒有自己的 `package.json`。
- 兩邊 `vite.config.ts` 加 alias `@shared → ../shared`，`tsconfig.json` 加
  `paths` 與 `include`。**app 的 `@contracts` alias 設了但從沒用過**，接的時候
  照 admin 的三件式（alias + paths + include）做，不要只設 alias。
- 兩個 Dockerfile 加 `COPY frontend/shared /shared`（`WORKDIR` 是 `/app`，
  `../shared` 剛好對上）。`docker-compose.dev.yml` 對應加 bind mount。
- `@ricky0123/vad-web` 兩邊都已裝同版（0.0.30），shared 層 `import()` 它時由消費端
  的 `node_modules` 解析，不用另裝。**兩邊版本必須一致**，加一個測試比對兩份
  `package.json`。

之後若要正式化成 workspace，shared 目錄可以原地變成 package，不必再搬。

## 2. 要先做的決定（實作前確認，不要自己猜）

下面每一項都是兩邊目前不一致、抽共用層時必須選一邊的。我給建議，但這是產品決定，
**動手前先跟使用者確認**：

| # | 決定 | 建議 | 理由 |
|---|---|---|---|
| D1 | 引擎設定還沒載到時預設 | **伺服器引擎** | 瀏覽器辨識會把聲音送 Google，不該是預設；且 ROOT 等帳號沒授權瀏覽器引擎 |
| D2 | 瀏覽器辨識壞掉自動退伺服器 | **要，兩邊都要** | 使用者按了麥克風就是要講話，不是要看錯誤訊息 |
| D3 | 閒置自動停 | **要，兩邊都要**：VAD／瀏覽器 10 秒沒聲音停；按鍵錄音 60 秒上限 | app 現在忘了按停會一直錄 |
| D4 | VAD 收音方式 | **做成選項** `commitMode: 'per-utterance' \| 'continuous'`，app 用前者、admin 用後者 | app 有 TTS 回授問題（麥克風開著會收到喇叭），admin 沒有；這是真的不同需求，不是漂移 |
| D5 | 辨識不出東西的雜音片段 | **continuous 模式安靜略過，per-utterance 模式回報錯誤** | 連續聆聽時雜音是常態；按一下錄一句卻沒東西，使用者需要知道 |
| D6 | 錯誤訊息 | **核心層只發錯誤碼**（app 現在的做法），中文訊息在 `errors.ts` 一張表 | 文案改一處；測試比對碼不比對字 |
| D7 | 引擎選單的「預設（依系統設定）」選項 | **兩邊都要有** | admin 現在選了就回不去「跟系統」 |
| D8 | 換引擎存失敗 | **樂觀更新 + 失敗還原 + 提示**（app 做法） | admin 現在失敗後畫面跟伺服器不一致 |
| D9 | TTS provider+voice 配對 | **當一組驗證**（app 做法）：存的配對失效就整組退回帳號預設 | admin 現在會拼出「存的引擎 + 別的聲音」 |
| D10 | TTS fallback 提示 | **顯示後端給的原因**，不寫死引擎名 | admin 現在讀到原因後丟掉 |
| D11 | localStorage 鍵名 | 統一用 `speech.*` 前綴，**帶舊鍵遷移**（讀不到新鍵就讀舊鍵並寫回新鍵） | 兩邊鍵名完全不同（`avatar.tts_engine` vs `brain-tts-provider`） |

## 3. 階段

每階段獨立可提交、可部署、可回退。順序是照風險排的：先搬本來就沒框架依賴的，
最後才動狀態機。

### 階段 1：純函式搬家（零行為變更）

搬 `encodeWav`、`encodePcm16`、`downmixToMono`、`resamplePcm`、`rmsVolume`、
`MIME_SUFFIXES`／`suffixFor`、引擎名稱表、`BROWSER_ASR`。這些兩邊行為已經相同
（附錄 A §5 確認 WAV 輸出逐 byte 一致）。

- 建 `frontend/shared/speech/`、alias、tsconfig、Dockerfile `COPY`、compose mount。
- 兩邊改 import，刪掉本地副本。
- `rmsVolume` 的 `3.4` 增益是實測值，搬過去時留原註解。

**驗收**
- 兩邊 `tsc` 乾淨、測試全綠、`vite build` 成功。
- `git grep -n "function encodeWav\|MIME_SUFFIXES\|ASR_ENGINE_LABELS\|ASR_ENGINE_NOTES" frontend/app frontend/admin` 只剩 shared 一處。
- Docker image 兩邊都 build 過（不是只 `--plugin-dir` 式的本機驗證）。
- 一個測試比對 `frontend/app/package.json` 與 `frontend/admin/package.json` 的
  `@ricky0123/vad-web` 版本相同。

### 階段 2：錄音與 HTTP client

`server-recorder.ts`（MediaRecorder 錄音上傳）、`client.ts`（三個 API 函式）、
`http.ts`（adapter 介面）、`errors.ts`（錯誤碼 + 訊息表）。

- 錄音邏輯兩邊已經逐字相同（位元率 128 kbps、MIME 順序、空片段判定），取 admin
  版的 `aliveRef`／取消中釋放 stream 這兩個 app 缺的防護。
- 錯誤碼採 app 的集合：`not-supported`、`not-allowed`、`no-speech`、`start-failed`、
  `transcribe-failed`。訊息表是唯一一份，兩邊的字要一樣（D6）。
- `HttpAdapter`：`request(path, init) → Response` + `parseError(res) → string`。
  app 注入 `apiFetch`，admin 注入 `apiUrl` + `apiFetch`。**路徑由 shared 層寫
  完整的 `/api/v1/...`**，adapter 不要再補前綴——admin 的 `apiUrl` 會補，注入時
  要繞掉，否則會變 `/api/v1/api/v1/`（admin `api/settings.ts` 有這個坑的註解）。

**驗收**
- 用假 `MediaRecorder` 跑完「開始→停止→上傳→出字」，含權限被拒、空片段、後端回
  「（音訊轉錄失敗）」三條錯誤路徑。這個測試已經在 admin 有
  （`useServerSpeechRecognition.test.tsx`），搬到 shared 層改成不依賴 React。
- 兩邊薄層各一個測試：state 變了 ref／useState 有跟著變。
- 兩邊錯誤訊息文字相同（測試從同一張表取字比對畫面）。

### 階段 3：VAD

`vad-recognizer.ts`。兩邊的 VAD 常數、實例重用、pause-not-destroy 已經一致
（附錄 A §1），差在收音方式與錯誤分類。

- `commitMode` 選項（D4）。`per-utterance`：`onSpeechEnd` 先 `stop()` 再上傳；
  `continuous`：上傳後繼續聽。
- 「辨識中」一律用計數不用布林——continuous 會多句同時在飛，先回來的不能把狀態
  提早關掉。
- 錯誤分類採 app 版：`NotAllowedError`／`NotFoundError` → `not-allowed`（換引擎沒
  用，`supported` 維持 true）；其餘 → `vad-unavailable`（`supported` 轉 false，
  controller 據此退回按鍵錄音）。admin 現在全部當 unsupported，權限被拒會白白退到
  按鍵錄音再被拒一次。
- 雜音片段：依 D5。
- 靜音計時（admin 的 `SILENCE_TIMEOUT_MS = 1000` → `onSpeechCommit`）只有 Live
  模式在用，保留為選項，chat 路徑不開。
- `starting` 狀態：`isListening` 要等 `instance.start()` 真的成功才 true；之前是
  `starting`，UI 顯示「麥克風啟動中…」。這是 2026-09-22 剛修的，不要退回去。
- 資產路徑 `/admin/vad/`、`ORT_WASM_CDN` 版本 `onnxruntime-web@1.24.3` 兩邊共用。
  **升版時一起升**。

**驗收**
- admin 現有的 7 個 `useVad` 測試（假 `MicVAD`：建一次、pause 不 destroy、載入中
  關掉不開麥、關掉後事件忽略、載失敗標不支援、卸載才 destroy）搬到 shared 層並
  全過，加 `commitMode` 兩種各一個。
- 後台 Live 模式（`useLiveSession.ts:438` 用 `useVad`）行為不變：手動測開麥、
  講話、1 秒靜音後 commit。
- 部署後兩邊實際按麥克風：第一次看到「啟動中」一下，第二次起幾乎立刻能講。

### 階段 4：瀏覽器辨識

`browser-recognizer.ts`。兩邊差最多的一個（附錄 A §3：continuous、重啟、結果擷取、
錯誤分類、speaking 訊號、全部不同）。**以 admin 版為底**——它是超集：有型別、
`isFinal` 正確處理、`onspeechstart/end` 給 speaking 訊號、終止錯誤分類、自動重啟。

- `continuous` 做成選項，app 用 false（一句一按）、admin 用 true。
- 終止錯誤集合用 Web Speech 規格的三個：`audio-capture`、`not-allowed`、
  `service-not-allowed`。app 自創的 `not-supported` 碼保留給「API 根本不存在」，
  在建構時就判定，不混進 runtime 錯誤。
- **打開 `interimResults`**，透過 `onInterim(text)` 事件往上發。這是三個引擎裡
  唯一能「講的當下就出字」的，現在兩邊都關著白白浪費。UI 把 interim 顯示成輸入
  框裡的灰色暫定字（階段 5 接）。

**驗收**
- 假 `SpeechRecognition` 跑：interim → final 順序、continuous 下 `onend` 自動
  重啟、terminal error 不重啟且 `supported` 轉 false、`aborted`／`no-speech` 靜默。
- app 端從此也有 speaking 訊號，「聆聽中」提示對瀏覽器引擎也會出現。

### 階段 5：引擎選擇狀態機

`controller.ts`。這是唯一需要真正重寫、不是搬家的部分。兩邊各 ~150 行散在 965 行
的 SFC 與 604 行的 hook 裡，決策邏輯是一個純狀態機：

```
輸入：provider（value／effective／allowed）、browserSupported、vadSupported、
      recorderSupported、userWantsListening
輸出：engine（browser│server）、inputMode（continuous│push-to-talk）、
      activeUnit（哪一個 recognizer 該 enabled）、supported、transcribing、
      speaking、starting、idleDeadline
轉移：browser 終止錯誤 → 改 server（D2，記憶體內，不寫回伺服器）
      vad-unavailable → inputMode 改 push-to-talk 並**立即開始錄**（app 做法：
        使用者那一下按鍵不能白按）
      閒置逾時 → userWantsListening = false（D3）
      換 provider → 先停收音、樂觀更新、失敗還原（D8）
```

- 三個 recognizer 由薄層建好注入，controller 只決定誰 `start()`／`stop()`。
- 引擎判定用 `effective` 還是 `value`？**用 `value` 決定「使用者要不要瀏覽器
  辨識」**（那只能使用者自己選，後端跑不了），**其餘一律交後端**（伺服器引擎由後端
  依帳號查，前端不指定，否則改個請求就能繞過授權——這是既有的安全設計，不要動）。
- `onResult` 的處置（app 直接送出；admin 接到輸入框後面再送）留在薄層，那是產品
  差異不是漂移。
- interim 文字（階段 4）從 controller 統一發 `onInterim`，兩邊 UI 顯示成暫定字；
  final 到了取代。Breeze／SenseVoice 沒有 interim 就只發 final，UI 不分支。

**驗收**
- 狀態機的測試不碰 DOM：給輸入序列，斷言輸出與轉移。至少涵蓋 D1、D2、D3、
  vad→push-to-talk 立即開錄、換 provider 失敗還原。
- 兩邊 UI 文案從同一張表取（附錄 A §4 的六種狀態）。**這一步之後兩邊同狀態同一
  句話**。
- 兩邊都有引擎選單、都有「預設（依系統設定）」選項（D7）、只有一個可選時都不顯示。
- 部署後手測：ROOT 帳號、一般帳號各一，瀏覽器引擎與伺服器引擎各一，斷網（讓 VAD
  載不到）一次。

### 階段 6：TTS

分兩半。**可共用的**先做，**兩邊真的不同的**不硬合。

可共用（搬家為主）：
- `pcm-stream.ts`：app `useTtsStreamer.ts:216-608` 那 ~390 行已經零 Vue 依賴，
  含串流重採樣、WAV `fmt` chunk 走訪、奇數 byte 跨 chunk 處理、mp3/ogg
  `decodeAudioData`。admin `ttsStream.ts` 的 200 ms 最小排程片段併進來當選項。
  admin 現在串流路徑**信任 `rate=` 標頭否則假設 48000**，沒有 app 的 WAV 標頭
  偵測——搬過去後 admin 也拿到正確的取樣率偵測。
- `scheduler.ts`：app `useAudioPlayer.ts` 只有 `isPlaying` 是 ref，其餘閉包狀態；
  把 `onUnmounted` 換成 `dispose()` 就是純 class。admin `playPcmStream` 是同一件
  事的另一份，合併。
- `selection.ts`：provider+voice 配對驗證與帳號預設回退（D9），從
  `useAvatarBootstrap.ts:266-308` 抽出。admin 換用之後不會再拼出錯配。
- `fallback.ts`：解析 `X-TTS-Fallback-Reason`，回一個 `{provider, reason}`；訊息
  由這裡組（D10）。app 開始讀這個 header——現在後端換引擎 app 使用者完全不知道。
- `cache.ts`：admin 的 LRU + SHA-256 key（~35 行，已是純函式）。app 要不要用 cache
  是產品決定，先讓它可用。

不硬合（留在各自薄層）：
- app 是「一輪對話一段串流、跟打字機同步」；admin 是「每則訊息一個播放鈕、有預先
  抓取」。目的不同，orchestrator 各自保留，只是底下都踩同一個 `pcm-stream` +
  `scheduler`。
- app 的 `{text, character}` IndexTTS 請求格式 admin 沒有。保留在 app 薄層。

**驗收**
- `pcm-stream` 的測試：餵一段帶 WAV 標頭、取樣率 24000、奇數 byte 邊界切開的串流，
  斷言輸出 PCM 16k 且 byte 數正確。這個現在兩邊都沒有測試。
- 兩邊播放同一段 TTS，人耳聽不出差異；admin 用 22050／24000 的 provider 不再變調
  （現在假設 48000 會）。
- 後端強制 fallback 一次（停掉主 provider），兩邊都跳出**含原因**的提示。

### 階段 7：storage 合併與收尾

- `storage.ts` 合併兩份 scoped localStorage，鍵名依 D11 遷移。
- 刪掉兩邊所有已搬走的本地副本；`git grep` 確認沒有殘留。
- `docs/specs/02_FRONTEND_SPEC.md` §6 改寫：指向 shared 層，把「兩邊各自實作」
  的描述拿掉。
- `CHANGELOG.md` 一條 Changed 總結。

## 4. 不做的事

- 不改後端 `/api/v1/asr/transcribe`、`/settings/my-asr-provider` 合約。
- 不做小米 SSE 逐字串流的**後端**部分。那是後端新增端點（`/api/v1/asr/transcribe/stream`
  代理 `10.9.0.19:8802/transcribe/stream`），前端這邊只要 `controller` 的
  `onInterim` 事件已經就位（階段 4／5 做好），後端端點上線時接一個 recognizer 即可。
  另開一份 plan。
- 不動 `frontend/avatar-sdk`。它是給第三方嵌入的，刻意不含 ASR／TTS。
- 不引入 RxJS、Zustand、Pinia 之類的狀態庫到 shared 層。
- 不把 app 從 `pnpm dev` 換成 production build。那是另一個問題（見附錄 B），
  但本計畫的 Dockerfile 變更要同時對兩種模式可用。

## 5. 風險

- **app 從沒真的消費過 `../` 之外的目錄**。`@contracts` alias 是死設定。階段 1 接
  alias 時要在 dev server（正式環境跑的就是 dev server）與 `vite build` 兩種模式
  都驗過 import 解析。
- **admin Live 模式共用 `useVad`**。階段 3 改它會影響 Live，驗收裡有手測項。
- **D1 改變 admin 的預設**。現在 admin 在設定載到前是瀏覽器辨識；改成伺服器後，
  沒授權任何伺服器引擎的帳號會走後端 fallback chain 的全站預設。確認這是要的。
- **localStorage 鍵名遷移**（階段 7）是唯一會碰到既有使用者資料的地方，遷移要
  帶測試、且舊鍵讀完不刪（留一版）。

---

## 附錄 A：差異盤點（2026-09-22）

以下是抽共用層前兩邊的實際狀態，供對照。行號以 2026-09-22 09:50 的 `main`
（`9350184`）為準。

### A.1 VAD

| | app `useVadAsr.ts` | admin `useVad.ts` + `useVadSpeechRecognition.ts` |
|---|---|---|
| 收音方式 | 一句一按（`onSpeechEnd` 先 `stop()` 再 `send`，:127-134） | 連續 |
| 辨識中狀態 | 布林 | 計數（`pending`） |
| 雜音片段 | 回報 `transcribe-failed` | 靜默略過 |
| 錯誤 vs 不支援 | 區分（:146-158） | 不區分，全當不支援 |
| 靜音計時 | 無 | 1000 ms → `onSpeechCommit`（Live 用） |
| `supported` 初值 | 看 `navigator.mediaDevices` | 寫死 true |
| 取消模型 | generation 計數 | `cancelled` 閉包 + `aliveRef` |

相同：資產路徑、ORT CDN 版本、`model: v5`、`startOnLoad: false`、實例重用、
pause-not-destroy、卸載才 destroy、`starting` 狀態。

### A.2 按鍵錄音

邏輯逐字相同（MIME 表、`suffixFor`、128 kbps、空片段判定）。差在錯誤合約（app 碼
／admin 字串）與 admin 多兩個防護（`aliveRef`、取消中釋放 stream）。同一狀況的
訊息五種有四種不同。

### A.3 瀏覽器辨識

| | app `useAsr.ts` | admin `useSpeechRecognition.ts` |
|---|---|---|
| `continuous` | false | true |
| `interimResults` | false | false |
| `onend` 重啟 | 無 | 有 |
| 結果擷取 | 取最後一筆，不看 `isFinal` | 從 `resultIndex` 收 `isFinal` |
| 終止錯誤 | 呼叫端 `BROWSER_FALLBACK_ERRORS`（含自創 `not-supported`） | hook 內三個規格碼 |
| speaking 訊號 | 無 | `onspeechstart/end` |
| `listening` 何時 true | `start()` 前樂觀設 | `onstart` 事件 |
| 型別 | `window as any` | 完整結構型別 |

### A.4 引擎選擇與 UI 文案

決策差異見 §0 的表。UI 同狀態文案對照：

| 狀態 | app（輸入框 placeholder） | admin（按鈕內文字） |
|---|---|---|
| 啟動中 | 麥克風啟動中… | 麥克風啟動中… |
| 辨識中（沒在收音） | 辨識中，請稍候… | 辨識中… |
| 按鍵錄音收音中 | 收音中…講完請再按一次麥克風送出 | 收音中 · 再按送出 |
| 連續、偵測到講話 | 聆聽中…講完會自動送出 | 聆聽中... |
| 連續、安靜 | 收音中…請直接說話 | 等待語音 |
| 不支援 | 按鈕 disabled | 按鈕不渲染 |

引擎名稱表：app `App.vue:684-690` 只有 label；admin `asrEngines.ts` 有 label + note。
五個 label 字串相同。

### A.5 WAV／PCM

`encodeWav` 兩邊輸出逐 byte 相同（標頭欄位、clamp、非對稱縮放、little-endian）。
`rmsVolume`（含 3.4 增益）、線性插值重採樣各有一份，算法相同。

### A.6 TTS

| | app | admin |
|---|---|---|
| 形態 | 一輪對話一段串流，與打字機同步 | 每則訊息一個播放鈕，LRU cache + prefetch |
| 取樣率 | 從 WAV `fmt` 偵測 | 讀 `rate=` 否則假設 48000 |
| 串流重採樣 | 有（`createStreamingResampler`） | 無 |
| 奇數 byte 跨 chunk | 有 | 無 |
| provider+voice 驗證 | 當一組 | 只驗 provider |
| fallback header | 不讀 | 讀了但畫面寫死「Edge TTS」 |
| 請求格式 | `{text, character}` 或 `{text, provider, voice}` | `{text, provider?, voice?}` |
| 中斷 | cancel reader + abort + flush 排程 + 清打字機 | abort + 停 `<audio>` + 清 mascot |

### A.7 已有的共用機制

- `contracts/`：admin 透過 alias + tsconfig paths + include 消費 9 個檔案；app 設了
  alias 但**零 import**。兩個 Dockerfile 都 `COPY contracts /contracts`；compose
  dev 有 bind mount。
- 無 pnpm workspace、無根 `package.json`、三份 lockfile。
- `frontend/avatar-sdk` 以 build 產物被 COPY 進 admin nginx，不是 source 依賴。

## 附錄 B：順帶發現、不在本計畫範圍

- `frontend/app` 正式環境跑的是 `pnpm dev`（Vite dev server），不是 production
  build（`frontend/app/Dockerfile` 最後一行）。HMR client 還在、無 minify。admin 有
  `target: runner` 走 nginx，app 沒有。應該不是故意的，但改它會換掉整個服務的執行
  方式，要另外決定。
- 部署後開著舊分頁的使用者點到還沒載入的頁面會白屏（chunk hash 對不上），只在
  console 留一行 `Failed to fetch dynamically imported module`。標準做法是攔截
  這個錯誤自動重載一次。兩個前端都缺。
- 後端 `ingestion_audio.py` 對小米只用非串流的 `/transcribe`；小米另有
  `/transcribe/stream`（SSE，`data: {"type":"token","text":...}`）可逐字串流。
  三個引擎裡只有它支援。見 §4。
