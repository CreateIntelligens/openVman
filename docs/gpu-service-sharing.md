# openVman GPU Service Sharing & Topology Guide

> **Status: Draft (Pending Live Production Verification)**

## 1. 概念與架構

openVman 支援將 **BGE-M3 向量嵌入服務 (embedding)**、**視覺模型 (vlm)** 與 **語音合成 (indextts)** 抽出為獨立長駐的 GPU 服務容器。

這使得多個開發 Worktree、JTAI 或測試環境可以共用同一組 GPU 權重與顯存配置，避免重複載入模型（例如 BGE-M3 每次重複載入消耗 ~1.5GB VRAM、VLM 消耗 ~4.5GB VRAM）。

---

## 2. 網路拓撲 (Docker Network Topology)

為了保持安全邊界，GPU 服務**不需要也不對外開放獨立 Host Port**。推薦使用共用內部 Docker 網路：

```bash
# 1. 建立共用 GPU 網路
docker network create openvman-shared-gpu

# 2. 在 provider (主服務 stack) 的 compose.yaml 加入網路
networks:
  default:
    name: openvman-shared-gpu
    external: true
```

各 consumer worktree 容器只需加入此網路，並直接在 `.env` 中設定：
```env
EMBEDDING_SERVICE_URL=http://embedding:8009
VISION_LLM_BASE_URL=http://vlm:8000/v1
TTS_INDEXTTS_URL=http://index-tts-vllm:8011
```

---

## 3. Nginx 邊界轉發 (Edge Proxy Routing)

若跨機器或跨主機無法直接加入 Docker 內部網路，可透過 Nginx 統一邊界 Port（8786 / 8787）路由。Nginx 保留 `Authorization` header 並施加 request body、rate、connection 與 timeout 限制；embedding gateway 本身會以 `EMBEDDING_SERVICE_TOKEN`（未設定時沿用 `GATEWAY_INTERNAL_TOKEN`）驗證 Bearer token。

```nginx
# base URL 本身就是 embed 端點（精確比對優先於下方前綴）
location = /api/embedding {
    client_max_body_size 10M;
    proxy_set_header Authorization $http_authorization;
    proxy_pass http://embedding:8009/embed$is_args$args;
}

location ~ ^/api/embedding/(.*)$ {
    client_max_body_size 10M;
    proxy_set_header Authorization $http_authorization;
    proxy_pass http://embedding:8009/$1$is_args$args;
}
```

對外 consumer 使用的 base URL 為 `https://<PUBLIC_DOMAIN>/api/embedding`，不要把 `/embed` 加在環境變數中。

| 用途 | 端點 | 認證 |
| --- | --- | --- |
| 向量嵌入（jtai 格式） | `POST /api/embedding` | Bearer |
| 向量嵌入（OpenAI 相容） | `POST /api/embedding/v1/embeddings` | Bearer |
| 模型清單 | `GET /api/embedding/v1/models` | Bearer |
| 存活檢查 | `GET /api/embedding/health` | 公開 |
| 就緒檢查 | `GET /api/embedding/health/ready` | Bearer |

`POST /api/embedding/embed` 仍可用，但 base URL 已直接對應同一個端點，新的串接不需要再疊 `/embed`。OpenAI 相容路徑讓 consumer 可以直接使用現成的 OpenAI client，只要把 base URL 設為 `https://<PUBLIC_DOMAIN>/api/embedding/v1`。

視覺模型走同一組限制，路徑對稱：

| 用途 | 端點 | 認證 |
| --- | --- | --- |
| 視覺推論（OpenAI 相容） | `POST /api/vlm/v1/chat/completions` | Bearer |
| 模型清單 | `GET /api/vlm/v1/models` | Bearer |
| 存活檢查 | `GET /api/vlm/health` | 公開 |

兩個服務都掛在 `/api/<service>` 底下。早期的 `/api/gpu/*` 前綴已退役——推論服務不一定跑在 GPU 上，前綴描述的是部署細節而非介面。

Docker edge 預設的 HTTP `8786` 會轉向 HTTPS `8787`；直接使用 `8787` 只適合 consumer 已信任該憑證的環境，生產環境應由正式憑證的 host nginx 對外提供 `443`。

---

## 4. JTAI 串接設定

JTAI 的 `EMBEDDING_SERVICE_URL` 會優先於本地 Compose embedding service。指向 openVman edge 時，不啟用 JTAI 的 `embedding` profile：

```env
# JTAI .env
COMPOSE_PROFILES=
EMBEDDING_SERVICE_URL=https://<PUBLIC_DOMAIN>/api/embedding
EMBEDDING_SERVICE_TOKEN=<same-high-entropy-token-as-openvman>
EMBEDDING_EXPECTED_MODEL=BAAI/bge-m3
EMBEDDING_EXPECTED_DIMENSION=1024
```

同一個 private Docker network 內可改用下列 URL，其餘設定不變：

```env
EMBEDDING_SERVICE_URL=http://embedding:8009
```

JTAI 發送 `POST /embed` (`{"texts": [...], "input_type": "document"}`)。`vectors` 保留原有 JTAI contract，openVman 另外回傳 additive metadata：

- top-level `model`；
- `embedding_spec.identity`、`provider`、`model`、`dimensions`、`dtype`；
- `normalized`、`normalization`、`input_semantics`；
- `model_revision` 與 `service_revision`；
- 無機密資料的 `attempts`。

JTAI client 會檢查回傳筆數、維度、model、L2 normalization 與 input semantics。一次 encode 若分成多個 HTTP chunk，第一個 response 的 canonical identity 會鎖定後續 chunk，避免同一批資料混用不同向量規格。舊版 `/embed` 只含 `vectors` 時仍可相容讀取，但無法提供 identity 鎖定與完整 spec 驗證，不應用於新的共用部署。

---

## 5. 生命週期與隔離規範

1. **獨立生命週期**：Provider GPU 服務獨立啟動，Consumer Worktree `docker compose down` 不得刪除共用 GPU 容器或快取 Volume (`hf-cache`)。
2. **安全原則**：所有內部端點均支援 `GATEWAY_INTERNAL_TOKEN` 鑑權，Health 與 Log 輸出自動過濾機密 Token。
3. **優雅降級**：若外部 GPU 服務中斷，Brain 自動切換至備援 Embedding Provider（如 Gemini / OpenAI），Backend 標記 VLM/TTS 為不可用，不影響核心文字功能。
