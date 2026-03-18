## ADDED Requirements

### Requirement: Web Crawler 外掛爬取指定 URL 並萃取正文
`plugin-web-crawler` SHALL 接收目標 URL，使用 HTTP + Readability（或 Playwright 無頭瀏覽器作為備援）爬取網頁，萃取主要正文（移除廣告、導覽列、頁尾等雜訊），並以 Markdown 格式回傳結果，供 Brain 層作為 RAG 補充知識。

#### Scenario: 成功爬取公開網頁正文
- **WHEN** Brain 或使用者觸發爬蟲，指定 `url: "https://example.com/article"`
- **THEN** 外掛 SHALL 在 `CRAWLER_TIMEOUT_MS`（預設 15000ms）內完成爬取，回傳 `{ "type": "crawl_result", "url": "...", "content_markdown": "...", "word_count": N }`

#### Scenario: 網頁需要 JavaScript 渲染（HTTP 模式失敗）
- **WHEN** HTTP + Readability 爬取結果正文少於 100 字（判定為 JS 渲染頁面）
- **THEN** 外掛 SHALL 自動切換至 Playwright 無頭瀏覽器模式重新爬取

#### Scenario: 爬取超時或連線失敗
- **WHEN** 目標 URL 在 `CRAWLER_TIMEOUT_MS` 內無回應
- **THEN** 外掛 SHALL 回傳 `{ "error": "crawl_timeout", "url": "..." }`，不重試

#### Scenario: URL 被列入黑名單
- **WHEN** 目標 URL 的 domain 出現在 `CRAWLER_BLOCKED_DOMAINS` 環境變數清單中
- **THEN** 外掛 SHALL 立即回傳 `{ "error": "domain_blocked" }` 而不發起任何網路請求

### Requirement: Web Crawler 萃取結果自動注入 RAG 知識庫
爬取完成後，外掛 SHALL 將正文 Markdown 自動觸發 Brain 層的知識索引管線（MarkItDown → Chunk → bge-m3 Embed → LanceDB），以 `source_url` 作為 metadata 欄位，避免重複索引已爬取的 URL。

#### Scenario: 相同 URL 被要求再次爬取
- **WHEN** 同一 URL 在 `CRAWLER_CACHE_TTL_MIN`（預設 60 分鐘）內被重複請求
- **THEN** 外掛 SHALL 直接回傳快取的爬取結果，不發起新的網路請求

### Requirement: Web Crawler 爬取行為遵守 robots.txt
外掛 SHALL 在爬取前檢查目標網站的 `robots.txt`，若 `User-agent: *` 的 `Disallow` 規則包含目標路徑，則跳過爬取並回傳 `{ "error": "robots_disallowed" }`（可透過 `CRAWLER_IGNORE_ROBOTS=true` 覆蓋，預設 false）。

#### Scenario: 目標路徑被 robots.txt 禁止
- **WHEN** `robots.txt` 中 `Disallow: /private/` 且目標 URL 路徑為 `/private/doc`
- **THEN** 外掛 SHALL 回傳 `{ "error": "robots_disallowed" }` 並記錄警告日誌
