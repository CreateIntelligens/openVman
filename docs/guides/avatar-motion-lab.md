# 角色動作測試頁

測試入口為現有站台的 `/experiments/avatar-motion/`，由 avatar 靜態服務提供，經既有 nginx 對外。此入口為獨立技術預覽；正式 Vue 前台的限定人物試用見下方「接入正式 Vman」，嵌入 widget 與 Avatar SDK 公開介面維持既有契約。

預覽原始碼在 `frontend/app/public/experiments/avatar-motion/`，Vite 建置時隨 `public/` 複製進 avatar 映像，和前台一起經 CI 與 watchtower 部署；修改後需重新建置映像。驗證使用實際提供給使用者的網址。

## HCIOT 素材與對嘴資料

目前使用 `.design/hciot-motion-clips/` 的四支 1080×1920、30 fps、8 秒 MP4。來源音軌為靜音，轉檔時移除。

| 控制項 | 來源 | 封裝時間軸 | 播放行為 |
|---|---|---|---|
| 待機 | `waiting-command.mp4` | 0–8 秒 | 循環 |
| 思考 | `thinking.mp4` | 8–16 秒 | 循環；此時不播放測試語音 |
| 說話 | `waiting-command.mp4` | 0–8 秒 | 以穩定、未遮嘴的畫面對嘴，音訊結束回待機 |
| 比心 | `idle.mp4` | 16–24 秒 | 完整播放一次，再回待機 |
| 道別 | `bye.mp4` | 24–32 秒 | 完整播放一次，再回待機 |

`idle.mp4` 中段會比心，故介面以實際動作命名，待機及說話採 `waiting-command.mp4`。四片首尾皆回到接近雙手腰前的姿勢；表情與頭姿仍有微小差異，手動在動作中段切換也會看見姿勢差異。

準備素材：

```bash
bash frontend/app/scripts/prepare-hciot-motion.sh
# 可選擇其他來源目錄（檔名及規格須相同）：
# bash frontend/app/scripts/prepare-hciot-motion.sh /path/to/clips
```

腳本只傳入上述四支影片，並在既有 `avatar-pipeline` 容器內處理；輸入副本留在已忽略的 `/data/avatar-jobs/motion-lab-hciot-v1/`。需要容器已設定既有的 `AVATAR_BUNDLE_KEY`。每片正規化為 25 fps、200 幀；各自擷取特徵點、平滑、計算裁切框與姿態，避免相鄰動作互相影響幾何資料。四段使用共用臉部模板，封裝為 800 幀／32 秒的 VP9 影片及對應的 `combined_data.json.gz`，同步標記以整份封裝的幀序重新寫入。動作起點設為關鍵幀，並檢查全部幀的標記、幀數與起點關鍵幀。

產物安裝到 `/data/avatar/0624/motion-lab/hciot-v1/`：

- `01.webm`：1080×1920、25 fps、無聲 VP9。
- `combined_data.json.gz`：新人物的專屬逐幀資料與加密裁切資訊。
- `manifest.json`：來源 SHA-256、規格、動作時間軸。

安裝先在同一檔案系統完成驗證，再原子發布目錄；已存在且來源相同時略過，來源不同需使用新版本目錄。原始 `0624/01.webm`、舊 JSON 與來源 MP4 均保留。產物經既有 `/static/characters/0624/...` 權限檢查提供，未複製到公開靜態目錄；本預覽沿用能讀取 `0624` 的帳號權限。

頁面先檢查登入及新資料包存取權限，再驗證 manifest 的版本、規格及時間軸，預載完整影片後才初始化 SDK，避免整檔預載與 SDK 的媒體 Range 請求同時進行。預載失敗時會說明錯誤，且尚未消耗一次性的 runtime。SDK 使用 `characterId: "hciot-v1"` 與 `assetsBaseUrl: "/static/characters/0624/motion-lab"`。四段共用同一個 runtime；切換維持新資料包的原始時間與幀索引。預覽使用局部堆疊層級，確保交接遮罩與狀態標籤顯示在 SDK 畫布上。

## 快取與交接

載入時將影片完整存入同一份 Blob URL，並初始化一次 SDK。就緒後切換與循環不重新請求影片、JSON 或 WASM。另預備最多三個停在區段起點的待命播放器，加上一個正在播放的播放器。命中時直接交給既有 WASM；換下來的播放器在背景跳回起點，準備下次循環。快取未命中的動作會在既有待命播放器中準備，播放器數量維持上限。

瀏覽器提供的 `navigator.deviceMemory` 不超過 4 GiB 時，待命上限降為兩個；未提供資訊時使用三個。無法建立待命解碼器時退回單播放器，仍使用已下載的 Blob。離頁會中止準備、清除播放器及釋放 Blob。此上限不代表已測得實體手機記憶體用量。

快取準備期間維持原動作，實際交接時才保留上一張畫面；確認 WASM 已繪製新播放器的畫面後，以 180 ms 緩進緩出淡化，再回填舊播放器。錄影也記錄同一淡化，中途切換保留當下可見的合成畫面。頁面詳情顯示命中次數及完整交接時間。`motionDemo.snapshot()` 包含 `source`、`segments`、`videoCache` 的 `hits`／`misses`／`entries`／`maxEntries`／`pending`（數量不含正在播放者），以及交接的 `cacheHit`／`prepareMs`／`renderMs`／`ms`。`ms` 包含準備、WASM 畫面與淡化完成。

「自動示範」播放待機、完整比心、思考、說話、完整道別，再回待機，約半分鐘。停止或手動切換會取消舊流程。比心與道別也可隨時手動中斷；正常播完會回待機，不會重複揮手或比心。

## 音訊、錄影與登入

`sample.wav` 為預先準備的 16 kHz 單聲道語音：「我正在測試動作切換，現在開始說話。」，以 Edge TTS 的 `zh-TW-HsiaoChenNeural` 產生。開頁不呼叫 TTS、聊天或設定寫入 API；選取的本機音訊也只留在瀏覽器。

「開始錄影」以 `MediaRecorder` 記錄實際 SDK 畫布與聲音。只有此獨立頁面會攔接 AudioNode 至錄音軌；停止後可下載 WebM，上限兩分鐘。需以使用者按鈕啟動音訊。

未登入時提供「登入 Vman」連結；在同站台的登入分頁完成登入後，回測試頁按「登入後重新檢查」，再載入角色。帳號無權存取、資料遺失或連線失敗時，會在 WASM 啟動前說明。頁面未內建帳密或金鑰。WASM 初始化失敗時使用「重新載入測試頁」，避免同文件重新初始化已處置的 runtime。

## 驗證

```bash
cd frontend/app
pnpm test
pnpm build
```

控制器測試涵蓋最後一次請求優先、原始時間軸循環、單次動作完成、取消、跳轉逾時及播放失敗；另驗證快取重用與上限、失敗退回單影片、manifest 拒絕錯版本或錯時間軸，以及登入恢復。

部署後執行真實 Chrome E2E：

```bash
BASE_URL=https://localhost:8787 \
MOTION_TEST_USERNAME='<測試帳號>' \
MOTION_TEST_PASSWORD='<測試密碼>' \
MOTION_ARTIFACT_DIR=/tmp/openvman-motion-e2e \
node frontend/app/scripts/e2e/avatar-motion.mjs
```

`BASE_URL` 預設為 `https://localhost:8787`；`MOTION_CHROME_PATH` 預設 `/usr/bin/google-chrome`。需已安裝 `playwright-core`，可使用全域 agent-browser 套件，或以 `MOTION_PLAYWRIGHT_PACKAGE` 指定其 `package.json`。`ffprobe`／`ffmpeg` 用於檢查錄影音軌。

E2E 包含匿名登入引導與同頁登入恢復、真實 SDK／WASM、canvas 像素及動作時間軸、320／375／414／768／1440 排版、循環、比心與道別播至尾段後回待機、快速切換、完整示範及非靜音錄影、停止後取消舊流程。就緒後要求素材請求數與 SDK／WASM 初始化次數維持不變。

另包含兩個獨立情境：375 寬／觸控／回報 2 GiB 記憶體的有界快取，以及待命解碼失敗退回單播放器。只重跑這兩個情境可設 `MOTION_CACHE_FOCUSED_ONLY=1`。瀏覽器模擬不能取代實體手機、實體喇叭或麥克風測試。

此獨立預覽使用既有 SDK 載入測試資料包，尚未提供正式動作包上傳或對外 SDK 動作 API；正式 Vue 前台的限定人物接線見下節。

## 接入正式 Vman

正式 Vue 前台可選擇 `HCIOT 醫院動作試用`（`hciot-motion`），動作設定只在元復醫院與創造智能醫院衛教助理兩個專案啟用。兩案的專案 ID 定義在 `frontend/app/src/composables/avatarMotionProfile.ts`，安裝與 E2E 腳本以環境變數帶入同一組 ID。

此人物歸屬元復醫院，透過既有專案資源指派分享給另一院，素材保持受保護；兩案的預設人物均指向它。安裝會保留原資源清單與其他政策，只新增此人物及更新人物預設值。使用者已儲存的人物偏好優先，需在設定選取新人物；不覆寫個人偏好。

角色的一般 `01.webm` 與 JSON 是 waiting-command 前 200 幀的中立 8 秒底片。SDK、嵌入 widget 與其他專案可依原本的載入契約使用中立底片。正式 Vue 前台的允許專案則載入 `/static/characters/hciot-motion/motions/hciot-v1/` 完整動作包；缺少或不符規格時回到中立底片。正式 API 與 Avatar SDK 公開介面未增加動作參數。

動作控制：

- 對話等待或 TTS 尚在合成時播放思考；實際語音播放及其首段準備優先於思考。
- 首段 PCM 先等中立說話畫面交接完成，再交給原音訊排程器播放。停止、斷線或換訪客時取消這段等待，舊音訊不會在稍後恢復。
- 比心及道別按鈕只在這個人物的動作試用啟用時顯示；回答期間停用。正常播完回待機，也可由新對話中斷。
- 換人物、切 3D、離頁會停止循環、釋放待命影片與 Blob、還原 canvas 攔接；同人物換專案也重新核對動作範圍。

正式 Vue 前台交接會在待命影片準備完成前繼續播放原動作，實際換播放器時才保留畫面。新播放器經 WASM 繪製後，以 180 ms 緩進緩出淡化；舊播放器的跳轉回填延到淡化結束，避免與第一幀解碼競爭。中途取消淡化時保留當下可見的合成畫面，不跳回較早的完整姿勢。待機與說話共用 0–8 秒底片，兩者只改邏輯狀態、不換播放器或歸零；正常循環仍會回到區段起點。獨立預覽也使用同樣的 180 ms 遮罩交接。

背景回填完成或失敗會通知 Vue 更新快取狀態，避免「準備中」計數停留在舊值；這個通知不阻擋淡化或音訊排程。

揭幕前先透過 `requestVideoFrameCallback` 確認解碼幀的 `mediaTime` 位於目標片段，再等待其後一次 WASM 畫面；`play()` 成功或繪製來源是同一個 video 元素，均不能單獨當成新片段已解碼的證據。可取消／逾時，舊片段的回呼不會提早揭幕；不支援此 API 的瀏覽器使用 RAF 檢查 readyState／跳轉狀態作較弱的降級。

2026-10-22 晚間使用者釐清的「畫面瞬間閃一下」與前述姿勢跳接是不同問題，不能把淡化改善當成閃爍已修復。`MOTION_FLASH_CAPTURE=1 MOTION_IMMERSIVE=1` 可在正式 E2E 額外保存畫布 alpha／亮度樣本與 CDP 螢幕合成幀。`/tmp/openvman-motion-20261022/flash-before/` 這輪的 1,250 筆畫布樣本皆不透明，201 張合成幀未觀察到整體亮暗跳變；這只是未重現，不足以排除使用者裝置上的單幀、局部嘴型或 GPU 合成閃爍。解碼幀檢查屬交接正確性補強，並非已證實的閃爍根因修復。

補上解碼幀檢查後，`flash-after/report.json` 的正式全螢幕有聲／停止／人物回切八項通過，另存 1,447 筆畫布樣本與 245 張合成幀；樣本皆不透明，仍未重現使用者所指的瞬間閃爍。前端共 409 個測試通過。全螢幕輸入區另在 `/tmp/openvman-fullscreen-chat/deployed/report.json` 完成 12 項實際部署 E2E：九種尺寸、真實送出／停止、訊息紀錄及長文字錯誤提示樣式，39 張截圖可回看。`deployed-attempt1/` 保留首次串流中斷的失敗；重測的手動停止只有預期的 fetch abort，沒有同樣的斷線提示。實體手機鍵盤與使用者原本瀏覽器的閃爍仍未驗證。

使用者後續確認是「整頁黑閃」，診斷範圍已擴到整頁。`MOTION_FLASH_CAPTURE=1` 也會保存 `pageEvents`，記錄全螢幕、可見性、頁面生命週期、WebGL context 事件與整頁遮罩／App 是否存在；加上 `MOTION_FLASH_CHAT_ONLY=1` 可只跑正式真實對話及停止。`full-page-flash/report.json` 的第一輪實際思考／有聲回答通過，第二輪 `/v1/audio/speech` 與 `/api/v1/chat/stream` 遇到 `ERR_NETWORK_CHANGED`，測試逾時，整份報告保留失敗。這輪 1,800 張整頁合成幀沒有整頁黑畫面，對話期間沒有額外全螢幕切換、整頁遮罩或頁面卸載事件；既有兩輪 201／245 張也已重新檢查整頁。這些紀錄仍不足以排除使用者裝置的螢幕合成問題，不能宣稱黑閃修復。

2026-10-23 依「kiosk 較明顯」補測本機 Chrome 的 2160×3840 直向全螢幕。正式 E2E 的 `MOTION_VIEWPORT_WIDTH`／`MOTION_VIEWPORT_HEIGHT` 可指定 viewport，`MOTION_DEVICE_SCALE_FACTOR` 預設 1，`MOTION_DEVICE_KIOSK=1` 會透過設定中的「切換成展示機台」及開始畫面進入訪客模式。搭配前述 capture／chat-only／immersive 旗標執行；錄影維持長寬比，最高 1440×1920，避免錄影本身無限制放大。`/tmp/openvman-motion-20261023/kiosk-4k/report.json` 四項通過，無非預期網路失敗或 page error，記錄 166 張整頁合成幀。

逐幀分析保存在 `/tmp/openvman-motion-20261023/frame-analysis/`，含原始幀、CSV、亮度曲線、逐幀縮圖及四倍無聲慢放。一般全螢幕切換片段拆出 38 幀，4K 直向片段拆出 59 幀，均保留原錄影的 25 fps（包含重複幀）；同時以 CDP 的 wall clock 對齊動作狀態及淡化，錄影剪輯時間僅近似對齊。比較整頁、人物、牆面與工具列區域，未見整頁黑幀，兩輪 4K 切換的背景與工具列亮度保持穩定。4K 在雙重擷取下的完整交接等待約 1.17–1.24 秒，一般案例約 0.42 秒；這包含準備與淡化，不能當作純播放器效能比較。4K 的 CDP 擷取有約 200–250 ms 間隔，整輪最大間隔約 3 秒，25 fps 錄影亦非每次螢幕刷新都記錄，不能以此排除現場短暫黑閃。尚需使用者現場 kiosk 的系統／瀏覽器資訊與實際黑閃片段；未據此更改正式 GPU／圖層策略。一般人物、SDK 與嵌入 widget 不涉及本輪診斷旗標。

連續底片重用由共用播放器的 `reuseContinuousSegment` 選項啟用，預設關閉；正式 session 才開啟。因此獨立預覽的手動切換與格式首輪對照保留原先每次重播起點的行為。

180 ms 淡化比原先 80 ms 多約 100 ms，首段語音仍等這段交接完成後排程。這是降低姿勢閃跳的取捨，不表示完整交接時間縮短；總時間仍包含準備、首個 WASM 畫面與淡化。

這能減少短暫停住及閃跳，但思考中段手在下巴、說話起點雙手放下的姿勢差異仍存在。若需要自然的放手過程，須另準備思考退場／接說話的過渡素材，或在可接受的回應時間內等到匹配姿勢；增加淡化不能產生缺少的動作影格。

交接修正的驗證紀錄在 `/tmp/openvman-motion-20261022/`：`handoff-before/`、`handoff-after/` 保存相同三個思考進度的切換錄影，前後對照為 `handoff-after/comparison.mp4`。前端 408 個測試通過；`handoff-vman/report.json` 為兩院 26 項正式有聲／RWD 檢查通過。最後映像補驗時，元復八項對話／手勢／停止／人物回切檢查通過（`handoff-final-vman/`），創造智能醫院同樣八項以新的瀏覽器程序通過（`handoff-final-chuang/`）。

獨立測試頁同步 180 ms 交接後，`handoff-lab/report.json` 的 16 項聚焦 E2E 全部通過，包含 375 寬／2 GiB 模擬、兩個待命播放器、快取 miss、單播放器降級、循環／單次動作完整播放、不中途重載，以及預載失敗時不初始化 WASM。

補驗沒有全部一路成功：`handoff-final-vman-attempt1/` 保留一次素材下載 `ERR_NETWORK_CHANGED` 後退回中立底片的失敗；`handoff-final-vman/report.json` 整體仍為失敗，因同一瀏覽器程序第二院啟動時只觀察到一幀 WASM 畫面，未能進入動作模式。新的瀏覽器程序測同一部署成功，尚不足以判定前次啟動異常的根因。不能把成功重測當成這個偶發啟動問題已修復，也不能把兩個啟動失敗歸因於姿勢交接。

控制器與快取的共用來源在 `frontend/shared/avatar/motion/`。預覽的靜態副本以 `node frontend/app/scripts/sync-avatar-motion.mjs` 同步；`pnpm check:motion`、build 與回歸測試會拒絕副本分歧。

### 安裝與部署

先準備上一節 HCIOT 動作包，再以環境變數提供有權限的 ROOT 管理員執行：

```bash
MOTION_TEST_USERNAME='<管理員帳號>' \
MOTION_TEST_PASSWORD='<管理員密碼>' \
MOTION_PILOT_PROJECT_IDS='<元復醫院專案 ID>,<創造智能醫院專案 ID>' \
bash frontend/app/scripts/install-hciot-motion-pilot.sh
```

腳本在 `avatar-pipeline` 容器內產生中立底片，經現有 `POST /api/v1/avatar` 登錄受保護的人物、複製動作包，並以既有 assignments／policy API 更新指定專案。Cookie 寫入請求帶同源 Origin，不繞過認證。帳密不寫入檔案。原政策備份留在 `/data/avatar-jobs/hciot-vman-install/<project_id>-policy-before.json`；重跑保留第一份備份。同名人物若屬於其他專案，安裝會停止。

試用版使用獨立本機映像；只對 avatar 容器關閉 watchtower 換版，避免尚未推送的程式被遠端舊映像覆蓋。其他服務維持原設定。一次只跑一個 build，完成後才啟動：

```bash
docker compose -f docker-compose.yml -f docker-compose.avatar-motion-pilot.yml build avatar
docker compose -f docker-compose.yml -f docker-compose.avatar-motion-pilot.yml up -d --no-build --no-deps avatar
```

回到原前台映像及原 watchtower 設定：

```bash
docker compose -f docker-compose.yml up -d --no-build --no-deps avatar
```

映像還原後，已登錄的新人物仍可用中立底片展示。若也要還原專案預設人物，經 policy API 套回上述備份，並保留其他同仁後來更新的政策欄位；人物正在使用時不要刪除資源或素材。

### 正式對話 E2E

```bash
BASE_URL=https://localhost:8787 \
MOTION_TEST_USERNAME='<測試帳號>' \
MOTION_TEST_PASSWORD='<測試密碼>' \
MOTION_TEST_PROJECT_IDS='<元復醫院專案 ID>,<創造智能醫院專案 ID>' \
MOTION_ARTIFACT_DIR=/tmp/openvman-motion-vman \
node frontend/app/scripts/e2e/avatar-motion-vman.mjs
```

這份腳本驗證正式前台的真實聊天、TTS／AudioContext 輸出、對話動作切換、手勢、停止取消、換人物／回切、五種寬度與角色就緒後不重載，另保存實際 UI＋音訊錄影。它隔離測試帳號的遠端偏好 PUT，使用者的個人選擇維持原樣，因此不驗證偏好持久化；不偽造聊天或 TTS 成功。實體手機與實體喇叭／麥克風仍需另驗。

前台全螢幕對話輸入列另有獨立 E2E，驗證實際 fullscreen、五種寬度與短高畫面、真實送出／停止及操作區遮擋；同樣隔離遠端偏好寫入，未涵蓋實體手機鍵盤：

```bash
BASE_URL=https://localhost:8787 \
MOTION_TEST_USERNAME='<測試帳號>' \
MOTION_TEST_PASSWORD='<測試密碼>' \
node frontend/app/scripts/e2e/avatar-fullscreen-chat.mjs
```

2026-10-22 已在上述兩案完成實測：320／375／414／768／1440 寬度、兩次真實對話、比心／道別完整播放、停止後取消舊音訊，以及一般人物與試用人物回切皆通過。首段實際語音出現時已切到說話狀態；每案全程只初始化一次 SDK／WASM。E2E 的專案選擇走正式設定 UI，不以 `?project_id` 當成已支援的前台切換契約。結果與實際有聲 MP4 保存在 `/tmp/openvman-motion-20261022/vman/`；元復的五種寬度證據在同目錄首輪報告，其餘檢查在最終報告。

## WebM／MP4 混播效能對照

`frontend/app/scripts/e2e/avatar-motion-formats.mjs` 使用真實 SDK／WASM，分別執行全 VP9 WebM、全 H.264 MP4，以及待機／說話用 WebM、思考／比心／道別用 MP4 三組。每組固定四個播放器、相同時間軸、控制器、80 ms 淡化與動作流程；混播組兩個 WebM、兩個 MP4，各播放器只設定一次 Blob 來源。這是獨立的格式快取實驗，正式兩院人物目前仍使用 WebM 與原本的 `MotionVideoCache`。

前置條件為已安裝正式試用人物，以及完整動作包目錄內的 `01.mp4`：1080×1920、25 fps、800 幀、H.264／yuv420p、無音軌，0／8／16／24 秒為關鍵幀。MP4 必須保留 WebM 的所有逐幀同步標記，沿用同一份 JSON；轉檔與檢查須在 `avatar-pipeline` 容器內完成，不能只換檔名或使用原始 30 fps MP4。2026-10-22 的測試副本已逐幀檢查 800 個標記。

```bash
BASE_URL=https://localhost:8787 \
MOTION_TEST_USERNAME='<測試帳號>' \
MOTION_TEST_PASSWORD='<測試密碼>' \
MOTION_ARTIFACT_DIR=/tmp/openvman-motion-formats \
node frontend/app/scripts/e2e/avatar-motion-formats.mjs
```

預設依序執行 1440 與 375 寬度的三組情境。`MOTION_FORMAT_VIEWPORTS=desktop,mobile` 與 `MOTION_FORMAT_MODES=all-webm,all-mp4,mixed-state` 可選取子集。效能量測先暖機兩秒，包含正常播放、循環、動作切換及快速取消；錄影另在量測後執行，避免編碼負載混入數據。原始樣本、逐播放器計數、摘要、畫面及混播錄影存於同一輸出目錄。

報告同時列出 `getVideoPlaybackQuality` 的總幀／掉幀、`requestVideoFrameCallback` 的來源幀間距、實際 SDK canvas 新畫面的間距，以及包含淡化的交接時間。連續播放與交接分開計數；總幀計數含待命播放器的解碼／跳轉，不可直接當成觀眾看到的掉幀率。每個來源為 25 fps，不以螢幕 60 Hz 為目標。這份短測每組只跑一輪，375 寬為同一台主機的瀏覽器模擬，不能推論實體手機、Safari 或長時間記憶體表現。

2026-10-22 Chrome 150 首輪結果（正式前台 180 ms 交接修正前），產物在 `/tmp/openvman-motion-20261022/formats/`：

| 情境 | 瀏覽器掉幀／總幀 | 連續 canvas 畫面最大間距 | 連續畫面 >200 ms 次數 | 交接中位數／最大值 |
|---|---|---|---|---|
| 1440 全 WebM | 9／780 | 128.1 ms | 0 | 187／344 ms |
| 1440 全 MP4 | 17／781 | 100.7 ms | 0 | 191／505 ms |
| 1440 混播 | 4／760 | 90.7 ms | 0 | 153／380 ms |
| 375 全 WebM | 7／771 | 96.7 ms | 0 | 140／247 ms |
| 375 全 MP4 | 23／778 | 84.3 ms | 0 | 188／439 ms |
| 375 混播 | 13／765 | 271.1 ms | 1 | 199／430 ms |

混播兩種寬度均實際跨格式切換，未重新初始化 WASM，沒有逐幀標記比對異常；375 組仍有一次可量到的短暫停頓，不可宣稱完全不卡。全 MP4 的 375 組有一筆 rVFC metadata 與當下擷取像素的標記差一幀，保留失敗原始樣本，首輪總報告為 `passed: false`。該比對同時讀取 callback metadata 與 video 當下畫面，尚不能單憑這一筆判定為素材、SDK 對嘴或取樣時序問題；沒有以重跑覆蓋失敗。格式實驗未切換正式兩院的播放來源。

單獨對嘴基準使用同一腳本，設定 `MOTION_FORMAT_MODES=single-lipsync` 與 `MOTION_FORMAT_REPORT_PREFIX=single-report`，保留原六組報告。此模式改載入 `hciot-motion` 原生中立 8 秒／200 幀素材，只建立一個影片播放器、使用原生循環，不建立快取或動作控制器。暖機後持續播放 18 秒測試語音，記錄實際音訊 RMS、AudioContext 排程及 WASM 嘴型貼圖繪製次數，確保量到實際對嘴。量測後另外錄製 8 秒畫面與真實音訊，錄影負載不計入掉幀數據。

同日單獨對嘴兩組皆通過：桌面 449 幀掉 1 幀（約 0.22%）、375 寬模擬 450 幀掉 2 幀（約 0.44%），均沒有 >200 ms 的 canvas 畫面間距；最大值為 125.6／130.8 ms，p95 為 48.4／48.8 ms。每案只有一個 video，實際語音排程 18 秒且 AudioContext 為 running；嘴型貼圖繪製與非零音訊 RMS 已驗證。此結果表示單純對嘴仍可能少量掉幀，沒有在這次短測觀察到長停頓，不代表所有裝置或長時間播放都能零掉幀。原始資料與有聲短片在同一產物目錄，摘要為 `single-report.json`／`.md`。

`frontend/app/scripts/e2e/avatar-motion-handoff.mjs` 是交接專用錄影探針：用真實 SDK 預載完整的 800 幀 JSON，再載入目前的正式 motion session 原始碼，分別在思考約 1.2／3.5／6.5 秒後切到說話並播放測試語音，保存實際淡化合成影片與逐格像素變化。設定 `MOTION_ARTIFACT_DIR` 可保留修改前後兩份產物。此探針沒有正式 Vue 對話狀態機，不能替代前述正式兩院有聲 E2E；錄影本身有負載，也不是效能比較基準。
