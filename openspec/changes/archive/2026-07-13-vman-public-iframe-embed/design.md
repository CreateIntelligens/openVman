## Context

openVman 目前是單體單租戶設計：`frontend/admin`（Vite + React，port 8787 同源）與 `frontend/app`（Vue3 虛擬人）直接打 backend `/api/*` 與 `/ws/*`，沒有任何 token 鑑權。虛擬人渲染由 `useMatesX.ts` 載入 DHLiveMini2 WASM 引擎完成，引擎來自 MatesX（上海云虛互伴），形象資料 (`combined_data.json.gz`) 已具備使用者自有的免費額度。

商務上需要把虛擬人放到第三方網站。這份 design 處理「最少代價、能讓陌生網站一行 script 嵌入」的最小可行架構。授權層面：DHLiveMini2 引擎本身的對外再分發授權尚未書面取得，本次設計**不假設**有 OEM 條款，把實作保留在「使用者用自己的形象、自己的 quota」框架內，等同於把現有單頁應用換個介面對外暴露，不額外複製或代理 WASM。

## Goals / Non-Goals

**Goals**
- 第三方網站只要 `<script src=".../vman-embed.js"></script>` + `<vman-avatar api-key="…">` 兩行就能嵌入虛擬人
- 對外端點（`/embed/*`、`/api/embed/*`、`/ws/embed/*`）走 API Key 鑑權與 domain allowlist
- 既有 admin / 內部 avatar 行為與既有 WS envelope 完全不變
- iframe ↔ host 用 `postMessage` 通訊；訊息協議版本化（`v1`），未來可演進
- 一個 backend 程式碼路徑同時服務內部與對外，差別只在 middleware

**Non-Goals**
- 不做 OAuth / SSO / 使用者帳號系統（API Key 就夠）
- 不做計費 / quota（免費額度由 MatesX 那層管）
- 不做 B2 SDK（npm package）、不做 B3（雲端 WebRTC 推流）
- 不做形象動態切換 / 多語言 / 多 persona 切換 API（後續再說）
- 不複製、不代理、不 rehost DHLiveMini2 WASM；引擎仍從 MatesX OSS 載入

## Decisions

### D1：採 iframe + Web Component（B1），不採 SDK（B2）
- iframe 隔離 WASM、canvas、WS、TTS pipeline，host 頁不受污染
- Web Component (`<vman-avatar>`) 是 iframe 的薄包裝，提供宣告式 API
- 替代方案 B2 SDK 已評估：對方需自備 canvas / 處理 WASM 生命週期 / 跨框架包裝，整合成本高、版本治理難，否決

### D2：對外通道分離為獨立路由前綴 `/embed/*`、`/api/embed/*`、`/ws/embed/*`
- 不重用內部 `/api/*`、`/ws/*`，避免鑑權邏輯與既有同源信任互相污染
- 內部與對外共用 service 層（chat、tts、brain），只在 router / middleware 分流
- 替代方案「同一路由用 header 區分」否決：太容易因為 nginx 配置改動意外破鑑權

### D3：API Key 是唯一鑑權因子，搭配 domain allowlist
- API Key 透過 `Authorization: Bearer <key>` 或 query string `?key=` 傳遞
- API Key 綁定 `tenant_id`、`allowed_domains[]`、`enabled`、`created_at`
- iframe 載入時 backend 校驗 `Origin` 或 `Referer` 是否在 allowlist
- 替代方案 JWT / OAuth 否決：對 B2B 嵌入過重，第一版不需要

### D4：API Key 儲存使用簡單 JSON / SQLite，不導入新 service
- 新增 `backend/data/embed_keys.json`（或 SQLite，沿用 brain 既有 `session_store.py` 模式）
- CRUD 透過 admin UI 一頁面操作；初期用 CLI 手動管也可以
- 替代方案 Redis / Postgres 否決：Redis 已存在但不適合存配置；Postgres 引入新依賴
- 寫入時加檔案鎖避免 race；reload 採事件驅動或 60 秒 TTL 快取

### D5：iframe ↔ host 訊息協議版本化、minimal surface
- 訊息格式 `{ source: "vman", version: "v1", type, payload }`
- Host → iframe：`speak(text)`、`interrupt()`、`set_persona(id)`（後續）
- iframe → host：`ready`、`message`（含 user / assistant text）、`speaking`（start/stop）、`error`、`resize`
- `version` 欄位讓後續可以加新訊息型別不破舊版

### D6：`/embed/avatar` 路由由 `frontend/app` 提供，UI 是現有 avatar 介面的精簡版
- 移除 admin 才會用的 debug、麥克風選擇、設定按鈕
- 透過 query string 接 `api_key` / `tenant_id` / `persona` / `theme`
- 既有 `App.vue` 切兩個入口：`main.ts` 內部用、`embed.ts` 對外用，共享 composables
- 替代方案「另起新前端專案」否決：要重複維護兩份 useMatesX / useTtsStreamer 太貴

### D7：DHLiveMini2 WASM 仍從 MatesX OSS 載入
- iframe 內部還是 `script.src = '/js/DHLiveMini2.js'`，由 nginx 服務本地 copy
- 不複製、不 rehost wasm 檔到對外 CDN（避免授權爭議）
- 第三方 end-user 載入時，瀏覽器會去拉本站的 nginx → nginx 裡的 wasm 來自當初 build 時打包的版本（已合法取得）；這跟對方直接從 MatesX OSS 拉是同等行為

### D8：CORS / X-Frame-Options 規則精準放寬
- `/embed/avatar` 是可公開載入的靜態 iframe shell；API Key 與 domain allowlist 延遲到 `/api/embed/session` 驗證
- nginx 不反射 `$http_origin`；`/api/embed/*` 的 CORS header 由 backend 在 API Key + allowlist 通過後設定，避免 nginx 與 backend 疊加或放寬錯誤
- 既有 `/admin/*` 與 `/api/*`（內部）保留嚴格 same-origin
- 替代方案「整站開 CORS」嚴重否決：等同放棄 admin 的 CSRF 防護

## Risks / Trade-offs

- **WASM 引擎再分發授權未明** → 限定使用者自有形象、自有免費額度；若 MatesX 改變 OSS 公開政策或要求授權書面，需暫停服務並向 MatesX 取得 OEM 授權
- **每位 end-user 載入 ~2.3MB WASM** → 第一版接受，後續評估是否值得自架 CDN（須先確認授權允許）
- **API Key 洩漏難以撤銷** → domain allowlist 為第二道防線；若 key 洩到外部，撤銷後 60 秒內生效（TTL 快取）
- **iframe 內 WS 鑑權** → WS 連線 query string 帶 key，server 第一個 frame 之前驗證；token 出現在 URL log 是已知缺點，第一版接受
- **`postMessage` 沒有來源驗證會被惡意 host 偽造** → iframe 端固定 `targetOrigin` 為 host；host 端應該驗證 `event.origin`，文件中明示
- **DHLiveMini2 WASM 大小 / 啟動延遲** → 對方 end-user 第一次載入慢；用 `<vman-avatar lazy>` 屬性延後載入緩解
- **同一 API Key 被嵌到多個 domain** → allowlist 強制檢查；若需要多 domain，發一張 key 帶多個 allowed domain
- **跨域 cookie / storage 限制** → iframe 內的 session state 走自家 backend session_store，不依賴 cookie
- **既有測試 / CI 不覆蓋對外路徑** → 新增 `tests/embed/` 子目錄，用 pytest + httpx 跑端到端

## Migration Plan

1. **Phase 1（純後端 + loader）**：先做 `/api/embed/*` 鑑權層、API Key store、loader script、文件。沒有 UI 變動。可以用 curl 測通鑑權路徑
2. **Phase 2（前端 embed 入口）**：`frontend/app` 加 `/embed/avatar` 路由與精簡 UI，loader iframe 指向它
3. **Phase 3（postMessage 雙向協議）**：實作 host → iframe 指令與 iframe → host 事件
4. **Phase 4（admin UI 管 API Key）**：admin 加一頁，不阻擋 Phase 1-3 上線
5. **Rollback**：對外通道是獨立路由，停掉 nginx `/embed/*` 一個 location 即整片下架，不影響內部

## Open Questions

- API Key 要不要 hash 後存？第一版明文存 JSON 是否可接受（內部運維可見）
- WS 鑑權 token 要不要走第一個訊息握手而非 query string？延後到 v2 訊息協議
- 是否要強制 HTTPS-only embed？開發期允許 HTTP 方便本機測試
- 同一 tenant 多 persona 的切換是 API Key 層級還是 query string 層級？延後決定
- 嵌入時 host 頁尺寸自適應策略：iframe `auto-resize` 透過 `postMessage` 回報高度，or 固定大小由 host 決定？預設後者，提供前者選項
