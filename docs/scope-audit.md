# 權限範圍與上傳限制盤點

盤點日期：2026-09-14。核對版本：`fbf8bfd`。原始待辦以 `2a1d4fa` 為基準，部分描述已與目前版本不同。

## Admin scope 解析

**成立，已修正程式碼。** `backend/app/auth/resources.py` 原本攔截 runtime 解析的所有例外並回傳 `UNSCOPED_ADMIN`。現在例外向上傳遞、中止請求，避免 scope 無法確認時放行。測試替身以參數注入 repository，ROOT 則沿用不受 scope 限制的規則。

原始待辦的影響面需要收斂：單筆資源解析與可見清單會使用這個隱式 runtime 入口；`/api/v1/users/access-options` 明確傳入 repository；授權遞移檢查 `_ensure_grants_within_granter_scope` 在 transaction 內直接讀取 scope，並不依賴此 fallback。既有資料庫讀取失敗原本就會中止，不能描述成所有強制點都會失效。

## 零授權正式帳號

**原待辦的主要判斷不成立，保留現有行為。**

- `fbf8bfd` 已恢復前端建立一般使用者時的 `accessForm.complete` 守衛，要求完整資源與預設值。
- `AccountAccessRepository.replace` 一開始就呼叫 `_normalize_account_access`，檢查專案、聲音、人物或 VRM grants 與預設值；只閱讀函式後半段會漏掉這層驗證。
- 建帳 API 允許省略 `access`，與既有分步建帳契約及 API lifecycle 測試相容。列表已有「尚未授權」標示。
- 在執行中 Backend 容器，以暫存 SQLite、獨立 runtime 與 FastAPI TestClient 驗證：省略 access 建帳回 201、一般登入回 200、預設管理後台登入回 403、空 access 更新回 422。新帳號對五類已登記資源的可見清單皆空，直接解析皆拒絕；未動正式帳號資料。

容器版本與 checkout 的 VRM-only 驗證細節不同，以上容器結果只代表目前 runtime；checkout 的 repository 也有完整 grants 驗證。零 grants 不會撤銷既有 ownership，不能將這項結果推論為所有既有零 grants 帳號均無資源。

另外看到前台在沒有可用人物時，會先產生無人物通知，再顯示通用的網路載入錯誤。這是既有提示文字問題，未在本次權限修正中變更。

## 上傳大小

**成立，且原始待辦未涵蓋所有路由。** `validateUploadFiles` 的固定 5 MiB 只用於知識庫與 workspace，並非所有角色／背景／吉祥物上傳共用。

Backend 預設每檔限制：文件、角色、吉祥物為 100 MiB，背景為 25 MiB。原始檔上傳 `/api/v1/knowledge/raw/upload` 原本經通用 proxy 到 Brain，沒有套用文件上限；`/api/v1/knowledge/upload` 的部分文字檔 passthrough 也漏掉檢查。只把前端常數改成 100 MiB 仍不足以修復。

本次在 Backend 容器讀取上述四個設定，實際值與預設值相同。

修正讓知識庫的兩條上傳路徑都由 Backend 執行文件上限，前端則在上傳前讀取 Backend 提供的限制。每檔限制和 nginx 的整批 HTTP body 限制是兩回事；整批仍可能被 nginx 拒絕。

通用 proxy 同時封鎖上述上傳路徑的尾斜線與子路徑，並拒絕 `.`／`..` 片段。隔離重現確認，若只有字串前綴檢查，`knowledge/%2e/upload` 等路徑會被 HTTPX 正規化成有效的 Brain 上傳 URL，繞過 Gateway；修正後在轉送前回 404。

## 驗證範圍

scope 回歸測試涵蓋 runtime 例外、repository 例外、隱式與明確注入 repository、範圍外單筆與清單，以及 ROOT 和未設限 admin 的既有行為。上傳驗證涵蓋依設定變動的大小邊界、授權檢查與上游轉送行為。

- Backend 全套分兩組執行：`python -m pytest tests/auth/ -q` 為 193 passed；`python -m pytest tests/ --ignore=tests/auth -q` 為 570 passed、2 skipped（環境未安裝原生 AnyDoc binding）。最後補上 dot segment 防護後，另重跑上傳路由 27 passed 與 Brain proxy 13 passed。
- Admin：`pnpm test` 為 351 passed。
- Admin：`pnpm build --outDir /tmp/openvman-scope-admin-dist` 通過 TypeScript 與 production build。預設 `dist` 目錄因既有權限無法清空，所以改用獨立輸出目錄，未修改該目錄權限。
- `python contracts/scripts/generate_protocol_contracts.py --check` 與 `git diff --check` 通過。

本次交付為工作樹程式碼與文件修改；未以重建或重啟服務將修正部署到執行中的容器。
