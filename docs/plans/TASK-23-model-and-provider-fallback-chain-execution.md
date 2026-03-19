# TASK-23: Model and Provider Fallback Chain Execution

> Issue: #32 — Model and provider fallback chain execution
> Epic: #8
> Branch: `feature/brain`
> Status: **Draft**

---

## 開發需求

完成 bounded 的 model / provider fallback chain，能在同 provider 模型失敗時切次模型，必要時跨 provider 切換，且單次請求要維持同一條 traceable chain。

| 需求 | 說明 |
|------|------|
| same-provider model fallback | 同 provider 內主模型失敗可切次模型 |
| cross-provider chain | 同 provider 失敗後可切下一個 provider |
| retry policy preserving trace continuity | 單次請求在同一條 bounded chain 內完成 |
| bounded hop count | 單次請求 hop 數有限，避免無限輪轉 |
| router-visible logs | router 決策與 hop 必須可見 |

---

## 現況分析

### 已有資料

| 來源 | 內容 |
|------|------|
| [03_BRAIN_SPEC.md](docs/03_BRAIN_SPEC.md#L185) | 已要求同 provider 多 key fallback |
| [03_BRAIN_SPEC.md](docs/03_BRAIN_SPEC.md#L186) | 已要求同 provider 多 model fallback |
| [03_BRAIN_SPEC.md](docs/03_BRAIN_SPEC.md#L187) | 已要求跨 provider fallback |
| [03_BRAIN_SPEC.md](docs/03_BRAIN_SPEC.md#L200) | 已要求同一次對話綁定在同一條 fallback chain |
| [llm_client.py](brain/api/core/llm_client.py#L1) | 現有 client 已有 route loop，但還是簡單線性嘗試 |
| [provider_router.py](brain/api/core/provider_router.py#L1) | 現有 router 只處理單 provider key/model 的簡化 route |

### 缺口

| 缺口 | 說明 |
|------|------|
| 沒有正式 fallback chain 模型 | 現在 route 嘗試沒有明確的 chain object |
| 沒有 cross-provider 配置 | 尚未定義 `provider:model` 的完整 chain |
| 沒有 bounded hop count | 沒有顯式 hop 限制與 chain 終止條件 |
| trace continuity 不完整 | fallback hop 與原 request trace 尚未明確綁定 |

---

## 開發方法

### 架構

```text
request(trace_id)
    │
    ├─ build fallback chain
    │    ├─ provider A / model 1 / key pool
    │    ├─ provider A / model 2 / key pool
    │    ├─ provider B / model 1 / key pool
    │    └─ provider C / model 1 / key pool
    │
    └─ execute bounded hops
         ├─ classify failure
         ├─ decide next hop
         └─ stop on first success or hop limit
```

### 設計決策

1. **把 fallback chain 顯式化**  
   不再在 `for route in iter_routes()` 裡隱式疊邏輯，改成明確的 chain plan。

2. **single request, single bounded chain**  
   同一請求內只跑一條 chain，不能重建多條亂跳。

3. **同 provider 先換 model，再換 provider**  
   與 spec 一致，先用較低成本的同 provider fallback。

4. **429 / 5xx 是 fallback 觸發條件，4xx auth 走 task22 key handling**  
   auth invalid 先交給 key pool 處理；provider / model hop 主要針對 rate limit、quota、5xx、timeout。

---

## 實作步驟

| 步驟 | 內容 | 產出檔案 |
|------|------|---------|
| 1. chain config | 定義 model/provider fallback chain 設定 | `brain/api/config.py` |
| 2. chain model | 建立 route hop / chain dataclass | `brain/api/core/provider_router.py` 或新 `brain/api/core/fallback_chain.py` |
| 3. execution logic | `llm_client` 按 bounded chain 執行 route attempts | `brain/api/core/llm_client.py` |
| 4. trace continuity | 每個 hop 都帶同一 trace id 與 hop index | `brain/api/core/llm_client.py` |
| 5. 測試 | 429 / 5xx 觸發 hop、bounded chain、logs 可見 | `brain/api/tests/test_llm_fallback_chain.py` |

---

## 詳細設計

### 1. Chain config

建議設定：

```env
BRAIN_LLM_FALLBACK_CHAIN=gemini:gemini-2.0-flash,gemini:gemini-1.5-pro,groq:llama-3.3-70b,openai:gpt-4o-mini
BRAIN_LLM_MAX_FALLBACK_HOPS=4
```

### 2. Route hop

```python
@dataclass
class RouteHop:
    provider: str
    model: str
    hop_index: int
    trace_id: str
```

### 3. Fallback rules

首版：
- 429 / quota exceeded -> 同 provider 下一模型，若沒有則跨 provider
- 5xx / timeout / connection error -> 同 provider 下一模型，若沒有則跨 provider
- auth invalid -> 交 task22 key pool disable key，該 hop 改用同 provider 其他 key；若 key pool耗盡再進 model/provider fallback

### 4. Bounded chain

規則：
- `max_hops` 到達後立即停止
- 每個 hop 最多嘗試一次
- success 後立即返回，不再繼續後面 route

---

## 測試案例

| 測試 | 驗證內容 |
|------|---------|
| `test_429_triggers_same_provider_model_fallback` | 429 時先切同 provider 次模型 |
| `test_5xx_triggers_next_hop_in_chain` | 5xx 時會正確跳下一個 hop |
| `test_request_uses_one_bounded_chain_only` | 單次請求不會無限輪轉 |
| `test_trace_id_is_preserved_across_hops` | 每個 hop 都帶同一 trace continuity |
| `test_router_logs_each_hop_decision` | logs 可看到每次 hop 決策 |

---

## 驗收方法

### 自動驗收

| 檢查項目 | 指令 | 驗證內容 |
|---------|------|---------|
| fallback chain 測試 | `python3 -m pytest brain/api/tests/test_llm_fallback_chain.py -v` | 429 / 5xx / bounded chain |
| provider router 測試 | `python3 -m pytest brain/api/tests/test_provider_router.py -v` | 與 task22 相容 |
| 全 brain 測試 | `python3 -m pytest brain/api/tests/ -v` | 不打壞現有 generate path |

### 驗收標準對照

| 驗收標準 | 如何確認 |
|---------|---------|
| 429 / 5xx 測試可正確跳路由 | fallback chain 測試 |
| 單次請求只走有限 fallback chain | bounded chain 測試 |
| router 決策在 logs 可見 | hop log 測試 |

---

## 檔案清單

| 檔案 | 動作 | 用途 |
|------|------|------|
| `brain/api/core/fallback_chain.py` | 新增 | route hop / chain dataclass 與 chain builder |
| `brain/api/core/provider_router.py` | 修改 | 與 task22 key pool、chain builder 對齊 |
| `brain/api/core/llm_client.py` | 修改 | bounded fallback chain 執行 |
| `brain/api/config.py` | 修改 | chain / hop count 設定 |
| `brain/api/tests/test_llm_fallback_chain.py` | 新增 | model/provider fallback chain 測試 |
| `docs/plans/TASK-23-model-and-provider-fallback-chain-execution.md` | 新增 | 計畫書（本文件） |

