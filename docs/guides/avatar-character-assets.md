# 2D 人物素材：格式要求、上架與驗收

前台、Admin人物試用與 Avatar SDK 的新版播放程式共用 [`AvatarEngine`](../../frontend/shared/avatar-engine/README.md)，以本專案的加密WebAssembly嘴型模型、WebAudio與WebGL播放2D人物，不以舊Avatar runtime作備援。這是程式及格式契約說明，正式部署與各入口實機驗收須另行確認；[來源拆分計畫](../plans/avatar-source-decoupling.md)保持Draft。每個人物是一個資料夾，放在 backend 的 `avatar_assets_dir`（正式機為 `data/avatar/<char_id>/`），經 `GET /static/characters/<char_id>/<檔名>` 提供，讀取權限依人物資源判斷（全域、專案專屬、ROOT 指派，見 `docs/specs/01_BACKEND_SPEC.md`「專案資源範圍」）。

素材可以由本 repo 的 `avatar-pipeline` 從影片或圖片產生（流程與參數見 [avatar-pipeline/README.md](../../avatar-pipeline/README.md)），也可以由外部工具製作後直接上傳。本文只記 openVman 這端要求的格式、上架方式與如何驗收。

## 檔案

| 檔案 | 要求 |
|---|---|
| `01.webm` | VP9、無音軌、25 fps。寬高與 `render_data.frameSize` 一致（例：1014、local_01 為720×1280，其他多為1080×1920），影格數等於 `render_data.frames` 筆數。可帶透明通道（`yuva420p`、WebM `alpha_mode=1`），舞台背景會從人物後方透出；VP9透明相容性須以實際瀏覽器驗收 |
| `render_data.json.gz` | 新版播放讀取的gzip JSON，契約為 `openvman.render.v2`，欄位見下節。依相同角色權限提供，未通過授權不得觸發舊包轉換 |
| `combined_data.json.gz` | 新版現成包上傳仍沿用此檔名，但內容僅為 `{ "render_data": v2物件 }`，不含舊模板、姿態或加密資料。歷史包仍可保留作離線遷移，不能直接供v2播放器使用 |
| `meta.json` | 由 backend 上傳時寫入（`label`、`created_at`、`updated_at`），不要手寫 |

資料夾內不要放其他檔案（備份、`.orig`、暫存）：同一個路由會照人物的權限提供資料夾裡的任何檔案。

### 新版渲染資料契約

| 欄位 | 內容 |
|---|---|
| `schema`／`geometrySource` | 固定為 `openvman.render.v2`／`mediapipe-video` |
| `frameRate`／`frameSize` | 固定25 fps；`[width, height]`為1～8192的整數 |
| `frames` | 非空陣列，每幀物件含 `region`（原圖xyxy）、`outer`／`inner`（各20點、40個局部xy數值，範圍0～180） |
| `provenance` | 影片SHA-256、產製實作及MediaPipe偵測模型身分；上傳此欄不等於伺服器已證實其真實性 |

產製管線直接解碼原影片追蹤嘴唇，依嘴寬計算ROI，不讀舊模板、rig或姿態。瀏覽器程序產生嘴唇網格、解剖位移、牙冠輪廓、口腔著色及融合範圍。新角色的上傳包與sidecar包含相同v2物件。

歷史v1人物須從其原影片重新產製v2；不能只修改schema字串。Backend仍能在既有授權規則下讀取／轉換歷史v1包，但所得v1含原模板，**不能供新v2引擎播放，也不算完成來源替換**。新引擎明確提示重新產製，不載入舊rig備援。正式人物的批次遷移／重新上架需單獨核對角色與專案授權，驗收輸出不能直接覆寫正式資料夾。

### 人像、模板與相依來源

使用者確認人像／影片為己方提供，應依要求保留；不能因格式相容而將人像所有權歸給工具作者。反過來，人像為己方素材，也不能推定配套網格、牙齒或模板均由己方建立。

- v2獨立生成：人物嘴唇座標只取自己方影片及MediaPipe；拓樸、解剖位移、融合範圍與牙齒／口腔著色由可重現程式產生。共用引擎已移除原VBO、IBO、形變與牙齒／遮罩二進位交付。
- 歷史來源保留：舊候選及離線轉換工具仍保有原模板／rig／校準profile的來源紀錄。v2產製容器不包含它們，不能把新版完成延伸宣稱成所有舊資料與Git歷史已改來源。
- 保留模型：音訊模型仍為原來源權重，改以加密後編進 `mouth-model.wasm` 發布，六維輸出與音訊特徵契約維持相容。MediaPipe偵測器同樣是第三方模型，不能宣稱整包只有自研權重。
- 第三方程式：MediaPipe、OpenCV、NumPy、ffmpeg與容器套件保留各自來源與授權；不以npm掃描未命中來判定資料來源。
- 獨立Live2D小助理：`frontend/app/public/vendor/ai-avatar-bot/widget.html` 不使用本次替換的Avatar runtime。同目錄 `LICENSE:25–30` 明示MIT只涵蓋該專案自有程式；Cubism Core與Haru模型另有權利及使用限制，該檔註明模型供示範使用，不能概括認定整包MIT或產品／商用授權。

逐檔證據、SHA-256、外部驗收報告行號與尚待釐清事項，見現有 [PROVENANCE.md](../../scripts/experiments/avatar-renderer-next/PROVENANCE.md)。本節記錄技術來源及未證實範圍，不作法律結論。

## 播放端依賴的兩件事

素材少了下面任一項，可能出現人物正常但嘴型不對或不動；格式檢查通過仍須實際播放驗收：

1. 幀同步標記：引擎每格讀影片右上角 2×2 像素（`(width − 2, 0)`）的灰階平均，以 `round(avg / 40)` 當作 `幀號 % 7`。製作時每格右上角要寫入 `(幀號 % 7) × 40` 的灰階。VP9 低碼率會把太小的標記糊掉（2026-10-16 local_01 有 3 格讀錯，皆在開頭關鍵幀附近），標記區塊建議比 2×2 大，或提高該區域品質。
2. 嘴唇座標資料：每格region須位於原影片內、內外唇環須落於180×180局部ROI。影片與sidecar幀數或對位不同會讓嘴型錯位；格式合格後仍須同影格零值／正負控制及實際語音驗收。

新版顯示修復集中在共用 `frontend/shared/avatar-engine/frame-sync.mjs`，由同一 `FramePlayer` 先讀取2×2標記判斷幀號，再依左側與下側乾淨邊界重建右上角16×16背景，外緣4像素逐步融合原始畫面，避免複製另一塊背景造成方形亮度接縫。標記本體建議不超過8×8，壓縮污染須留在修復區域內，修復邊界須保留背景；不要放人物或文字。修復使用 `putImageData`，不受影片繪製的 `globalCompositeOperation = "copy"` 影響。Vue與SDK共用此路徑；獨立Live2D widget不使用人物幀標記。

新版入口為共用 `AvatarEngine`，部署資源由 `frontend/app/scripts/prepare-avatar-engine.mjs` 依鎖定套件組裝並產生雜湊清冊。官方ORT仍需自己的WASM與模型資源，並非零第三方依賴；SDK跨origin播放需正確CORS及Blob Worker的CSP設定，詳見共用引擎README。歷史 `OpenVmanAvatarRuntime.js`／`.wasm` 的路徑不是新版播放契約。

## 上架

後台 Avatar 頁「人物」分頁有兩條路，都限 admin 以上：

- 從影片或圖片產生人物（主要路徑，`POST /api/v1/avatar/jobs`）：上傳一段正面、無聲的說話影片（MP4／MOV／WebM，200 MB、60 秒內）或一張正面人像（PNG／JPG／WebP，25 MB、最長邊 8192 像素內），由 `avatar-pipeline` 轉成素材包後自動登錄。圖片會做成 10 秒循環片段；透明背景會保留，前台的舞台背景會從人物後方透出；影片最後一格接不回第一格時會自動接上一段倒放。進度依序顯示排隊中、準備來源、檢查首尾銜接、擷取臉部特徵、轉成 VP9、計算嘴型、封裝素材。
- 上傳現成素材包（進階，`POST /api/v1/avatar`）：form `char_id`、`label`、`video`（`01.webm`）、`data`（`combined_data.json.gz`），選填 `project_id`，兩個檔案合計 100 MB 內。

後台在送出前先檢查副檔名與檔案大小，擋下明顯不符的檔案；影片長度與圖片尺寸只在伺服器檢查，伺服器回的 413／415 說明會原樣顯示。檔案可點選或拖放到欄位上，選好後顯示預覽，透明圖片以棋盤格襯底。

- 帶 `project_id`：建成該專案的專屬人物，只有能讀該專案的帳號（與綁定該專案的 Embed key）看得到、下載得到；公開的 `GET /api/v1/characters` 不列。
- 不帶：全域人物，照帳號授權。
- 不要直接把檔案複製進 `data/avatar/`，也不要改 Auth DB 的 `resources` 來「讓檔案拿得到 200」：前者不會登錄資源，後者會把專案專屬人物變成任何人（含未登入）都能下載。要替換素材就用同一個 `char_id` 與 `project_id` 重新上傳。

## 驗收

1. 規格：`ffprobe -count_frames` 的影格數、fps、寬高與 `render_data.frames` 筆數、25 fps及 `frameSize` 一致；舊相容包另核對 `json_data` 筆數。
2. 幀同步標記：解出每格右上角 2×2，`round(avg/40)` 應等於 `幀號 % 7`；讀錯的格數越少越好。
3. 權限：專案專屬人物用專案成員讀 `01.webm`／`render_data.json.gz`／`combined_data.json.gz` 應200；非成員403；未登入404；公開清單不出現。未授權的sidecar請求不得建立轉換檔。
4. 實際播放：在前台選這個人物、送一句話，確認嘴巴開合跟著聲音。替換素材後瀏覽器可能留著舊檔，要強制重新整理。
5. 標記修復：以淺色背景檢查待機及講話時右上角不再閃爍、修復區域沒有明顯接縫，且其餘人物畫面完整。前台與外部 SDK 都要驗證；舊頁面須強制重新整理以更新引擎。
