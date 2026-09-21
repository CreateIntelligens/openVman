# TASK-15: GCP Fallback Adapter and Fallback Metrics

> Issue: #24 — GCP fallback adapter and fallback metrics
> Epic: #5
> Branch: `feature/brain`
> Status: **Draft**

---

## 開發需求

在 TTS router 中補上 GCP 作為雲端 fallback provider，並將 provider hop 與 fallback 命中情況轉成可供 dashboard 使用的 metrics。

| 需求 | 說明 |
|------|------|
| GCP adapter contract | 實作 `ProviderAdapter` protocol，呼叫 Google Cloud TTS |
| fallback hit-rate metrics | 記錄 provider hop、命中率、chain exhausted |
| provider chain tests | 驗證完整 fallback chain |
| dashboard-ready counters | metrics 名稱與 labels 可直接做 dashboard |

---

## 驗收標準對照

| 驗收標準（Issue #24） | 實作方式 |
|----------------------|---------|
| router can synthesize via GCP when prior routes fail | 前面 provider 失敗時 chain 走到 GCP |
| fallback metrics show node / provider hops | `tts_route_attempts_total`、`tts_fallback_hops_total` counters |
| full chain failure tests pass | `test_chain_exhausted_is_recorded` 等測試 |

---

## 設計

### GCP adapter config

```env
TTS_GCP_ENABLED=true
TTS_GCP_PROJECT_ID=my-project
TTS_GCP_CREDENTIALS_JSON=/secrets/gcp-tts.json
TTS_GCP_VOICE_NAME=cmn-TW-Standard-A
TTS_GCP_AUDIO_ENCODING=LINEAR16
TTS_GCP_SAMPLE_RATE=24000
```

### Provider chain 順序

```text
1. Index TTS
2. GCP Cloud TTS
3. AWS Polly
4. Edge-TTS (in-process)
```

任一 hop 成功即停止，全部失敗則回 router error。

### Metrics

```text
tts_route_attempts_total{target, result}
tts_fallback_hops_total{from_target, to_target, reason}
tts_provider_requests_total{provider, result}
tts_provider_failures_total{provider, reason}
tts_chain_exhausted_total{final_reason}
tts_provider_latency_ms{target, result}
```

### GCP error mapping

| GCP 例外 | reason code |
|---|---|
| invalid credentials / unauthenticated | `auth_error` |
| quota exceeded / resource exhausted | `rate_limited` |
| invalid argument | `bad_request` |
| unavailable / deadline exceeded | `provider_unavailable` |

---

## 測試案例

| 測試 | 驗證內容 |
|------|---------|
| `test_gcp_adapter_returns_normalized_result` | GCP response 轉成 `NormalizedTTSResult` |
| `test_router_falls_back_to_gcp_after_index_fails` | Index 失敗 → GCP 接手 |
| `test_fallback_metrics_record_provider_hops` | metrics 記錄 provider hop |
| `test_chain_exhausted_metric_increments_when_all_fail` | 全鏈失敗有 exhausted counter |
| `test_provider_chain_order_is_bounded_and_stable` | 單次請求只走固定且有限的 chain |

---

## 檔案清單

| 檔案 | 用途 |
|------|------|
| `backend/tts_router/app/providers/gcp_adapter.py` | GCP Cloud TTS adapter |
| `backend/tts_router/app/observability.py` | fallback metrics 與 snapshot |
| `backend/tts_router/app/providers/error_mapping.py` | GCP 錯誤分類 |
| `backend/tts_router/app/config.py` | GCP 設定 |
| `backend/tts_router/app/service.py` | provider chain 路由邏輯 |
| `backend/tts_router/tests/test_gcp_adapter.py` | GCP adapter 測試 |
| `backend/tts_router/tests/test_fallback_metrics.py` | metrics 測試 |
