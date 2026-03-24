# 計畫：URL 匯入知識庫

## 目標

在 admin 後台的 Knowledge Base 頁面支援「貼網址匯入」，透過外部 crawler provider 抓取網頁內容後，送進 Brain 的 knowledge ingest 流程。

目前 provider 使用 `create360.ai`，但程式碼不再寫死 provider URL，改由環境變數 `CRAWLER_PROVIDER_URL` 提供。

---

## 現況摘要

這條功能目前已經有基本實作，實際程式結構如下：

- frontend UI：`frontend/admin/src/pages/KnowledgeBase.tsx`
- frontend API helper：`frontend/admin/src/api.ts`
- backend route：`backend/app/gateway/routes.py`
- provider adapter：`backend/app/gateway/crawl_adapter.py`
- shared crawler plugin：`backend/app/gateway/plugins/web_crawler.py`
- Brain 寫入：走既有 `POST /brain/knowledge/upload`（multipart files + target_dir）

也就是說，這份文件現在不是純 proposal，而是 **現況回補 + 後續缺口整理**。

---

## 架構流程

```text
KnowledgeBase.tsx
  -> POST /api/knowledge/crawl
  -> gateway routes
  -> crawl_adapter.fetch_page(url)
  -> GET {CRAWLER_PROVIDER_URL}/{domain}{path}
  -> _parse_provider_response()
  -> _clean_markdown()
  -> POST {brain_url}/brain/knowledge/upload (multipart)
  -> workspace/knowledge/ingested/ + background reindex
  -> 回傳結果給前端並刷新列表
```

---

## Provider 格式

`create360.ai` 回傳的是純文字，不是 JSON。實測格式如下：

```text
Title: Breaking News, Latest News and Videos | CNN

URL Source: http://cnn.com/

Markdown Content:
Breaking News, Latest News and Videos | CNN
===============

...
```

現行 parser 規則：

1. 優先解析 wrapper 的 `Title:`、`URL Source:`、`Markdown Content:`
2. 如果 wrapper 沒有 title，才 fallback 用 markdown heading 規則推斷
3. 如果 markdown 開頭只是重複標題，會先剝掉
4. 解析完正文後，再做噪音清理
5. 最後還沒有 title，才 fallback 用 `{domain}{path}`

這和早期「直接從 markdown 第一段猜 title」的版本不同，後續修改請以目前 parser 為準。

---

## 實作細節

### 1. crawl adapter

`backend/app/gateway/crawl_adapter.py` 是唯一對外呼叫 crawler provider 的地方。

目前包含這幾個責任：

- URL 格式驗證
- blocked domain 檢查
- `CRAWLER_PROVIDER_URL` 缺值檢查
- provider wrapper 解析
- markdown 噪音清理
- shared httpx client 重用
- 回傳 `CrawlResult(title, content, source_url, status_code)`

目前 helper 大致分成：

- `_parse_provider_response(raw_text, fallback_url)`
- `_extract_markdown_title(content)`
- `_strip_leading_markdown_title(content, title)`
- `_clean_markdown(raw)`
- `_get_client()` / `close_client()`

### 2. gateway route

`backend/app/gateway/routes.py` 目前實際路由是：

```text
POST /api/knowledge/crawl
```

不是 `/knowledge/crawl`。

這樣做的原因很單純：

- frontend `post()` helper 會自動補 `/api`
- backend 本身也 include 了 `brain_proxy_router`
- 直接用 exact path `/api/knowledge/crawl` 比較不容易和 proxy routing 搞混

這個 route 目前做的事：

1. 呼叫 `fetch_page(req.url)`
2. 組裝 markdown（`# title\n\nSource: url\n\ncontent`）
3. 從 URL 產生 slug 檔名，multipart POST 到 `{brain_url}/brain/knowledge/upload`
4. 回傳 `{status, title, source_url, path, size}`

### 3. frontend

frontend 已補兩塊：

- `frontend/admin/src/api.ts`
  - `crawlUrl(url)` 會呼叫 `knowledgePath("/crawl")`
  - 經過 `post()` helper 後，瀏覽器實際會打 `/api/knowledge/crawl`
- `frontend/admin/src/pages/KnowledgeBase.tsx`
  - 已新增 URL 匯入輸入框與按鈕
  - 成功後會刷新 knowledge list

### 4. shared plugin

`backend/app/gateway/plugins/web_crawler.py` 現在已經共用 `crawl_adapter.fetch_page()`。

也就是：

- 同步知識匯入
- worker/plugin crawler

這兩條目前吃的是同一份 provider parsing 邏輯，不是兩套不同 crawler。

---

## 設定方式

`crawler_provider_url` 現在是 **env-only**。

程式碼中的 config 預設值是空字串，必須由環境提供：

```env
CRAWLER_PROVIDER_URL=https://create360.ai
```

目前 backend 實際讀的是：

```text
backend/.env
```

不是 repo root 的 `.env`。

如果沒有設定，`fetch_page()` 會直接報：

```text
未設定 CRAWLER_PROVIDER_URL
```

---

## 路由注意事項

backend 內同時 include：

- `gateway_router`
- `internal_router`
- `brain_proxy_router`

目前 `gateway_router` 先於 `brain_proxy_router` 註冊，所以 `/api/knowledge/crawl` 會先命中 gateway route。

後續如果有人調整 router 註冊順序，這條功能可能被 `/api/{path:path}` proxy fallback 吃掉，所以這是要注意的 integration point。

---

## 錯誤處理

目前這條流程應至少覆蓋以下情境：

| 場景 | HTTP | 說明 |
|------|------|------|
| URL 格式錯誤 | 400 | `無效的網址：{url}` |
| Domain 被封鎖 | 400 | `該網域已被封鎖：{domain}` |
| Provider 未設定 | 422 | `未設定 CRAWLER_PROVIDER_URL` |
| Provider timeout | 504 | `抓取逾時（{timeout}ms）` |
| Provider 非 2xx | 502 | `網頁回傳錯誤：{status}` |
| 抓取內容為空 | 422 | `抓取結果為空：{url}` |
| 清理後內容為空 | 422 | `清理後內容為空：{url}` |
| Brain upload 失敗 | 502 | `知識庫寫入失敗：{err}` |

---

## 驗收項目

- [ ] Knowledge Base 頁面可看到 URL 匯入 UI
- [ ] 貼入有效 URL 後可看到成功訊息
- [ ] 匯入文件會出現在知識庫列表
- [ ] 文件正文含 `Source: {url}` 標記
- [ ] reindex 後可被 RAG 搜尋
- [ ] 無效 URL 會顯示錯誤
- [ ] blocked domain 會顯示錯誤
- [ ] provider 不可達時會回 timeout / upstream error
- [ ] 既有檔案上傳與手動編輯流程不受影響
- [ ] `WebCrawlerPlugin` 仍可正常運作

---

## 目前還缺的部分

以下是目前 code 還沒補齊，或至少還沒被驗證完的部分：

1. 還缺 backend route 的正式測試  
目前有 adapter test 和 plugin test，但還沒有直接覆蓋 `POST /api/knowledge/crawl` 的 route test。

2. 還缺 admin -> backend -> brain 的端到端驗證  
目前有局部測試，但還沒把「貼網址後真的寫進 knowledge」這條完整手測或自動測試補起來。

3. 噪音清理規則還是 heuristic  
首頁類型頁面像 `cnn.com` 這種 still 可能會留下很多導覽內容；目前不是 parser 壞掉，而是內容清理還只是 MVP 規則。

4. 還沒有 preview step  
現在是直接 crawl -> ingest，沒有像 NotebookLM 那種「先預覽、再確認匯入」。

5. 還沒有 queue / worker 版本  
目前是同步流程，慢頁面或 provider 不穩時，使用者會直接等這個 request 完成。

---

## 暫不做

- 不做批次 URL 匯入
- 不做聊天引用網址
- 不把整頁內容寫進 memory
- 不新增 Brain 端的專用 ingest 端點（直接走 upload）
- 不做通用 plugin 平台 UI
- 不做 preview / approve flow
- 不做 queue-based async ingest
