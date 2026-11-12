# 人物渲染程式替換候選

獨立實驗，保留人物影片、外觀、動作及模型，重新實作渲染程式。來源與仍保留的相容關係見 [PROVENANCE.md](PROVENANCE.md)；計畫維持 [Draft](../../../docs/plans/avatar-source-decoupling.md)，畫質尚未經使用者接受。正式前台與既有候選不會自動切換。

各節依時間排列，舊節描述當時狀態：v2初版的六維位移與牙齒圖集、以v1當左欄及三欄的比較頁都已被取代。現況看最後一節「嘴型校準與畫面驗收」。

```bash
cd scripts/experiments/avatar-renderer-next
pnpm install --frozen-lockfile --ignore-scripts
python3 install.py
```

`install.py` 從官方鎖定套件組裝靜態包，寫入既有 `openvman-avatar-1` 的 `/usr/share/nginx/html/experiments/avatar-renderer-next/`，逐檔核對 SHA-256。補齊容器 nginx 的 `.mjs` MIME 對應並 reload；不開新埠。既有容器重建會移除此實驗，需重跑安裝。

預覽入口：`https://<預覽主機>:8787/experiments/avatar-renderer-next/`。按「播放測試語音」以 40ms PCM 分塊供料，停止會取消目前世代並歸零；定格按鈕以同一影格比對中立及開口。失敗直接顯示錯誤，沒有舊引擎備援。首次播放須符合瀏覽器使用者手勢要求。

`loadCharacter(base)` 讀取本目錄既有角色資料，`CharacterBinding.update(frame, controls)` 產生標準位置、法線、材質與位移欄位；`SurfaceRenderer.render(geometry, skin)` 只負責 GPU 合成。串流控制介面為 `beginStream / appendPcm / endStream / stop / dispose`，輸入僅 16kHz、mono、Int16 PCM，包含世代、序號及 sample offset 檢查與背壓回傳。這個本機示範沒有對外 API，也沒有認證或遠端 fallback。

## 2026-11-04 本機驗證結果

本輪驗證為 Chrome／NVIDIA RTX A4000、既有單一人物、5 秒串流，並非正式產品或手機驗收。原始結果在 `~/openvman-experiments/avatar-source-decoupling/e2e-final/summary.json`，同目錄保留截圖、參考對照圖與有聲錄影。

- 角色全部 151 個影格產生有限數值；六維正負控制均有獨立響應，缺檔、錯誤牙齒尺寸、非法座標資料明確拒絕。
- 14/14 項既有串流控制器回歸通過，測試改從本目錄讀取真實控制器與 Worker，不再硬寫舊 worktree 路徑。
- 完整音訊送入 80,000 samples，產出 125 步；停止後活動音源為 0、12 維控制與最後實際繪製控制全零。正常播放 300 次活動音訊回呼中，錯誤中立向量為 0。
- 嚴格 URL 白名單未允許請求為 0；兩個禁止資源探針均遭阻斷。參考 renderer 僅在第二個審計瀏覽器明確注入，不在部署包或正式播放測試中。
- 5 秒錄影為 1,419,791 bytes，實際解碼有效音訊 5.04 秒、RMS 0.08290；這是軟體音畫證據，未測實體喇叭或螢幕 scan-out。
- 整幀 CPU 呼叫（含影片貼回及 GPU 命令提交）p50 3.9ms、p95 6.0ms、p99 7.0ms；不是 GPU 完成時間，亦未重跑新版 10 分鐘長測。
- 固定同影格 50、同控制向量的中立／開口／負值／第三維／真實語音五組對照：180×180 ROI 平均絕對差 0.717～1.242，嘴部 ROI 平均差 1.961～4.496，最大單通道差 71～94。新光照採用自行產生的方向取樣，牙齒陰影仍有差異；**不宣稱與歷史 renderer 逐像素等效**。實際檢視未見臉部裁切、上下顛倒或唇外藍色貼片。
- 320、375、414、768 寬度的實際瀏覽器檢查均無水平溢位。

```bash
node test_character.mjs
node test_streaming.mjs
python3 verify_e2e.py --out ~/openvman-experiments/avatar-source-decoupling/recheck
```

可選的 `--reference /path/to/avatar-renderer.mjs --reference-samples /path/to/samples32.json` 僅用於獨立歷史對照。參考檔刻意留在交付包外，不是執行依賴。驗證工具需本機 `playwright`、`numpy`、`Pillow`、Google Chrome 與 ffmpeg，不會在安裝時自動下載測試工具。

## 相依盤點及未完成邊界

依 `install.py` 實際組裝內容產生的 SPDX、PDF、逐檔雜湊與限制說明，在 `~/openvman-experiments/avatar-source-decoupling/sbom/`。鎖檔的 18 個相依名稱及版本與 SPDX 比對一致；其中官方 ORT web/common 為 1.30.0。**OSV 未查詢，PDF 顯示零漏洞不能當成查無漏洞。** 此盤點也不涵蓋 nginx／容器 OS／正式前台。

第三方引擎不是零依賴；瀏覽器需要下載模型。來源揭露文件仍明文提及原系統；資產、資料契約及模型來源不能只憑套件數或關鍵字掃描判定。`avatar-pipeline/pipeline/geometry.py` 與 `landmarks.py` 仍揭露上游移植關係，正式前台仍使用原 runtime。本輪沒有替換這些產品入口或產製程式，不宣告整個專案僅剩模型權重具有原來源關係。

## 第二階段正式程式整合（2026-11-05）

本目錄原 Demo 保留為第一階段基線；正式 Vue／SDK 現在改接 `frontend/shared/avatar-engine/`，產製程式亦已更新。上一節「正式程式未改」描述的是第一階段，不是本分支最新狀態。範圍、測試、來源與待驗收項目統一更新於 [來源拆分計畫](../../../docs/plans/avatar-source-decoupling.md)。

新的公開整合預覽為 `https://<預覽主機>:8787/experiments/avatar-integration/engine.html`，可播放、停止與切換兩個人物；它使用與正式整合相同的共用引擎，不載入舊 runtime。完整 Vue 映像的登入頁預覽為 `/experiments/avatar-product/`；它仍使用真實帳號授權，不繞過登入。正式站根入口尚未切換。

```bash
# 先後建置，不與其他 Docker build 並行。
docker compose -p openvman-source-preview -f scripts/experiments/avatar-renderer-next/compose.integration.yaml build avatar-preview
docker compose -p openvman-source-preview -f scripts/experiments/avatar-renderer-next/compose.integration.yaml up -d --no-deps avatar-preview
pnpm --dir frontend/avatar-sdk build
python3 scripts/experiments/avatar-renderer-next/publish-integration-preview.py
python3 scripts/experiments/avatar-renderer-next/verify-integration.py --out ~/openvman-experiments/avatar-source-decoupling/integration-recheck
```

上述命令從 repo 根目錄執行。Compose 預覽服務只加入既有 `openvman_default` 網路，不開公用埠；瀏覽入口經現有 edge proxy。`publish-integration-preview.py` 只新增預覽頁、共用 runtime 與帶 hash 的靜態資源，不替換正式根 `index.html`。舊人物需先由既有 pipeline 容器執行 `python -m pipeline.render_data --directory /data/avatar` 新增 sidecar，或部署新 Backend 後由原授權路由轉換；不要改原包或重設 bundle key。

正式前台 build 產生的 `avatar-engine/manifest.json` 含逐檔 SHA-256。新的掃描見 `~/openvman-experiments/avatar-source-decoupling/integration-sbom/`：包含實際映像與正式 SDK，與第一階段候選 SBOM 分開；人物來源、相容 profile、`matesx:` 識別碼及 VAD 外部 runtime 仍如實揭露。


## 第三階段：自產幾何資產 v2（2026-11-05）

本目錄原獨立候選與第二階段v1預覽保留作明示的比較基線。新的共用引擎從己方影片重新追蹤內外唇，程序產生網格、六維位移、牙齒／口腔圖集及融合遮罩，不讀原模板或rig；音訊ONNX與第三方MediaPipe仍保留來源。v1人物須重新產製v2，不能只改schema字串。

新版獨立入口：`https://<預覽主機>:8787/experiments/avatar-own-rig/`。
並排對照：同路徑 `compare.html`；左側明確載入第二階段v1保留資產版，右側為自產v2，只有右側播放聲音。它不是原ncnn引擎效能基準。正常新版入口不載入左側依賴。

```bash
# 在既有具MediaPipe的容器內，僅讀己方影片，輸出至隔離目錄。
python -m pipeline.video_lips --video /path/to/01.webm --output /isolated/render_data.json.gz
# 正式產製映像也採白名單模組，排除模板、profiles與legacy幾何模組。
docker compose -p openvman-own-rig -f scripts/experiments/avatar-renderer-next/compose.own-rig.yaml build producer
# 下一個build必須等上一個結束。
pnpm --dir frontend/app build
pnpm --dir frontend/avatar-sdk build
python3 scripts/experiments/avatar-renderer-next/publish-own-rig-preview.py \
  --render-data /path/to/render_data.json.gz --manifest /path/to/deployment-manifest.json
python3 scripts/experiments/avatar-renderer-next/verify-integration.py --own-rig --out /path/to/e2e
python3 scripts/experiments/avatar-renderer-next/benchmark-own-rig.py --out /path/to/performance
```

`publish-own-rig-preview.py`只新增／更新`experiments/avatar-own-rig/`及該公開實驗prefix的CORS／無快取規則，不覆寫正式根頁、原人物或其他實驗。必須先prepare/build，部署清冊逐檔列SHA。SDK的可選`runtimeBaseUrl`讓隔離引擎不借用正式資源目錄；不變更聊天API、cookie／Embed授權或人物讀取權限。

畫面與效能驗收使用同一人物影片及音訊，分開記錄整幀CPU提交耗時、非同步WebGL timer GPU耗時、distinct影片FPS、間隔、首音排程、Chrome程序CPU／記憶體。GPU timer無法使用或發生disjoint時必須如實記錄；記憶體量測非驅動VRAM、不是長時間洩漏證明，首音不是外部喇叭量測。各次硬體、版本雜湊、原始樣本與完整數據保存在外部`own-rig/`證據目錄；不得沿用舊127/149或舊長測結論。


### v2本輪交付實測

環境為本機RTX A4000／Chrome，720×1280同影片與相同30秒PCM；每版本各3次、每次全新瀏覽器，順序交錯。表格採各次統計值中位數，CPU為整個Chrome程序群的單核心百分比。這是保留rig的上一版共享引擎v1與自產v2比較，不能稱為原ncnn引擎比較。

| 項目 | v1保留資產 | v2自產資產 |
|---|---:|---:|
| 網格頂點 | 3700 | 480皮膚＋82口腔 |
| 嘴型三角形 | 6224 | 880（另有2個底圖三角形） |
| CPU繪製提交p95 | 7.45ms | 7.10ms |
| GPU合成p95 | 0.644ms | 0.460ms |
| Chrome CPU | 107.3% | 95.7% |
| 有效影片FPS | 24.81 | 24.81 |
| 首音排程 | 101.4ms | 109.5ms |
| 播畢程序PSS | 742.3MiB | 745.3MiB |

三組新版最大影片間隔93.4ms，未出現500ms停頓；GPU計時無disjoint樣本。CPU提交包含JS／Canvas與GPU命令，GPU時間是非同步timer query，不以gl.finish阻塞。記憶體只代表短測程序PSS，不能宣稱排除洩漏；readyMs包含不同初始人物路徑，沒有拿它宣稱冷啟動加速。

來源／產製驗證：最終產製映像實際成功產生151幀v2包，刻意不提供assets／profiles；新包只含render_data，sidecar權限0644。相同影片重跑兩次gzip逐byte相同。26份既有人物／動作全長重產共7612幀全部成功，26份原影片SHA全數不變，資料只留於隔離/tmp與外部驗收目錄，未覆寫正式資料。

最終檢查：產製完整125／125、Vue完整420／420、SDK完整59／59、共享引擎47／47、沿用串流14／14；Backend完整1832通過2跳過後，新增幾何退化防護之focused35／35通過；Admin進度文字相關9／9。直接引擎與跨站SDK實際有聲E2E各只建立1個AudioContext，80000 samples只排程一次、結束／停止全零，URL白名單兩個禁止探針全攔截，未允許請求0。並排頁明示建立兩個獨立引擎作比較，但總音訊仍只排程80000 samples一次。

真實GPU檢視示範女角、男角、透明女角及安全帽全身角色，正負六維與極小控制無錯位或零值跳變；後三者透過本機fixture回應測試，並非正式私有人物授權流程。影片外觀保留，但新形變模型的嘴型輪廓、開口量及牙齒呈現與v1有差異，不主張逐像素相同。

實際交付逐檔HTTP內容與MIME核對、來源／映像SHA、原始6組效能樣本、同影格圖與有聲對照錄影，位於 `~/openvman-experiments/avatar-source-decoupling/own-rig/`。其中`comparison/`保留可直接看的圖及VP8＋Opus錄影；`comparison-summary.json`為公開實測摘要。舊`integration-sbom/`是v1映像的歷史報告，不能直接稱為這次v2交付掃描。

本輪完成獨立候選，正式站、正式人物上架、登入對話／Admin實際試用與手機／展示機、v2新版10分鐘長測沒有據此宣告通過。Live2D另有自己的第三方素材與授權邊界，沒有被本次人物rig替換涵蓋。計畫維持Draft，未push／合併main。


### 使用者畫面複驗後的修正（quality-r2）

使用者指出v1未播放便開口、v2牙齒突出；因此撤回先前對畫面自然度的通過判定。v1實為第二階段重寫候選，其全零仍合成牙齒是缺陷，並非原始ncnn引擎或人物原影片。對照頁保留它以揭露問題，增加原影片欄，三欄共用同一解碼影格，不隱藏或修飾v1的錯誤來冒充原版。

v2修正牙齒映射：圖集高度固定為量測嘴寬的0.22、相對原影片上唇休止位置固定，牙冠不再隨開口高度伸長或跟著上唇移動；UV在片段取樣時才由texture邊界處理，避免先鉗位各頂點導致三角形內部拉伸。同步縮小中央門齒比例、降低亮度，保留有號嘴型位移及零值原影片不變。增加實際UV比例／定位回歸測試，覆蓋5／20／40三種jaw開度。

原三次30秒效能表屬quality-r1，不能當成quality-r2重新完整量測的結果；修正未改網格點數或繪製管線，另作短測確認。原始比較、修正後同影格圖、有聲錄影與測試位於外部own-rig/quality-r2/。畫面仍須使用者實際檢視，不能以像素數或程式PASS宣告更自然。


### 真正原版引擎語音對照（2026-11-05 14:10）

使用者要求原版也實際動嘴，因此`compare.html`中間欄改為真正現行原版ncnn引擎，移除有待機缺陷的v1重寫候選。左欄仍為原影片供檢視人物動作，右欄為新版；原版與新版接收同一份16kHz PCM，各自推論，只由新版播放聲音一次。原版的WebGL畫布依現行SDK保留在可合成區域（透明度0.001）；完全移到視口外會導致深度緩衝未隨合成更新，出現「係數變了但畫面不動」。未修改原版JS或WASM二進位。

原版參考部署在隔離的`/experiments/avatar-native-reference/`，只被明示比較頁的iframe載入，獨立新版入口不載入它。`identity.json`記錄直接從現行容器複製的JS／WASM SHA。為保持同一示範人物，參考包使用原來保存的151幀幾何與歷史模板重新封裝為原格式；這不是原始包逐byte副本，不能宣稱資料也未重封裝，且不作v2產製輸入。金鑰只在既有pipeline容器內讀取，未寫入前端或報告。

`native-reference.ts`沿用現行SDK的待機嘴型bypass及marker修復，包裝原版`_processSecret`／`_setAudioBuffer`。原版不建立有聲播放器；新版首次WebAudio排程時啟動原版推論，停止／播畢清空兩者，非螢幕或聲學硬體層同步保證。先前v1-v2三次30秒效能表不是此原版ncnn比較的效能結果。

```bash
frontend/app/node_modules/.bin/esbuild scripts/experiments/avatar-renderer-next/native-reference.ts \
  --bundle --format=esm --outfile=/path/to/native-reference/reference.mjs
python3 scripts/experiments/avatar-renderer-next/publish-native-reference.py --directory /path/to/native-reference
python3 scripts/experiments/avatar-renderer-next/verify-own-rig-comparison.py --out /path/to/native-reference/e2e
```

上述資料夾需含已核對SHA的原版JS／WASM、同素材相容combined_data.json.gz及identity.json；不使用舊候選的補丁WASM冒充原版。E2E會固定來源影片2秒，量測原版真實uniform與嘴部畫素隨語音變動，排除身體／影片動作干擾；核對20塊、80000samples、同一video物件與唯一有聲排程，留存三欄VP8＋Opus錄影。這一版不再提供把兩種不同模型強制設為同一6D係數的按鈕。


### 兩欄與畫面驗收狀態（2026-11-05 14:36）

依使用者要求移除原影片播放欄，`compare.html`只保留真正ncnn原版與v2，各自對同一句語音計算嘴型、聲音只播一次。測試中的原影片畫素只作離線因果檢查，不顯示在頁面；不改原版或v2引擎的輸出來掩蓋差距。

使用者指出v2與真正原版差距明顯，畫質尚未達替換標準。前述來源替換、可執行、效能與E2E通過均不等於視覺等效或使用者驗收；開口幅度、唇形／閉合、牙齒遮擋與動態細節仍需以真正原版為基準改善。此頁是隔離比較，不能據此切正式站或宣稱畫面完成。

### 六維控制診斷與預覽恢復（2026-11-05）

motion-r3試調增加開口範圍與下顎皮膚連動，仍未達畫質要求。音訊模型六維輸出不等於已確認的標準jaw／smile等控制；目前`character-adapter.mjs`將六維指定給自訂解析位移場，這項對應沒有充分校準。同一影片影格與相同控制向量的瀏覽器介入對照，確認第三維在原版會影響張口、新版卻當作橫向伸縮，因此「六個維度都有非零位移」的測試不足以證明動作正確。原始圖與診斷腳本在外部`own-rig/motion-r3/`；只作診斷，不讀／擬合原形變表來生成新資產。共用引擎48項測試通過不代表這個視覺缺陷已解決。

容器重建會清除暫存預覽目錄；可依上述兩個發布腳本恢復。原版參考的輸入bundle仍為`reference.mjs`，發布時以`reference.js`交付、HTML保留`type="module"`，避免預設nginx將`.mjs`當成`application/octet-stream`而拒絕執行。只寫入隔離參考目錄，正式原版JS／WASM不修改。新版SDK已依motion-r3來源重新build，沒有將歷史Docker映像或舊效能數據當成此修訂驗證。

### 解剖方向修正試作（motion-r4b）

採AGY所提參數化控制的方向，沿用自產網格，不擴成52個通道；不採RBF重取樣原位移表，也不以舊位移回歸新矩陣。AGY腳本僅為舊資產CPU數值診斷，並未比較新基底或實際GPU輸出。方向解釋仍是相容介面的近似，不把它們宣稱為標準FACS權重。

修正第三維由橫向伸縮改為包含上唇上提、第四維由微笑改為上唇下覆；第二維加強收圓、第五／六維各自作空間分布不同的水平牽引。保留有號值與零值原影片，合成後才約束上下內唇接觸。首次motion-r4混合語音張口過大，該版圖像另存；motion-r4b縮小新增位移範圍，仍不宣告自然度通過。共用引擎50項、SDK59項與Vue建置是工程檢查，不能代替畫質驗收。

修正前後短測可在同一頁、相同角色／音訊下，以Playwright僅替換載入的舊版自產adapter，循序啟動全新瀏覽器比較。`before`為motion-r3，`after`為motion-r4b，均非原版ncnn；每次保存實際載入adapter的SHA-256。

當時的量測指令用只替換adapter的 `--baseline-adapter`；這個參數已改為比較完整舊版runtime的 `--baseline-runtime`（見下節）。

本輪不改角色格式、後端授權／產製或Live2D。Vue與SDK使用同一共用引擎；隔離預覽更新，歷史Docker映像不據此宣稱含最新修訂，正式站不切換。

motion-r4b短測結果：每版三次各15秒、循序全新Chrome，修正前後有效影片FPS中位數24.80／24.82，影格間隔p95中位數51.26／50.90ms；CPU單核基準中位數109.6%／102.9%。GPU單幀p95在修正前2.32–2.37ms、修正後0.27–2.33ms間波動，不以這三次短測宣稱GPU加速。網格仍為480個皮膚點及82個口腔點，無新增模型、舊資產或依賴。原始6組資料與載入SHA保存在外部`own-rig/motion-r4b/performance/`；兩版均非原版ncnn，此結果也不代替長測或自然度驗收。

### 嘴型校準與畫面驗收（motion-r5）

根因、決策與來源邊界見[計畫](../../../docs/plans/avatar-source-decoupling.md)與[PROVENANCE](PROVENANCE.md)；嘴型模型的現況說明在[共用引擎README](../../../frontend/shared/avatar-engine/README.md)。

比較頁左為真正原版、右為新版，同一人物同一句語音，聲音只播一次。可切 5 秒與 30 秒語音、中途停止、放大看臉。兩邊都會跟語音動，所以看的是對嘴自然度，不是哪邊比較亮或比較銳利。

```bash
# 從音素語料產生解碼矩陣；語料資料夾為 <聲音>_<音節>.wav（16kHz 單聲道）。
python3 scripts/experiments/avatar-renderer-next/calibrate-mouth-latents.py --model /path/to/model_audio.onnx --corpus /path/to/corpus --out /path/to/calibration

# 建置共用引擎後發布，再產生人看的證據：同影格同係數、全臉、連續嘴部與有聲錄影。
pnpm --dir frontend/app build
pnpm --dir frontend/avatar-sdk build
python3 scripts/experiments/avatar-renderer-next/publish-own-rig-preview.py \
  --render-data /path/to/render_data.json.gz --long-speech /path/to/speech-30s.wav --manifest /path/to/manifest.json
python3 scripts/experiments/avatar-renderer-next/verify-mouth-quality.py \
  --calibration /path/to/mouth-calibration.json --out /path/to/quality

# 舊版要用整個 runtime 目錄比較：adapter、renderer 與 player 是一起改的，只換一個檔載不起來。
python3 scripts/experiments/avatar-renderer-next/benchmark-own-rig.py \
  --baseline-runtime /path/to/motion-r4b/baseline-runtime --groups 3 --seconds 30 --out /path/to/performance
```

比較頁若發布到 `openvman-avatar-1`，下一次正式換版就會被 watchtower 清掉。需要長時間給人看時，改用獨立站台 `compose.own-rig-preview.yaml`（預設 port 8790，HTTPS 自簽憑證，不受 watchtower 更新）。`OWN_RIG_PREVIEW_DIR` 底下放 `html/` 與由 `own-rig-preview-nginx.conf` 複製來的 `default.conf`，`OWN_RIG_PREVIEW_CERTS` 指向含 `openvman.crt`／`openvman.key` 的目錄。檔案與 nginx 設定都在主機目錄，容器重建後仍在。比較頁可用 `?c=<人物代號>` 或頁面上的人物選單切換人物：兩支發布腳本各加 `--character`（新版給該人物的 `render_data.json.gz` 與 `01.webm`，原版給它原本的 `combined_data.json.gz`），原版每個人物發布在 `avatar-native-reference/<代號>/`。

```bash
docker compose -p openvman-own-rig-preview -f scripts/experiments/avatar-renderer-next/compose.own-rig-preview.yaml up -d
python3 scripts/experiments/avatar-renderer-next/publish-own-rig-preview.py --container openvman-own-rig-preview \
  --render-data /path/to/render_data.json.gz --long-speech /path/to/speech-30s.wav --manifest /path/to/manifest.json
python3 scripts/experiments/avatar-renderer-next/publish-native-reference.py --container openvman-own-rig-preview --directory /path/to/native-reference
```

`calibrate-mouth-latents.py` 的輸出是矩陣的起點，引擎內 `DECODE` 的開口列與圓唇c4之後再手動調整；重跑腳本會得到存檔的輸出，而不是引擎的數值，差異列在PROVENANCE。`speech-30s.wav` 由 VoxCPM 合成，是 `own-rig/motion-r5/generate-passage.py` 產出的語音截到31.38秒的停頓處，不進repo。

固定係數的同影格對照只能看形狀；時序要看實播的連續畫面。`verify-mouth-quality.py` 檢查的是結束後回到全零與原影片畫素、中途停止可再次說話、四種寬度沒有水平捲動，並不判定自然度。

本輪效能：同機、全新Chrome、RTX A4000，每版3次各30秒，循序交錯，同一影片與語音，表中為中位數（`own-rig/motion-r5/performance/`）。語音是5秒的 `speech.wav` 循環6次，人物為720×1280示範人物。前者是r4b完整runtime，兩版都不是原版ncnn。

| 項目 | r4b | 新版 | 門檻 |
|---|---:|---:|---:|
| 有效影片FPS（不同影格） | 24.82 | 24.82 | ≥23.75 |
| 影格間隔p95 | 50.9ms | 51.1ms | ≤80ms |
| 最大影格間隔（3次最大值） | 100.7ms | 109.4ms | <500ms |
| Chrome CPU（單核基準） | 84.0% | 84.1% | |
| 整幀提交p50 | 3.8ms | 3.5ms | |
| GPU合成p50 | 0.134ms | 0.155ms | |
| 首音排程 | 78.7ms | 80.8ms | |
| 播畢程序PSS | 710MiB | 708MiB | |

1080p人物另測一次（`--character-dir`，同樣3＋3次），因為合成解析度會隨裁切範圍調高：有效FPS 24.60／24.60，影格間隔p95 51.1／51.0ms，最大間隔124／114ms，CPU 103／101%，GPU合成p50 0.13／0.23ms，全部達標（`own-rig/motion-r5/performance-1080p/`）。

兩組都全部達標，CPU與提交時間持平。提交與GPU的p95同一版本各次就差很多，所以不列。PSS不是VRAM，也不證明沒有洩漏。

載入：音訊模型跑CPU，每40ms一步的推論p50 0.5ms、p95 1.2ms、最大15.8ms（5秒語音、本機RTX A4000工作站），WebGPU沒有效能上的必要，反而要多下載14MB並有GPU讀回延遲（WebGPU版未實測）。所以改用CPU版ONNX Runtime並開gzip：WASM、JS與模型的傳輸量從約31MB降到約6MB，本機就緒時間從約1.8秒降到約1.2秒。ONNX Runtime與模型設24小時快取，引擎程式維持no-cache。之後ONNX Runtime整個換成本專案的WebAssembly推論模組，推論資源剩約2.6MB（加密權重無法壓縮），node實測每步約0.26ms。

測試中曾有一次新版啟動60秒未就緒：伺服器紀錄顯示模型檔已下載，人物資料卻沒有被要求，所以推測停在ONNX Worker初始化，當時機器負載偏高，隨後完整重跑都正常。那段程式本輪未修改，原因未確認；紀錄在 `own-rig/motion-r5/performance-incomplete-run1/`。

本輪在 r4b 上發現並修正：`drawImage(WebGL畫布)` 未先 `flush` 會間歇貼上舊快照，固定係數下464次繪製有25次亮度跳變，加上 `flush` 後為0。所以 r4b 及更早版本的固定係數畫面與錄影都可能混入舊嘴型，舊的畫面判讀要留意。測試只保護呼叫順序，這個現象本身要實機才看得到。
