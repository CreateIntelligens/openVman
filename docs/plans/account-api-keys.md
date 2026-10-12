# 帳號 API 金鑰

狀態：Draft（2026-10-12；使用者授權實作，待確認結案）。

## 目標與邊界

帳號可持有多把獨立的 API key，用於 ASR、TTS、Chat 及其他應用 API。root key 使用 root 的應用權限；admin key 與一般帳號 key 使用所屬帳號當下的資源授權與管理上限。服務內部 token、第三方供應商 key 與公開 Embed key 維持各自的驗證方式。

此功能涵蓋 Backend 驗證／管理 API、後台帳號金鑰介面、OpenAPI、每把 key 的請求紀錄與用量歸屬、文件及回歸測試。前台與 Avatar SDK 不提供儲存或傳遞完整管理 key 的功能；原本聊天／語音協定不變。API key 供可信任的後端程式使用，不自動開放跨網域瀏覽器請求。

## 契約

- `Authorization: Bearer ovk_<key_id>.<secret>`；與現有 JWT Bearer 共存，HTTP 與 WebSocket 使用同一驗證入口。不接受 URL query key。
- 明文只在建立回應顯示一次；資料庫存隨機高熵 token 的 SHA-256，列表／audit 不包含完整 key 或雜湊。
- 期限可指定含時區的未來時間，或不設期限；後台預設 90 天。撤銷保留 metadata，立即拒絕後續驗證。
- 正式帳號可管理自己的 key；root／admin 管理其他帳號沿用既有管理階層。臨時帳號不建立長期 key。
- 代發時，admin 僅可替有效資源不超過自己的正式一般帳號發行；替其他 admin 發行限 root。發行後由所屬帳號當下授權決定可用資源。
- 管理 key 需要登入 session（Cookie 或 JWT），不能用 API key 或 Embed key 再建立／管理其他 key。
- 每次驗證重讀帳號狀態與授權。停用帳號、撤銷帳號憑證或變更角色後，舊 key 失效；資源授權縮減不需重新發 key。
- 使用紀錄保留最近驗證時間與請求次數；推論用量以 `principal_type=api_key`、`principal_id=key_id` 區分，`user_id` 仍為帳號擁有者。

## 驗收

驗證明文不落庫／不出現在列表或 audit、撤銷與到期拒絕、帳號及資源權限不被繞過、管理其他帳號的階層規則、JWT／Embed 回歸、HTTP 與 WebSocket key 認證、用量主體區分。後台驗證建立／只顯示一次／複製／切換帳號／撤銷與直接路由，完成 build 與測試。以隔離測試資料及本機服務驗證，不建立正式使用者或正式 key。

結案時說明實際測試與部署狀態；未經使用者確認，不將本計畫標為 Done。

## 本機驗證紀錄（2026-10-12）

- Backend：`PYTHONPATH=backend python3 -m pytest backend/tests -q`，1,204 passed、2 skipped；全套執行期間補上的最新案例另由下列 43 項定向回歸覆蓋。
- Brain：`python3 -m pytest brain/api/tests -m 'not integration' -q`，1,255 passed、1 skipped、15 deselected。
- Admin：`pnpm test`，93 個測試檔、603 passed；`pnpm build` 通過。
- 最新權限／ASR／OpenAPI／入口邊界定向回歸：43 passed。包含真實 Bearer key 通過驗證、兩把 key 的 ASR 用量歸屬分開、撤銷後回 401；上游辨識與帳本傳送使用替身。
- 實際容器內以 `/tmp` 隔離來源與資料執行：Backend 定向回歸 81 passed；新增 ASR 整合案例後，該檔再跑 8 passed。Brain 用量／內部橋接定向回歸 50 passed。未修改正式容器的 `/app` 或資料目錄。
- 已建置 Admin 配合隔離 FastAPI／SQLite，以真瀏覽器驗證登入、直接路由、建立一次性 key、獨立 Bearer 認證 200、請求次數更新、關閉後清除明文及撤銷後 401。320／375／414／768 寬度沒有水平溢出，手機導覽入口可開啟頁面；瀏覽器儲存空間未出現完整 key。測試瀏覽器、服務與資料庫已清除。
- 合約產生器 `--check` 通過。Avatar、SDK 及事件 schema 無協定變動；既有 nginx SPA 路由已涵蓋新子路徑，無需變更。

以上驗證不包含實際 ASR 模型辨識品質、併發負載或正式環境部署。正式資料庫、使用者、key 及 `.env` 均未變更。
