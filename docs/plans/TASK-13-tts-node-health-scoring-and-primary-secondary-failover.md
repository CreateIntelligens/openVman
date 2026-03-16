# TASK-13: TTS Node Health Scoring and Primary-Secondary Failover

> Issue: #22 — TTS node health scoring and primary-secondary failover
> Epic: #5
> Branch: `feature/backend`
> Status: **Planned**

---

## 開發需求

建立一個位於自建 TTS worker 前方的 router/gateway，先在 self-hosted TTS nodes 之間做主備切換與健康評分，只有在後續 task 才往 cloud provider fallback 擴展。

| 需求 | 說明 |
|------|------|
| node health checks | 定期檢查 primary / secondary TTS nodes 的 `/healthz` 狀態 |
| node score / cooldown tracking | 對節點維護分數、失敗次數、cooldown 到期時間與最近錯誤 |
| primary-secondary failover order | primary 異常時自動跳過，改選 secondary |
| structured logs | 節點選擇、略過、切換、恢復都要記錄原因 |
| recovery | cooldown 後節點恢復健康時可重新納入候選 |
| scope control | 本 task 只做 self-hosted node failover，不做 AWS/GCP provider fallback |

---

## 現況分析

### 已有資料

| 來源 | 內容 |
|------|------|
| [01_BACKEND_SPEC.md](/home/human/openVman/01_BACKEND_SPEC.md#L100) | 後端已要求對 TTS 依賴有 fallback 思維 |
| [01_BACKEND_SPEC.md](/home/human/openVman/01_BACKEND_SPEC.md#L103) | 已明確規定先做自建 TTS 節點 fallback |
| [01_BACKEND_SPEC.md](/home/human/openVman/01_BACKEND_SPEC.md#L107) | 降級順序要求先切 node，再切 speaker，再切 provider |
| [01_BACKEND_SPEC.md](/home/human/openVman/01_BACKEND_SPEC.md#L171) | 已有 `TTS_PRIMARY_NODE` / `TTS_SECONDARY_NODE` 環境變數方向 |
| [08_PROJECT_PLAN_2MONTH.md](/home/human/openVman/08_PROJECT_PLAN_2MONTH.md#L43) | 專案計畫已列出 node fallback、錯誤分類、熔斷計數 |
| [TASK-10-indextts2-service-bootstrap-and-inference-api.md](/home/human/openVman/docs/plans/TASK-10-indextts2-service-bootstrap-and-inference-api.md#L1) | task10 已規劃單一 TTS worker 的 `/healthz` 與 `/v1/synthesize` 合約 |
| [TASK-11-zh-tw-speaker-profile-and-pronunciation-override-support.md](/home/human/openVman/docs/plans/TASK-11-zh-tw-speaker-profile-and-pronunciation-override-support.md#L1) | task11 已規劃 speaker/profile 與 pronunciation config，router 可視為透明轉發 |

### 缺口

| 缺口 | 說明 |
|------|------|
| 沒有 TTS router/gateway | 現在只有單一 worker 規劃，沒有 upstream node 選擇邏輯 |
| 沒有節點健康狀態模型 | 尚未定義 node score、cooldown、最近失敗原因 |
| 沒有自動 bypass primary | primary 異常時，沒有機制自動切到 secondary |
| 沒有恢復機制 | secondary 代打後，primary 健康恢復時也沒有重新納入候選 |
| 沒有結構化切換日誌 | 無法在 log 中清楚知道為什麼切 node |

### 前置依賴

- 本 task 預設 task10 的 worker node contract 已存在：`GET /healthz`、`POST /v1/synthesize`
- task11 的 speaker/profile 資訊由 router 透明轉發，不在本 task 重新解析

---

## 開發方法

### 架構

```text
backend/tts_router
    ├─ FastAPI app
    │   ├─ GET /healthz
    │   └─ POST /v1/synthesize
    ├─ NodeRegistry
    │   ├─ primary node
    │   └─ secondary node
    ├─ NodeHealthTracker
    │   ├─ score
    │   ├─ consecutive_failures
    │   ├─ cooldown_until
    │   └─ last_error
    ├─ NodeSelector
    │   └─ choose best healthy node
    └─ NodeClient
         ├─ call /healthz
         └─ forward /v1/synthesize
```

### 設計決策

1. **router 與 worker 分離**  
   task10/11 的 `backend/tts_service/` 視為 worker node；task13 新增 `backend/tts_router/` 做前置路由，避免把推理與 failover 狀態攪在一起。

2. **先做 node failover，不碰 provider failover**  
   本 task 只覆蓋 self-hosted path：primary -> secondary。雲端 provider fallback 放後續 task。

3. **主排序固定，健康分數輔助**  
   在兩個 node 都健康時，仍優先 primary；只有 primary degraded / cooldown / unreachable 時才切 secondary。

4. **主動 health check + 被動失敗回報併用**  
   背景 health probe 負責恢復判斷；實際 synthesize timeout/5xx 則即時扣分、進 cooldown。

5. **cooldown 是暫時逐出，不是永久封鎖**  
   node 冷卻結束且健康檢查恢復後，應重新成為候選。

6. **failover 必須有原因碼**  
   log 至少標示 `timeout`、`network_error`、`5xx`、`health_probe_failed`、`cooldown_active`。

---

## 實作步驟

| 步驟 | 內容 | 產出檔案 |
|------|------|---------|
| 1. 建立 router 服務骨架 | 建 `backend/tts_router/` 根目錄、app/tests/scripts 與依賴檔 | `backend/tts_router/*` |
| 2. node config 與 loader | 定義 primary/secondary node 設定與載入 | `backend/tts_router/config/nodes.yaml` `backend/tts_router/app/config.py` |
| 3. node health tracker | 實作 score、cooldown、failure count、recovery state | `backend/tts_router/app/node_health.py` |
| 4. node client | 實作 upstream `/healthz` 與 `/v1/synthesize` 呼叫 | `backend/tts_router/app/node_client.py` |
| 5. selector 與 failover policy | 實作 primary-first 選擇、失敗後切 secondary 的規則 | `backend/tts_router/app/node_selector.py` |
| 6. router service path | `POST /v1/synthesize` 透過 selector 挑 node，必要時 failover 重試一次 | `backend/tts_router/app/service.py` |
| 7. structured logs | 補 node selected / bypassed / failover / recovered 事件 | `backend/tts_router/app/logging.py` 或 service/node_health |
| 8. health endpoint | `/healthz` 回 router 狀態與各 node 當前 health/score | `backend/tts_router/app/main.py` |
| 9. 測試與 smoke | 補 failover、cooldown、recovery、log reason 測試與手動腳本 | `backend/tts_router/tests/*` `backend/tts_router/scripts/*` |

---

## 詳細設計

### 1. 服務與 worker 邊界

目標結構：

```text
backend/
├── tts_service/   # task10/11 的單一 worker node
└── tts_router/    # task13 的 failover gateway
```

router 對外提供統一入口：
- `GET /healthz`
- `POST /v1/synthesize`

router 對內呼叫多個 task10 worker nodes：
- `http://tts-node-a:9000/healthz`
- `http://tts-node-a:9000/v1/synthesize`
- `http://tts-node-b:9000/healthz`
- `http://tts-node-b:9000/v1/synthesize`

### 2. node config

`backend/tts_router/config/nodes.yaml`

```yaml
nodes:
  - node_id: tts-primary
    base_url: http://tts-node-a:9000
    priority: 100
    role: primary

  - node_id: tts-secondary
    base_url: http://tts-node-b:9000
    priority: 50
    role: secondary

policy:
  failure_threshold: 2
  cooldown_seconds: 30
  healthcheck_interval_seconds: 10
  request_timeout_ms: 4000
```

規則：
- primary / secondary 由 config 定義，不寫死在程式
- `priority` 為 tie-breaker，預設 primary > secondary

### 3. node state model

建議結構：

```python
@dataclass
class NodeState:
    node_id: str
    role: str
    base_url: str
    priority: int
    score: int
    consecutive_failures: int
    cooldown_until: float | None
    last_error: str
    last_status_code: int | None
    last_latency_ms: float | None
    healthy: bool
```

初始值：
- `score = 100`
- `consecutive_failures = 0`
- `healthy = True`

### 4. score / cooldown policy

首版簡化規則：

- `2xx / healthy probe`:
  - `consecutive_failures = 0`
  - `score` 緩慢回升，最高回到 `100`
  - 若原本在 cooldown 且 probe 成功，解除 cooldown

- `timeout / network error / 5xx`:
  - `consecutive_failures += 1`
  - `score -= 50`
  - 若失敗次數達 `failure_threshold`，進入 cooldown

- `cooldown active`:
  - 不作為候選
  - 但 health probe 繼續執行

### 5. node selection policy

選擇邏輯：

1. 先過濾掉 `cooldown active` 或 `healthy=False` 的 node
2. 候選中優先依 `priority` 排序
3. `priority` 相同時，再看 `score`
4. 本 task 僅允許單次 failover：
   - 先打 primary
   - 失敗時標記 primary
   - 若 secondary 可用，立即重試 secondary

不做的事：
- 不做多輪 retry storm
- 不做 load balancing
- 不做跨 provider fallback

### 6. structured log events

至少記錄：

```text
tts_node_selected
tts_node_bypassed
tts_node_failover
tts_node_marked_unhealthy
tts_node_recovered
```

欄位至少包含：
- `trace_id`
- `request_id`
- `from_node`
- `to_node`
- `reason`
- `status_code`
- `latency_ms`
- `cooldown_seconds`

### 7. router health endpoint

`GET /healthz`

```json
{
  "status": "ok",
  "service": "tts-router",
  "nodes": [
    {
      "node_id": "tts-primary",
      "role": "primary",
      "healthy": false,
      "score": 0,
      "cooldown_active": true,
      "last_error": "timeout"
    },
    {
      "node_id": "tts-secondary",
      "role": "secondary",
      "healthy": true,
      "score": 100,
      "cooldown_active": false,
      "last_error": ""
    }
  ]
}
```

---

## 測試案例

| 測試 | 驗證內容 |
|------|---------|
| `test_primary_selected_when_both_nodes_healthy` | primary 正常時仍優先選 primary |
| `test_unhealthy_primary_is_bypassed_automatically` | primary unhealthy/cooldown 時自動切 secondary |
| `test_failover_reason_logged_on_primary_timeout` | primary timeout 時會有 `tts_node_failover` log 與 reason |
| `test_node_enters_cooldown_after_threshold_failures` | 連續失敗達門檻後進 cooldown |
| `test_node_recoveres_after_cooldown_and_successful_probe` | cooldown 後健康檢查成功可重新納入候選 |
| `test_router_retries_secondary_once_after_primary_5xx` | primary 5xx 時會嘗試 secondary 一次 |
| `test_no_failover_when_secondary_also_unhealthy` | 兩個 node 都壞時回清楚錯誤，不進無限重試 |
| `test_healthz_reports_node_state_and_scores` | `/healthz` 能回各 node 的 health/score/cooldown |
| `test_nodes_loaded_from_config_not_hardcoded` | node 清單由 config 載入，不寫死在 code |

---

## 驗收方法

### 自動驗收

| 檢查項目 | 指令 | 驗證內容 |
|---------|------|---------|
| selector 測試 | `python3 -m pytest backend/tts_router/tests/test_node_selector.py -v` | primary/secondary 選擇邏輯 |
| health tracker 測試 | `python3 -m pytest backend/tts_router/tests/test_node_health.py -v` | score、cooldown、recovery |
| service 測試 | `python3 -m pytest backend/tts_router/tests/test_service_failover.py -v` | synthesize failover path |
| health endpoint 測試 | `python3 -m pytest backend/tts_router/tests/test_healthz.py -v` | router health metadata |
| 全 router 測試 | `python3 -m pytest backend/tts_router/tests/ -v` | 不打壞 node failover 邏輯 |

### 手動驗收

| 檢查項目 | 指令 | 驗證內容 |
|---------|------|---------|
| primary down 切 secondary | 停掉 primary worker 後送 `POST /v1/synthesize` | 請求仍成功，由 secondary 回音訊 |
| failover log | 查看 router logs | 有 `tts_node_failover` 並附 reason |
| recovery | 重新啟動 primary，等待 cooldown 後再送請求 | primary 可重新成為候選 |

### 驗收標準對照

| 驗收標準 | 如何確認 |
|---------|---------|
| primary node 異常時可自動切到 secondary | service failover 測試與手動停 primary 驗證 |
| 切換原因會記錄在 logs | `tts_node_failover` / `tts_node_bypassed` log 含 reason |
| 恢復後可重新納入候選 | cooldown + successful probe 後，selector 다시選得到 primary |

---

## 檔案清單

| 檔案 | 動作 | 用途 |
|------|------|------|
| `backend/tts_router/config/nodes.yaml` | 新增 | primary / secondary node 與 policy 設定 |
| `backend/tts_router/app/main.py` | 新增 | router FastAPI 入口與 `/healthz`、`/v1/synthesize` |
| `backend/tts_router/app/config.py` | 新增 | router 環境變數與 config 載入 |
| `backend/tts_router/app/node_client.py` | 新增 | upstream worker 呼叫 |
| `backend/tts_router/app/node_health.py` | 新增 | score / cooldown / recovery 狀態管理 |
| `backend/tts_router/app/node_selector.py` | 新增 | primary-first 選擇與 failover policy |
| `backend/tts_router/app/service.py` | 新增 | synthesize routing 與 structured logs |
| `backend/tts_router/tests/test_node_selector.py` | 新增 | node 選擇邏輯測試 |
| `backend/tts_router/tests/test_node_health.py` | 新增 | 健康評分與 cooldown 測試 |
| `backend/tts_router/tests/test_service_failover.py` | 新增 | primary-secondary failover 測試 |
| `backend/tts_router/tests/test_healthz.py` | 新增 | router health endpoint 測試 |
| `backend/tts_router/scripts/failover_smoke.py` | 新增 | 手動 failover 驗收腳本 |
| `backend/tts_router/Dockerfile` | 新增 | router 容器化 |
| `backend/tts_router/docker-compose.yml` | 新增 | router + 兩個 worker 的 dev 啟動 |
| `backend/tts_router/requirements.txt` | 新增 | router Python 依賴 |
| `docs/plans/TASK-13-tts-node-health-scoring-and-primary-secondary-failover.md` | 新增 | 計畫書（本文件） |
