# 程式、模型與人物資料來源

本檔是揭露清單，不是來源掃描通過證書。2026-11-05 補充：把人像內容、資料抽取鏈、最初作者及所有權分開記錄；格式相容、原 runtime 曾載入某檔，均不足以判定所有權。相關計畫仍為 [Draft](../../../docs/plans/avatar-source-decoupling.md)。

## 2026-11-05：v2自產資產候選

共用引擎目前改用 `openvman.render.v2`。下列步驟不讀原runtime抽出的模板、VBO／IBO、形變貼圖、牙齒圖集、遮罩或heap參考點：

| 資料 | 新來源 | 可重現入口 |
|---|---|---|
| 每幀內外唇與ROI | 己方影片經第三方MediaPipe FaceMesh直接量測，保留浮點xy | `avatar-pipeline/pipeline/video_lips.py`；記錄影片／實作／偵測模型SHA |
| 網格與連接關係 | 20點量測嘴唇環插值為80段，支撐環延伸至不動的ROI邊界 | 共用引擎 `character-adapter.mjs` |
| 六維到嘴型 | 以模型靜音收斂點為零點，3×6有號矩陣解碼成開口、下顎、圓唇，再驅動依嘴寬正規化的解析位移場；畫面未經使用者驗收 | `character-adapter.mjs`；矩陣起點由 `calibrate-mouth-latents.py` 產生，見下方「嘴型校準」；不讀原形變表、不對原表或原版位移做擬合 |
| 牙齒／口腔 | 本專案以牙冠輪廓與著色公式繪製，色彩取自人物當前影格的唇色與臉頰亮度 | `createDentalProfile()`、`renderer.mjs` |
| 融合範圍 | 依各網格頂點可被帶動的程度計算，沒有獨立遮罩圖 | `character-adapter.mjs` 的 `changed` |
| 音訊模型 | 原來源權重明確保留；引擎發布加密後的 `mouth-model.wasm`，明文ONNX與金鑰不在公開repo | 模型逐檔SHA與既有轉換來源紀錄；`tests/mouth-model.test.mjs` 比對參考輸出 |

共用引擎五份 `assets/rig/*.bin` 已移除，前台打包腳本只複製模型與第三方授權；v2產製Docker映像採模組白名單，不包含舊模板／profile或legacy幾何工具。新版上傳包只包含v2 `render_data`，不夾帶舊模板。既有影片／正式資料與凍結候選未因本輪而覆寫。

這是特定資產抽取鏈的替換，不宣稱整包法律clean-room、所有模型均自研或Git歷史已沒有上游痕跡。MediaPipe及其偵測權重、ORT與其WASM、音訊模型契約和原權重、ffmpeg等第三方相依仍須揭露。既有Live2D功能不在本輪替換範圍。

### 嘴型校準

`calibrate-mouth-latents.py` 的輸入是保留的音訊ONNX、既有特徵處理，以及專為校準合成的語音：VoxCPM的6種聲音（`cosy-young-female-01/02`、`cosy-teen-female-01`、`cosy-young-male-01/02`、`cosy-senior-male-01`）朗讀26組重複音節，檔案與SHA-256清單在外部 `own-rig/motion-r5/calibration/`。腳本也寫死兩個屬於保留模型契約的常數：輸出縮放 `SCALES` 與三步延遲 `MODEL_LAG_STEPS`，`LATENT_REST` 與解碼矩陣的尺度都依賴前者。目標是本專案為各音素寫下的發音姿態，寫在腳本的 `PHONETIC_TARGETS`。

同一語料重跑腳本可得到逐byte相同的 `mouth-calibration.json`。擬合是粗略近似，尤其圓唇：留一聲音的平均絕對誤差，開口0.024–0.046、下顎0.017–0.032（嘴寬比例），圓唇0.19–0.28（-1到1）；u的圓唇目標1.0只解出約0.42，捲舌音的符號甚至相反。

引擎裡的數值與腳本輸出不完全相同：

| 項目 | 腳本輸出 | 引擎 | 怎麼來的 |
|---|---|---|---|
| `DECODE.gap` | `[0.00596, 0.00616, 0.00879, 0, 0, 0]` | `[0.0068, 0.0095, 0.0145, -0.002, -0.003, -0.003]` | 看原版對照頁手動調整；前三項不是等比例放大，後三項從擬合貼在界線的0移開 |
| `DECODE.round` 的 c4 | `-0.08807` | `-0.05` | 手動調低，減少說話時整體偏圓唇 |
| `SEAL_MARGIN` | 擬合截距0 | `0.03` | 手動訂定 |
| 追蹤平滑 `SMOOTHING`、靜止嘴縫 `REST_SEAM`、臉部比例 `MOUTH_TO_EYES`／`OPENING_SCALE`、唇厚備援 `NEUTRAL_THICKNESS`、開口上限 `MAX_GAP`、下排牙露出量 `LOWER_TEETH_SHOWING`（0.035） | 無 | `[1,4,6,4,1]`、`0.03`、`0.47`／`[0.6,1.15]`、`0.14`、`0.26`（移除先前的峰值放大） | `MOUTH_TO_EYES` 取範例人物 MediaPipe 量測的嘴寬／兩外眼角距離中位數，使其開口不變；其餘依各人物逐格量測與比較頁畫面手動訂定。原版畫面只作對照，未對其位移擬合 |
| 上排牙邊緣 `dental.upperEdge` | 無（不在擬合範圍） | 靜止 `-0.012`，隨慢速開口上收（係數 `0.45`、起點開口 `0.1`、下顎漸變寬 `0.14`、時間常數 `0.14s`） | 依合成語音逐格畫面手動訂定，未對原版位移擬合 |
| `DECODE` 其餘11項、`LATENT_REST` | | 相同，僅四捨五入 | |

`SEAL_KNEE`、`ANCHOR_BLEND`、`ROUND_GAIN`、`MAX_*`、`FOLLOW_SECONDS`、網格、牙冠邊界與 `renderer.mjs` 的著色常數都是程式內手寫的，沒有逐項來源紀錄，也沒有讀取舊資料。

與原版的關係要分開看。沒有讀取或回歸舊網格、形變表、牙齒圖集、遮罩或位移，輸出也沒有內嵌這些資料。但原版確實影響了結果，而且不只方向：

- 靜音點等於閉口，是用原版的同影格介入確認的。
- `SIGNS` 記錄的正負方向，是單維介入看原版畫面得來的。
- `PHONETIC_TARGETS` 在看過原版對照後改過再重跑，所以連「擬合」的目標也受原版畫面影響。
- 上表的手調數值，以及牙齒露出量、口腔明暗，都是對照原版畫面決定的；開口的幅度因此是校正到接近原版的。
- 調整過程曾把原版嘴部的像素數值印出來看，`verify-mouth-quality.py` 也會讀原版的係數序列來報告兩邊的一致程度。這些都不寫回資料，但不是純肉眼。

所以這裡的「獨立」只表示沒有使用舊資料，不表示數值與舊rig無關；開口增益與舊形變表隱含的方向相近並不意外。不宣稱法律clean-room。

校準資料的限制：只用合成語音，沒有拿真人或真實影片的嘴型驗證。部分影片的音軌是靜音，其餘人物影片沒有音軌，所以不能用。本機另有幾支帶語音的導覽員宣傳影片，人物確實跟著語音開合，但來源與製作方式未確認（若是舊引擎輸出，用來校準就等於間接使用舊資料），因此沒有使用，能否使用由使用者判斷。

以下保留原獨立候選／v1階段的歷史來源證據，不能當成v2現況或新驗收通過證明。

## 歷史候選／v1盤點

| 項目 | 來源與保留範圍 |
|---|---|
| `renderer.mjs` | 本次重新撰寫的通用 WebGL 表面場、獨立材質、取樣與合成程式，不引入舊 renderer 的 GLSL 字串。仍以既有候選作行為參考，不能主張法律意義的 clean-room。 |
| `character-adapter.mjs` | 本次重新撰寫的 CPU 角色資料介接。讀取既有幾何、六維形變、牙齒類別及逐影格參考點；動作契約與數值常數仍與原系統相容。 |
| `inference/streaming-*` | 沿用先前候選的 JS 特徵處理及串流／插話控制。特徵與遞迴介面仍對齊既有模型。 |
| `onnxruntime-web` | 正式引擎已不使用；只剩本資料夾的舊實驗頁與 `calibrate-mouth-latents.py`（Python 版）用來讀明文模型。 |
| `model_audio.onnx`（已移出repo） | 由先前模型轉換取得；保留原權重及模型來源關係，並非本次訓練。舊實驗頁與校準腳本需另外提供本機路徑。 |
| `assets/character/portrait.webm` | 既有專案示範人物影片原樣保留；使用者說明人物素材為己方提供。檔案格式不能用來否定使用者的素材所有權。 |
| 角色幾何、牙齒貼圖、形變與逐影格資料 | 詳見下表；既有候選保留資料具有可證實的抽取鏈，不能概括斷言全部由某上游擁有，也不能斷言只剩權重有原來源關係。 |
| `assets/speech.wav` | 既有候選測試音訊，供本機驗收，不作授權證明。 |

## 角色檔案逐項分類

從原版引擎抽出的 `*.bin` 與 `json_data_151.json` 只保留在本機，不進公開repo；需要重跑舊實驗時另外放回。下列角色路徑均相對於本目錄的 `assets/character/`；`4548ba89185989a090640942512e3d211ea5468c` 是其匯入本候選的 commit，並非最初建立證明。

| 分類與檔案 | 已查證證據 | 保留及替換邊界 |
|---|---|---|
| 己方人像：`portrait.webm` | 使用者確認人物素材為己方提供；與外部證據的 `orig_01.webm` 逐 byte 相同，SHA-256 `2b502bf8…`。 | 按使用者要求保留人像及影片；其來源不應與通用網格或牙齒混稱。 |
| 原 runtime 抽取：`face_mesh_vbo_3700v.bin`、`face_mesh_ibo_18672i.bin` | 與 `quality-fix/analysis/exact_assets/` 逐 byte 相同；`extract_full_assets.py` 從原頁面的 WebGL buffer 讀出 VBO／IBO。SHA-256 分別 `1d58236c…`、`bb8d46dd…`。 | 若要排除這條資料來源鏈，須重建幾何、拓樸及其參考索引／法線等欄位；保留人像影片不代表必須保留這些通用資料。 |
| 原 runtime 抽取：`texture_bs_3700x6.bin` | 與上述 `exact_assets/` 逐 byte 相同；報告第291行記錄抽取鏈，SHA-256 `c456be13…`。 | 須獨立建立六維形變基底，並重新驗證模型輸出控制與嘴型。 |
| 原 runtime 抽取：`texture_teeth_180x180.bin` | 與 `true_teeth_576x192.bin` 逐 byte 相同；報告第483–493行記錄由原執行緒擷取。實際尺寸為576×192 RGBA8、442,368 bytes，SHA-256 `9b5bc8d7…`；檔名中的180×180不是實際尺寸。 | 須替換牙齒圖集及對應UV／材質映射。 |
| 原 heap 匯出：`json_data_151.json` | 報告第779、814、849行記錄151影格、每格950值／465參考點由原記憶體匯出；SHA-256 `bdfd418b…` 與現檔一致。 | 這是原候選的特定角色驅動資料；v1階段的共用引擎不載入此檔，改用下述 `affine-rest` 資料。 |
| 轉換方式已知、最初來源未證實：`weight_map_180x180.bin` | 與舊候選逐 byte 相同，SHA-256 `a4f3ac3d…`；內容為180×180個 Float32，逐點等於外部 `weight_map_b64.txt` 的 UInt8 值除255（Float32誤差範圍內）。未找到該原始遮罩最初建立或抽取證據。 | 不是RGBA8；v1階段的共用 `character-adapter.mjs` 當時明確驗證0～1有限值，再轉成灰階RGBA8及不透明alpha。若要獨立來源，須另產生融合遮罩。 |
| 最初來源未證實：`avatar-pipeline/assets/face_template.json`（repo根目錄路徑） | `6b74ba0ac60ec136d816056c834bd2dd0056f390` 首次加入465個xyz點，SHA-256 `aa0925fd…`；`bundle.py` 用其前209點求姿態。未找到模板最初來源證明。 | 不能從同目錄程式的移植註記推定本檔作者；欲排除未明來源，須替換模板並重算相應姿態。 |

上述抽取證據只證明資料曾由原 runtime／角色包導出，未證實每份資料的最初作者或所有權，亦不作法律結論。外部驗收證據根目錄為 `~/openvman-experiments/onnx-acceptance-20261029/`；行號指其中 `REPORT.md`。這些檔案不在本 repo 的交付包內，跨機器稽核需另外保留證據及雜湊，不應把本機路徑當作公開可存取連結。

## 歷史：v1整合階段與產品共用引擎的差異

本目錄保留原獨立實驗及其 `json_data_151.json`。v1整合階段，產品程式 [`frontend/shared/avatar-engine/`](../../../frontend/shared/avatar-engine/README.md) 的 `assets/rig/` 曾含VBO、IBO、形變、牙齒與遮罩五檔，與本目錄對應檔案的SHA-256相同；這五檔已自共用引擎移除（見上方v2一節），來源邊界仍適用於本目錄保留的檔案。

v1階段逐幀資料使用 `openvman.render.v1`／`denseReference: "affine-rest"`：前209個xy參考來自角色追蹤資料，其餘256個xy參考由模板與每幀姿態矩陣計算。當時新產製由 `avatar-pipeline/pipeline/render_data.py` 寫出；舊角色由 `backend/app/avatar/render_data.py` 在角色讀取授權通過後轉換。當時這條流程不載入舊候選的heap匯出151影格資料，也不啟動舊 Avatar WASM；但仍使用保留模板及既有角色資料，不能因此宣稱所有資料來源均已獨立。`affine-rest` 與原heap匯出參考點算法不同，視覺等效須另驗證。

現行產製由 `avatar-pipeline/pipeline/video_lips.py` 寫出v2，`pipeline/render_data.py` 不在產製映像白名單內。Backend仍保留上述v1轉換，但新引擎拒絕v1，既有角色須從影片重新產製。

## 其他保留相依及表面

- 正式引擎不再發布ONNX Runtime，音訊推論由本專案撰寫的WebAssembly模組執行；模型權重及其轉換來源仍保留，不是本次重新訓練。
- `avatar-pipeline/pipeline/geometry.py`、`landmarks.py` 明文揭露 DH_live 移植；MediaPipe、OpenCV、NumPy及ffmpeg是產製相依，各自來源與授權不能由渲染器替換推定已移除。
- 獨立 Live2D widget 位於 `frontend/app/public/vendor/ai-avatar-bot/widget.html`，不是本次舊Avatar runtime替換對象。其同目錄 `LICENSE:25–30` 明示MIT只涵蓋該專案自有程式，Cubism Core及Haru模型另有權利與使用限制，該檔註明模型供示範使用；不得概括標成整包MIT或已取得產品／商用授權。

共用引擎的程式整合與原獨立候選的驗收證據不可混用；部署及所有產品入口的實測狀態另依計畫與交付報告記錄。不得為使掃描零命中刪除應保留的授權或歷史說明，也不能宣稱整包只剩權重具有原來源關係。
