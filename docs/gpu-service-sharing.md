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

若跨機器或跨主機無法直接加入 Docker 內部網路，可透過 Nginx 統一邊界 Port（8786 / 8787）路由，並啟用 Bearer Token 鑑權：

```nginx
location /api/gpu/embedding/ {
    auth_request /auth/verify;
    client_max_body_size 10M;
    proxy_pass http://embedding:8009/;
    proxy_set_header Host $host;
}
```

---

## 4. JTAI 串接設定

JTAI 系統可直接共用 openVman 的 embedding 服務：

```env
# 在 JTAI 的 .env 中設定
EMBEDDING_MODEL=BAAI/bge-m3
EMBEDDING_SERVICE_URL=http://embedding:8009
```
JTAI 發送 `POST /embed` (`{"texts": [...], "input_type": "document"}`)，openVman embedding 服務直接回傳相容之 `{"vectors": [...]}`。

---

## 5. 生命週期與隔離規範

1. **獨立生命週期**：Provider GPU 服務獨立啟動，Consumer Worktree `docker compose down` 不得刪除共用 GPU 容器或快取 Volume (`hf-cache`)。
2. **安全原則**：所有內部端點均支援 `GATEWAY_INTERNAL_TOKEN` 鑑權，Health 與 Log 輸出自動過濾機密 Token。
3. **優雅降級**：若外部 GPU 服務中斷，Brain 自動切換至備援 Embedding Provider（如 Gemini / OpenAI），Backend 標記 VLM/TTS 為不可用，不影響核心文字功能。
