# TASK-24: Routing Observability and Circuit-Breaker Metrics

> Issue: #33 — Routing observability and circuit-breaker metrics
> Epic: #8
> Branch: `feature/brain`
> Status: **Draft**

---

## 開發需求

補齊 LLM routing 的可觀測性，讓 provider/model failure、fallback hop 與 circuit-breaker 狀態變化可在 metrics 與 logs 中被追查。

| 需求 | 說明 |
|------|------|
| fallback counters | 記錄 fallback hop 與 chain exhausted |
| provider failure metrics | provider / model failure 可在 metrics 中看見 |
| circuit-breaker state metrics | circuit-breaker open/half-open/closed 要有 state metrics |
| dashboard-ready log fields | log 欄位可支援事故後追查 |
| post-incident debugging | 能從 metrics + logs 還原 routing 決策 |

---

## 現況分析

### 已有資料

| 來源 | 內容 |
|------|------|
| [03_BRAIN_SPEC.md](docs/03_BRAIN_SPEC.md#L200) | Spec 已要求 fallback 失敗原因記入 metrics 與 structured logs |
| [observability.py](brain/api/safety/observability.py#L1) | 目前已有 lightweight metrics store 與 structured logging helper |
| [provider_router.py](brain/api/core/provider_router.py#L1) | 目前已有部分 route failure 記錄，但還不夠完整 |
| [TASK-22-llm-key-pool-manager-and-quota-aware-routing.md](docs/plans/TASK-22-llm-key-pool-manager-and-quota-aware-routing.md#L1) | task22 已規劃 key pool health / cooldown |
| [TASK-23-model-and-provider-fallback-chain-execution.md](docs/plans/TASK-23-model-and-provider-fallback-chain-execution.md#L1) | task23 已規劃 bounded model/provider fallback chain |

### 缺口

| 缺口 | 說明 |
|------|------|
| 沒有 routing metrics taxonomy | 目前沒有 provider/model failure 與 hop metrics 命名規格 |
| 沒有 circuit-breaker state metrics | 若 task22/23 引入 state，也還沒有對應 metrics |
| log fields 不完整 | 目前難以用單一 trace 還原路由決策 |
| 事故後追查成本高 | 缺少 hop index、failure reason、chain exhausted 等關鍵訊號 |

---

## 開發方法

### 架構

```text
llm route attempt
    ├─ log route_selected
    ├─ observe latency
    ├─ on failure:
    │    ├─ increment provider/model failure counters
    │    ├─ log fallback hop
    │    └─ update circuit state metrics
    └─ on exhausted:
         ├─ increment chain exhausted
         └─ log final routing summary
```

### 設計決策

1. **沿用現有 `MetricsStore`**  
   task24 不先導入 Prometheus client，先讓 metrics taxonomy 穩定。

2. **log 與 metrics 同名對齊**  
   同一概念在 log 和 metrics 使用接近的事件名 / labels，降低 debug 成本。

3. **circuit-breaker 只暴露 state，不暴露內部複雜統計**  
   dashboard 先看 `open / half_open / closed` 與 state change 次數即可。

4. **trace + hop index 是最低要求**  
   沒有 `trace_id`、`request_id`、`hop_index` 的 log 不算可追查。

---

## 實作步驟

| 步驟 | 內容 | 產出檔案 |
|------|------|---------|
| 1. metrics taxonomy | 定義 routing / circuit-breaker metrics 名稱與 labels | `brain/api/safety/observability.py` |
| 2. provider failure metrics | 在 key pool / fallback chain 實際執行處補 metrics | `brain/api/core/provider_router.py` `brain/api/core/llm_client.py` |
| 3. circuit state logging | 補 open / half-open / closed state change logs | `brain/api/core/provider_router.py` |
| 4. dashboard-ready log fields | 統一路由 log 欄位 | `brain/api/core/llm_client.py` |
| 5. 測試 | metrics snapshot 與 log fields 測試 | `brain/api/tests/test_routing_observability.py` |

---

## 詳細設計

### 1. Metrics

建議 counters：

```text
llm_route_attempts_total{provider,model,result}
llm_provider_failures_total{provider,model,reason}
llm_fallback_hops_total{from_provider,from_model,to_provider,to_model,reason}
llm_chain_exhausted_total{final_reason}
llm_circuit_breaker_state_changes_total{provider,state}
```

建議 gauges / state snapshots：

```text
llm_circuit_breaker_state{provider,state}
llm_key_pool_available_keys{provider}
```

建議 timings：

```text
llm_route_latency_ms{provider,model,result}
```

### 2. Log fields

每筆 routing log 至少包含：

- `trace_id`
- `request_id`
- `provider`
- `model`
- `hop_index`
- `result`
- `reason`
- `latency_ms`
- `chain_length`
- `circuit_state`

### 3. Circuit-breaker events

至少：

```text
llm_circuit_opened
llm_circuit_half_open
llm_circuit_closed
llm_chain_exhausted
llm_fallback_hop
```

---

## 測試案例

| 測試 | 驗證內容 |
|------|---------|
| `test_provider_and_model_failures_increment_metrics` | provider/model failure 可在 metrics 看見 |
| `test_fallback_hops_increment_counters` | 每次 hop 都有 metrics |
| `test_circuit_breaker_state_changes_are_logged` | open/half-open/closed 有 log |
| `test_chain_exhausted_is_visible_in_metrics_and_logs` | 全鏈失敗可追查 |
| `test_routing_logs_include_trace_and_hop_fields` | 事故後追查所需欄位完整 |

---

## 驗收方法

### 自動驗收

| 檢查項目 | 指令 | 驗證內容 |
|---------|------|---------|
| routing observability 測試 | `python3 -m pytest brain/api/tests/test_routing_observability.py -v` | metrics + logs |
| provider router 測試 | `python3 -m pytest brain/api/tests/test_provider_router.py -v` | 與 task22 相容 |
| fallback chain 測試 | `python3 -m pytest brain/api/tests/test_llm_fallback_chain.py -v` | 與 task23 相容 |
| 全 brain 測試 | `python3 -m pytest brain/api/tests/ -v` | 不打壞現有流程 |

### 驗收標準對照

| 驗收標準 | 如何確認 |
|---------|---------|
| provider / model failure 可在 metrics 看見 | metrics snapshot 測試 |
| circuit-breaker 狀態變化有記錄 | state change log 測試 |
| 事故後可追查路由決策 | log fields + chain exhausted 測試 |

---

## 檔案清單

| 檔案 | 動作 | 用途 |
|------|------|------|
| `brain/api/safety/observability.py` | 修改 | routing / circuit-breaker metrics taxonomy |
| `brain/api/core/provider_router.py` | 修改 | provider failure 與 circuit state metrics/logs |
| `brain/api/core/llm_client.py` | 修改 | fallback hop / route logs 與 latency metrics |
| `brain/api/tests/test_routing_observability.py` | 新增 | metrics snapshot 與 log field 測試 |
| `docs/plans/TASK-24-routing-observability-and-circuit-breaker-metrics.md` | 新增 | 計畫書（本文件） |

