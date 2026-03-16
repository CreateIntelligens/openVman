# TASK-15: GCP Fallback Adapter and Fallback Metrics

> Issue: #24 — GCP fallback adapter and fallback metrics
> Epic: #5
> Branch: `feature/backend`
> Status: **Planned**

---

## 開發需求

在 TTS router 中補上 GCP 作為第二層雲端 fallback provider，並把 node/provider hop 與 fallback 命中情況轉成可供 dashboard 使用的 metrics。

| 需求 | 說明 |
|------|------|
| GCP adapter contract | 定義與 AWS 同型的 GCP provider adapter |
| fallback hit-rate metrics | 記錄 node/provider hop、命中率、chain exhausted |
| provider chain tests | 驗證 `node -> AWS -> GCP` 的完整 chain |
| dashboard-ready counters | metrics 名稱與 labels 可直接做 dashboard |
| scope control | 本 task 不再擴第三個 provider，只做到 GCP |

---

## 現況分析

### 已有資料

| 來源 | 內容 |
|------|------|
| [01_BACKEND_SPEC.md](/home/human/openVman/01_BACKEND_SPEC.md#L78) | 已明確把 GCP 列為 AWS 之外的雲端備援方案 |
| [01_BACKEND_SPEC.md](/home/human/openVman/01_BACKEND_SPEC.md#L95) | 已要求雲端 provider 失敗時可在 AWS / GCP 間切換 |
| [08_PROJECT_PLAN_2MONTH.md](/home/human/openVman/08_PROJECT_PLAN_2MONTH.md#L43) | 專案計畫已列出 node fallback、AWS/GCP fallback、錯誤分類、熔斷計數 |
| [TASK-13-tts-node-health-scoring-and-primary-secondary-failover.md](/home/human/openVman/docs/plans/TASK-13-tts-node-health-scoring-and-primary-secondary-failover.md#L1) | 已規劃 self-hosted node router |
| [TASK-14-aws-fallback-adapter-for-tts-router.md](/home/human/openVman/docs/plans/TASK-14-aws-fallback-adapter-for-tts-router.md#L1) | 已規劃 AWS 作為第一層雲端 fallback |

### 缺口

| 缺口 | 說明 |
|------|------|
| 沒有 GCP adapter | router chain 尚未延伸到第二個雲端 provider |
| 沒有完整 fallback chain 測試 | 尚未驗證 node/AWS/GCP 的完整跳轉順序 |
| 沒有 fallback metrics | 看不到 node hop、provider hop、chain exhausted 的可觀測數據 |
| 沒有 dashboard-ready labels | 現有 router plan 尚未定義可直接聚合的 metrics labels |

### 前置依賴

- 本 task 依賴 task13 router 與 task14 AWS adapter 先存在

---

## 開發方法

### 架構

```text
router chain
    ├─ self-hosted primary
    ├─ self-hosted secondary
    ├─ AWS provider
    └─ GCP provider

on each hop:
    ├─ record route attempt
    ├─ record fallback hop
    ├─ classify failure
    └─ stop on first success
```

### 設計決策

1. **GCP adapter 跟 AWS adapter 同 contract**  
   provider adapter 介面保持一致，router 只看 normalized result 與 classified error。

2. **chain 順序固定**  
   `primary -> secondary -> aws -> gcp`，不做動態成本優化。

3. **metrics 以 counter 為主**  
   task15 先補 counters / basic timings，避免在 router 初期就把 observability 做過重。

4. **dashboard labels 只保留必要維度**  
   labels 儘量固定為 `from_kind/from_target/to_kind/to_target/reason/result`，避免高 cardinality。

---

## 實作步驟

| 步驟 | 內容 | 產出檔案 |
|------|------|---------|
| 1. GCP config | 補 GCP project、credentials、voice 設定 | `backend/tts_router/app/config.py` |
| 2. GCP adapter | 實作 Google Cloud TTS adapter 與 normalization | `backend/tts_router/app/providers/gcp_adapter.py` |
| 3. provider chain | 在 router 中接上 `aws -> gcp` 的後續 hop | `backend/tts_router/app/service.py` |
| 4. fallback metrics | 補 hop counters、provider counters、chain exhausted counters | `backend/tts_router/app/observability.py` |
| 5. provider chain tests | 補節點失敗、AWS 失敗、GCP 成功與全鏈失敗測試 | `backend/tts_router/tests/*` |

---

## 詳細設計

### 1. GCP adapter config

```env
TTS_GCP_ENABLED=true
TTS_GCP_PROJECT_ID=my-project
TTS_GCP_CREDENTIALS_JSON=/secrets/gcp-tts.json
TTS_GCP_VOICE_NAME=cmn-TW-Standard-A
TTS_GCP_AUDIO_ENCODING=LINEAR16
TTS_GCP_SAMPLE_RATE=24000
```

### 2. provider chain

固定順序：

1. `node:tts-primary`
2. `node:tts-secondary`
3. `provider:aws`
4. `provider:gcp`

停止條件：
- 任一 hop 成功即停止
- 四條都失敗則回 router error

### 3. Metrics

建議 counters：

```text
tts_route_attempts_total{kind,target,result}
tts_fallback_hops_total{from_kind,from_target,to_kind,to_target,reason}
tts_provider_requests_total{provider,result}
tts_provider_failures_total{provider,reason}
tts_chain_exhausted_total{final_reason}
```

可選 timing：

```text
tts_provider_latency_ms{provider,result}
```

### 4. GCP error mapping

首版分類：
- invalid credentials -> `auth_error`
- quota exceeded / resource exhausted -> `rate_limited`
- invalid argument -> `bad_request`
- unavailable / deadline exceeded -> `provider_unavailable`

---

## 測試案例

| 測試 | 驗證內容 |
|------|---------|
| `test_gcp_adapter_returns_normalized_result` | GCP 回傳被轉成 internal result shape |
| `test_router_falls_back_to_gcp_after_node_and_aws_failures` | 前面路徑都失敗後會改走 GCP |
| `test_fallback_metrics_record_node_and_provider_hops` | metrics 可看出 node/provider hop |
| `test_chain_exhausted_metric_increments_when_all_routes_fail` | 全鏈失敗時會記錄 exhausted counter |
| `test_provider_chain_order_is_bounded_and_stable` | 單次請求只走固定且有限的 chain |

---

## 驗收方法

### 自動驗收

| 檢查項目 | 指令 | 驗證內容 |
|---------|------|---------|
| GCP adapter 測試 | `python3 -m pytest backend/tts_router/tests/test_gcp_adapter.py -v` | adapter contract |
| provider chain 測試 | `python3 -m pytest backend/tts_router/tests/test_provider_chain.py -v` | AWS/GCP chain |
| metrics 測試 | `python3 -m pytest backend/tts_router/tests/test_fallback_metrics.py -v` | hop / exhausted metrics |
| 全 router 測試 | `python3 -m pytest backend/tts_router/tests/ -v` | 不打壞 task13/14 |

### 手動驗收

| 檢查項目 | 指令 | 驗證內容 |
|---------|------|---------|
| GCP fallback | 停節點並讓 AWS mock 失敗後送 synthesize | 仍由 GCP 成功回音訊 |
| hop metrics | 查看 metrics snapshot | 能看到 node -> aws -> gcp hop |
| full chain failure | 人工讓四條路徑都失敗 | 有 exhausted metric 與明確錯誤 |

### 驗收標準對照

| 驗收標準 | 如何確認 |
|---------|---------|
| 前面路徑失敗後可改走 GCP | provider chain 測試與手動模擬失敗 |
| metrics 可看出 node / provider hop | metrics 測試與 metrics snapshot |
| 完整 fallback chain 測試通過 | provider chain 測試全綠 |

---

## 檔案清單

| 檔案 | 動作 | 用途 |
|------|------|------|
| `backend/tts_router/app/providers/gcp_adapter.py` | 新增 | GCP TTS adapter |
| `backend/tts_router/app/observability.py` | 新增 | fallback metrics 與 snapshot |
| `backend/tts_router/app/config.py` | 修改 | GCP 設定 |
| `backend/tts_router/app/service.py` | 修改 | `aws -> gcp` provider chain |
| `backend/tts_router/tests/test_gcp_adapter.py` | 新增 | GCP adapter 測試 |
| `backend/tts_router/tests/test_provider_chain.py` | 新增 | 全 fallback chain 測試 |
| `backend/tts_router/tests/test_fallback_metrics.py` | 新增 | hop / exhausted metrics 測試 |
| `docs/plans/TASK-15-gcp-fallback-adapter-and-fallback-metrics.md` | 新增 | 計畫書（本文件） |

