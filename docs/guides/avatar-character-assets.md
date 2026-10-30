# 2D 人物素材：格式要求、上架與驗收

前台與 Avatar SDK 用 DHLiveMini2 引擎（`frontend/app/public/js/OpenVmanAvatarRuntime.js`、`public/wasm/OpenVmanAvatarRuntime.wasm`）播放 2D 人物。每個人物是一個資料夾，放在 backend 的 `avatar_assets_dir`（正式機為 `data/avatar/<char_id>/`），經 `GET /static/characters/<char_id>/<檔名>` 提供，讀取權限依人物資源判斷（全域、專案專屬、ROOT 指派，見 `docs/specs/01_BACKEND_SPEC.md`「專案資源範圍」）。

素材可以由本 repo 的 `avatar-pipeline` 從影片或圖片產生（流程與參數見 [avatar-pipeline/README.md](../../avatar-pipeline/README.md)），也可以由外部工具製作後直接上傳。本文只記 openVman 這端要求的格式、上架方式與如何驗收。

## 檔案

| 檔案 | 要求 |
|---|---|
| `01.webm` | VP9、無音軌、25 fps。寬高與 `combined_data` 對應的原始影片一致（例：1014、local_01 為 720×1280，其他多為 1080×1920）。影格數必須等於 `json_data` 的筆數。可帶透明通道（`yuva420p`、WebM `alpha_mode=1`），舞台背景會從人物後方透出；Safari 不支援 VP9 透明，會顯示成黑底，展示機台要用 Chrome 或 Edge |
| `combined_data.json.gz` | 由素材製作管線產出的資料檔，內含 `json_data`（每格一筆）。`json_data` 筆數＝影片影格數 |
| `meta.json` | 由 backend 上傳時寫入（`label`、`created_at`、`updated_at`），不要手寫 |

資料夾內不要放其他檔案（備份、`.orig`、暫存）：同一個路由會照人物的權限提供資料夾裡的任何檔案。

## 播放端依賴的兩件事

素材少了下面任一項，人物會出現但嘴型不對或不動，前端不會報錯：

1. 幀同步標記：引擎每格讀影片右上角 2×2 像素（`(width − 2, 0)`）的灰階平均，以 `round(avg / 40)` 當作 `幀號 % 7`。製作時每格右上角要寫入 `(幀號 % 7) × 40` 的灰階。VP9 低碼率會把太小的標記糊掉（2026-10-16 local_01 有 3 格讀錯，皆在開頭關鍵幀附近），標記區塊建議比 2×2 大，或提高該區域品質。
2. 臉部姿態資料：每格的姿態資料必須讓嘴型網格落在 180×180 的嘴型貼圖範圍內。資料錯了，網格會整塊被裁掉，嘴型貼圖是全透明的：人物照常顯示、待機正常，只有講話時嘴巴不動。2026-10-16 local_01 第一版就是這個情況，由素材製作管線修正後解決。

顯示修復集中在共用 TypeScript 模組 `frontend/shared/avatar/avatarFrameSyncRepair.ts`，由前台與 SDK 的 runtime adapter 安裝及卸載，不手動拆改 WASM 工具產生的引擎內容。讀取 2×2 標記時，先保留原始 RGBA 供引擎判斷幀號，再依左側與下側乾淨邊界重建右上角 16×16 背景，外緣 4 像素逐步融合原始畫面，避免複製另一塊背景造成方形亮度接縫。標記本體建議不超過 8×8，壓縮污染須留在修復區域內，修復邊界須保留背景；不要放人物或文字。修復使用 `putImageData`，不受影片繪製的 `globalCompositeOperation = "copy"` 影響。前台、Avatar SDK 與 SDK 嵌入 widget 共用此修正。

引擎入口與 WASM 統一命名為 `OpenVmanAvatarRuntime.js`、`OpenVmanAvatarRuntime.wasm`，引擎本身為 DHLiveMini2（Emscripten 編譯），一律從同源載入。SDK 公開路徑 `/static/sdk/runtime/OpenVmanAvatarRuntime.js`、`.wasm` 不變；舊的 `/js/DHLiveMini2.js`、`/wasm/DHLiveMini2.wasm` 不再提供。

## 上架

後台 Avatar 頁「人物」分頁有兩條路，都限 admin 以上：

- 從影片或圖片產生人物（主要路徑，`POST /api/v1/avatar/jobs`）：上傳一段正面、無聲的說話影片（MP4／MOV／WebM，200 MB、60 秒內）或一張正面人像（PNG／JPG／WebP，25 MB、最長邊 8192 像素內），由 `avatar-pipeline` 轉成素材包後自動登錄。圖片會做成 10 秒循環片段；透明背景會保留，前台的舞台背景會從人物後方透出；影片最後一格接不回第一格時會自動接上一段倒放。進度依序顯示排隊中、準備來源、檢查首尾銜接、擷取臉部特徵、轉成 VP9、計算姿態、打包加密。
- 上傳現成素材包（進階，`POST /api/v1/avatar`）：form `char_id`、`label`、`video`（`01.webm`）、`data`（`combined_data.json.gz`），選填 `project_id`，兩個檔案合計 100 MB 內。

後台在送出前先檢查副檔名與檔案大小，擋下明顯不符的檔案；影片長度與圖片尺寸只在伺服器檢查，伺服器回的 413／415 說明會原樣顯示。檔案可點選或拖放到欄位上，選好後顯示預覽，透明圖片以棋盤格襯底。

- 帶 `project_id`：建成該專案的專屬人物，只有能讀該專案的帳號（與綁定該專案的 Embed key）看得到、下載得到；公開的 `GET /api/v1/characters` 不列。
- 不帶：全域人物，照帳號授權。
- 不要直接把檔案複製進 `data/avatar/`，也不要改 Auth DB 的 `resources` 來「讓檔案拿得到 200」：前者不會登錄資源，後者會把專案專屬人物變成任何人（含未登入）都能下載。要替換素材就用同一個 `char_id` 與 `project_id` 重新上傳。

## 驗收

1. 規格：`ffprobe -count_frames` 的影格數、fps 與 `json_data` 筆數一致。
2. 幀同步標記：解出每格右上角 2×2，`round(avg/40)` 應等於 `幀號 % 7`；讀錯的格數越少越好。
3. 權限：專案專屬人物用專案成員讀 `01.webm`／`combined_data.json.gz` 應 200；非成員 403；未登入 404；公開清單不出現。
4. 實際播放：在前台選這個人物、送一句話，確認嘴巴開合跟著聲音。替換素材後瀏覽器可能留著舊檔，要強制重新整理。
5. 標記修復：以淺色背景檢查待機及講話時右上角不再閃爍、修復區域沒有明顯接縫，且其餘人物畫面完整。前台與外部 SDK 都要驗證；舊頁面須強制重新整理以更新引擎。
