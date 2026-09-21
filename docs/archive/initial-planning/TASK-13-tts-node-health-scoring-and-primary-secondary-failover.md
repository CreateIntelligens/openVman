# TASK-13: TTS Node Health Scoring and Primary-Secondary Failover

> Issue: #22 — TTS node health scoring and primary-secondary failover
> Epic: #5
> Branch: `feature/brain`
> Status: **Draft**

---

## 開發需求

當優先 TTS provider 失敗時，自動切換到下一個 provider，確保語音合成服務不中斷。

| 需求 | 說明 |
|------|------|
| health checks | 每次請求時檢查 provider 是否可用（enabled + 呼叫是否成功） |
| score / cooldown tracking | 透過 fallback chain 順序與錯誤分類追蹤各 provider 狀態 |
| primary-secondary failover order | 固定優先順序：Index TTS → GCP → AWS → Edge-TTS |
| structured logs for switching | 每次路由嘗試、fallback hop、chain 耗盡都有結構化日誌與 reason |

---

## 架構

```text
tts-router (單一容器, port 8200)
    ├─ POST /v1/synthesize
    ├─ GET /healthz
    ├─ GET /metrics
    └─ Provider Fallback Chain
         ├─ 1. Index TTS (HTTP)
         ├─ 2. GCP Cloud TTS
         ├─ 3. AWS Polly
         └─ 4. Edge-TTS (in-process)
```

---

## 設計決策

1. **單一容器，所有 provider in-process 或 HTTP 呼叫**
   edge-tts 輕量不需獨立容器，雲端 provider 透過 SDK，Index TTS 透過 HTTP。

2. **chain 順序固定**
   Index TTS → GCP → AWS → Edge-TTS，不做動態調整。

3. **統一 `ProviderAdapter` protocol**
   `provider_name`、`enabled`、`synthesize(request) -> NormalizedTTSResult`。

4. **錯誤分類標準化**
   `auth_error`、`rate_limited`、`bad_request`、`network_error`、`provider_unavailable`、`unknown_error`。

5. **Edge-TTS 作為最終備援**
   預設啟用，確保至少有一個 provider 可用。

---

## 驗收標準對照

| 驗收標準（Issue #22） | 實作方式 |
|----------------------|---------|
| unhealthy primary node is bypassed automatically | 任一 provider 失敗時自動跳到 chain 中下一個 |
| failover choice is logged with reasons | `tts_route_attempt`、`tts_fallback_hop` 事件含 target 與 reason |
| node recovers after cooldown when healthy again | 每次請求重新走 chain，無需 cooldown；provider 恢復即自然命中 |

---

## 測試案例

| 測試 | 驗證內容 |
|------|---------|
| `test_index_success_returns_immediately` | 第一個 provider 成功時不走後續 |
| `test_index_fails_falls_back_to_gcp` | 第一個失敗 → 自動切到第二個 |
| `test_all_providers_fail_raises` | 全部失敗 → RuntimeError |
| `test_chain_order_is_index_then_gcp_then_aws` | chain 順序固定 |
| `test_fallback_hop_is_recorded` | fallback hop 有 structured log 與 reason |
| `test_chain_exhausted_is_recorded` | 全鏈失敗有 structured log |

---

## 驗收方法

### 自動驗收

| 指令 | 驗證內容 |
|------|---------|
| `python3 -m pytest backend/tts_router/tests/ -v` | 全部測試通過 |

### 手動驗收

| 指令 | 驗證內容 |
|------|---------|
| `docker compose -f backend/docker-compose.yml up --build` | tts-router 容器啟動正常 |
| `curl -X POST localhost:8200/v1/synthesize -H 'Content-Type: application/json' -d '{"text":"測試"}'` | 回傳音檔 |
| `curl localhost:8200/healthz` | `{"status": "ok", "service": "tts-router"}` |

---

## 檔案清單

| 檔案 | 用途 |
|------|------|
| `backend/tts_router/app/providers/base.py` | provider adapter protocol 與 `NormalizedTTSResult` |
| `backend/tts_router/app/providers/edge_tts_adapter.py` | in-process edge-tts adapter |
| `backend/tts_router/app/providers/aws_adapter.py` | AWS Polly adapter |
| `backend/tts_router/app/providers/gcp_adapter.py` | GCP Cloud TTS adapter |
| `backend/tts_router/app/providers/index_tts_adapter.py` | Index TTS adapter (HTTP) |
| `backend/tts_router/app/providers/error_mapping.py` | provider 錯誤分類 |
| `backend/tts_router/app/config.py` | 環境變數設定 |
| `backend/tts_router/app/service.py` | fallback chain 路由邏輯 |
| `backend/tts_router/app/main.py` | FastAPI 入口 |
| `backend/tts_router/app/observability.py` | metrics 與 structured logging |
| `backend/docker-compose.yml` | 容器編排 |
