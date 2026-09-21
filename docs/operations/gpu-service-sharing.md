# 共用推論服務設定

本頁說明本專案的 consumer 設定與既有 Nginx 路由。服務是否已外移、網路是否共用，需核對實際部署；專案不會自動建立 `openvman-shared-gpu` 網路。

## 指定服務位置

在根目錄 `.env` 設定 consumer 能連到的服務 URL。以下是內網範例，主機名稱必須由部署網路提供：

```env
EMBEDDING_SERVICE_URL=http://embedding:8009
VISION_LLM_BASE_URL=http://vlm:8000/v1
TTS_INDEXTTS_URL=http://index-tts-vllm:8011
```

Embedding 使用 `EMBEDDING_SERVICE_TOKEN`，未設定時沿用 `GATEWAY_INTERNAL_TOKEN`；外部 VLM 使用 `VISION_LLM_API_KEY`。完整設定見 [環境變數範本](../../.env.example)，服務啟動方式見 [部署手冊](11_DEPLOYMENT.md)。

共用服務應由 provider stack 管理生命週期。Consumer 必須能解析 provider 位址；若跨 Compose 專案使用服務名稱，需另外配置雙方共用網路，不能只修改 URL。

## 經由 Nginx 存取

[現有 edge 設定](../../frontend/admin/nginx/http.d/default.conf)將 embedding 與 VLM 路徑轉發至內部服務，並轉送 Authorization。不要為共用功能另開推論服務的 host port。

| 用途 | 路徑 |
|------|------|
| Embedding 自訂介面 | `POST /api/embedding`，轉發至 `/embed` |
| Embedding OpenAI 相容介面 | `POST /api/embedding/v1/embeddings` |
| Embedding 模型清單 | `GET /api/embedding/v1/models` |
| VLM OpenAI 相容介面 | `POST /api/vlm/v1/chat/completions` |
| VLM 模型清單 | `GET /api/vlm/v1/models` |

自訂 embedding base URL 可設為 `https://<PUBLIC_DOMAIN>/api/embedding`；OpenAI client 的 base URL 為 `https://<PUBLIC_DOMAIN>/api/embedding/v1`。Consumer 的 URL 拼接與驗證行為須以該 client 實作為準，不在此宣稱其他專案已完成串接。

## 接入檢查

1. 從 consumer 容器確認 DNS、連線與服務認證可用。
2. 以小批文字驗證向量筆數、維度與 embedding identity；更換模型時核對既有索引相容性。
3. 分別驗證 VLM／TTS 的實際請求；可連線不等於權重已就緒。
4. 檢查 provider 故障時的實際行為。Fallback 取決於 client 設定與向量身分限制，不能保證任意 embedding provider 可互換。

固定 VRAM 數字、某次主機拓撲與外部專案設定不列為本手冊的保證。
