# 2D 人物素材：格式要求、上架與驗收

前台與 Avatar SDK 用 DHLiveMini2（`frontend/app/public/js/DHLiveMini2.js`、`public/wasm/DHLiveMini2.wasm`）播放 2D 人物。每個人物是一個資料夾，放在 backend 的 `avatar_assets_dir`（正式機為 `data/avatar/<char_id>/`），經 `GET /static/characters/<char_id>/<檔名>` 提供，讀取權限依人物資源判斷（全域、專案專屬、ROOT 指派，見 `docs/specs/01_BACKEND_SPEC.md`「專案資源範圍」）。

素材的製作管線不在本 repo；本文只記 openVman 這端要求的格式、上架方式與如何驗收。

## 檔案

| 檔案 | 要求 |
|---|---|
| `01.webm` | VP9、無音軌、25 fps。寬高與 `combined_data` 對應的原始影片一致（例：1014、local_01 為 720×1280，其他多為 1080×1920）。影格數必須等於 `json_data` 的筆數 |
| `combined_data.json.gz` | 由素材製作管線產出的資料檔，內含 `json_data`（每格一筆）。`json_data` 筆數＝影片影格數 |
| `meta.json` | 由 backend 上傳時寫入（`label`、`created_at`、`updated_at`），不要手寫 |

資料夾內不要放其他檔案（備份、`.orig`、暫存）：同一個路由會照人物的權限提供資料夾裡的任何檔案。

## 播放端依賴的兩件事

素材少了下面任一項，人物會出現但嘴型不對或不動，前端不會報錯：

1. 幀同步標記：引擎每格讀影片右上角 2×2 像素（`(width − 2, 0)`）的灰階平均，以 `round(avg / 40)` 當作 `幀號 % 7`。製作時每格右上角要寫入 `(幀號 % 7) × 40` 的灰階。VP9 低碼率會把太小的標記糊掉（2026-10-16 local_01 有 3 格讀錯，皆在開頭關鍵幀附近），標記區塊建議比 2×2 大，或提高該區域品質。
2. 臉部姿態資料：每格的姿態資料必須讓嘴型網格落在 180×180 的嘴型貼圖範圍內。資料錯了，網格會整塊被裁掉，嘴型貼圖是全透明的：人物照常顯示、待機正常，只有講話時嘴巴不動。2026-10-16 local_01 第一版就是這個情況，由素材製作管線修正後解決。

## 上架

用後台 Avatar 頁或 `POST /api/v1/avatar`（admin 以上）上傳：form `char_id`、`label`、`video`（`01.webm`）、`data`（`combined_data.json.gz`），選填 `project_id`。

- 帶 `project_id`：建成該專案的專屬人物，只有能讀該專案的帳號（與綁定該專案的 Embed key）看得到、下載得到；公開的 `GET /api/v1/characters` 不列。
- 不帶：全域人物，照帳號授權。
- 不要直接把檔案複製進 `data/avatar/`，也不要改 Auth DB 的 `resources` 來「讓檔案拿得到 200」：前者不會登錄資源，後者會把專案專屬人物變成任何人（含未登入）都能下載。要替換素材就用同一個 `char_id` 與 `project_id` 重新上傳。

## 驗收

1. 規格：`ffprobe -count_frames` 的影格數、fps 與 `json_data` 筆數一致。
2. 幀同步標記：解出每格右上角 2×2，`round(avg/40)` 應等於 `幀號 % 7`；讀錯的格數越少越好。
3. 權限：專案專屬人物用專案成員讀 `01.webm`／`combined_data.json.gz` 應 200；非成員 403；未登入 404；公開清單不出現。
4. 實際播放：在前台選這個人物、送一句話，確認嘴巴開合跟著聲音。替換素材後瀏覽器可能留著舊檔，要強制重新整理。
