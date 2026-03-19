# TASK-22: LLM Key Pool Manager and Quota-Aware Routing

> Issue: #31 — LLM key pool manager and quota-aware routing
> Epic: #8
> Branch: `feature/brain`
> Status: **Draft**

---

## 開發需求

建立 brain 的 LLM key pool 與配額感知路由，讓失效或耗盡的 key 能自動跳過，健康 key 依可預測規則被選中，並對 auth failure 做明確分類。

| 需求 | 說明 |
|------|------|
| key pool storage | 管理可用 API keys 與其狀態 |
| health / cooldown tracking | 記錄 key 健康、cooldown、最近失敗與恢復 |
| quota-aware selection | 429 / quota exhausted / insufficient credits 時能自動避開該 key |
| auth failure classification | 401/403 等 auth failure 需被正確分類與記錄 |
| predictable selection | 健康 key 的選擇規則必須穩定可測 |

---

## 現況分析

### 已有資料

| 來源 | 內容 |
|------|------|
| [03_BRAIN_SPEC.md](docs/03_BRAIN_SPEC.md#L182) | Brain 必須內建金鑰與模型回退機制 |
| [03_BRAIN_SPEC.md](docs/03_BRAIN_SPEC.md#L185) | 已要求同 provider 多 key fallback |
| [03_BRAIN_SPEC.md](docs/03_BRAIN_SPEC.md#L188) | 已要求限流 / quota exceeded 時自動切換 |
| [provider_router.py](brain/api/core/provider_router.py#L1) | 現有 router 已有基本 key cooldown 與 round-robin |
| [config.py](brain/api/config.py#L12) | 目前已有單 key 與多 key env 設定 |

### 缺口

| 缺口 | 說明 |
|------|------|
| 沒有正式 key pool state model | 目前只有 `_cooldowns` dict，缺健康狀態、失敗分類、最近成功等資訊 |
| quota-aware 規則不夠細 | 目前 429 與 quota exhausted 沒有細分 |
| auth failure 沒有明確分類 | 401/403 只進 cooldown，未區分 invalid / revoked / forbidden |
| selection policy 不夠清楚 | 現在是簡單輪轉，未明確定義 predictable healthy-key policy |

---

## 開發方法

### 架構

```text
LLM request
    │
    ├─ KeyPoolManager
    │    ├─ key registry
    │    ├─ health state
    │    ├─ cooldown / disabled
    │    └─ quota-aware selection
    │
    └─ ProviderRouter
         ├─ request route
         ├─ mark_success
         └─ classify_and_mark_failure
```

### 設計決策

1. **延續現有 `ProviderRouter`，補正式 key pool manager**  
   不重寫整個 router，先把 key 狀態抽成獨立元件。

2. **key pool 仍從 env 建立**  
   task22 先不做資料庫持久化，key storage 仍由 env 載入，但在記憶體中維護狀態。

3. **quota 與 auth 分類分開**  
   `quota_exhausted`、`rate_limited`、`auth_invalid`、`auth_forbidden` 必須分開處理，不能都等同 cooldown。

4. **predictable selection 先採穩定 round-robin among healthy keys**  
   只在 healthy keys 間輪轉；被標記 exhausted/disabled 的 key 不進候選。

---

## 實作步驟

| 步驟 | 內容 | 產出檔案 |
|------|------|---------|
| 1. key state model | 定義 key pool record 與健康狀態 | `brain/api/core/key_pool.py` |
| 2. config 對齊 | 補 key pool cooldown / disable / quota 設定 | `brain/api/config.py` |
| 3. failure classification | 實作 auth / quota / transient failure 分類 | `brain/api/core/provider_router.py` |
| 4. selection policy | healthy keys 的穩定選擇規則 | `brain/api/core/key_pool.py` `brain/api/core/provider_router.py` |
| 5. llm client 整合 | `llm_client` 改走 key pool manager | `brain/api/core/llm_client.py` |
| 6. 測試 | exhausted/invalid key skip、selection predictability、auth classification | `brain/api/tests/test_provider_router.py` |

---

## 詳細設計

### 1. Key state

```python
@dataclass
class KeyState:
    key_id: str
    api_key: str
    provider: str
    healthy: bool
    disabled: bool
    cooldown_until: float | None
    last_failure_reason: str
    consecutive_failures: int
```

### 2. Failure classification

首版分類：

| 狀況 | 類型 |
|---|---|
| 401 invalid key | `auth_invalid` |
| 403 forbidden / revoked | `auth_forbidden` |
| 429 quota exceeded / insufficient credits | `quota_exhausted` |
| 429 burst rate limit | `rate_limited` |
| timeout / connection error | `transient_error` |
| 5xx | `provider_error` |

規則：
- `auth_invalid` / `auth_forbidden` -> 直接 disable key
- `quota_exhausted` -> 長 cooldown
- `rate_limited` -> 短 cooldown
- `provider_error` / `transient_error` -> 一般 cooldown

### 3. Selection policy

規則：
1. 先過濾 disabled keys
2. 再過濾 cooldown 尚未到期的 keys
3. 在 healthy keys 間做穩定 round-robin
4. 若全部都在 cooldown，可選擇最早恢復的 key 作為最後退路，避免完全空候選

---

## 測試案例

| 測試 | 驗證內容 |
|------|---------|
| `test_exhausted_key_is_skipped_automatically` | quota exhausted key 會被跳過 |
| `test_invalid_key_is_disabled_after_auth_failure` | 401/403 key 會被 disable |
| `test_healthy_keys_are_selected_predictably` | healthy keys 的輪轉順序可預測 |
| `test_rate_limited_key_enters_short_cooldown` | burst 429 只進短 cooldown |
| `test_failure_classification_is_logged_correctly` | auth / quota / transient 分類正確 |

---

## 驗收方法

### 自動驗收

| 檢查項目 | 指令 | 驗證內容 |
|---------|------|---------|
| provider router 測試 | `python3 -m pytest brain/api/tests/test_provider_router.py -v` | key pool / classification / selection |
| llm client 測試 | `python3 -m pytest brain/api/tests/test_llm_client.py -v` | client 整合不壞 |
| 全 brain 測試 | `python3 -m pytest brain/api/tests/ -v` | 不打壞既有流程 |

### 驗收標準對照

| 驗收標準 | 如何確認 |
|---------|---------|
| 配額耗盡或失效 key 會自動跳過 | exhausted / invalid key 測試 |
| 健康 key 的選擇規則可預測 | selection policy 測試 |
| auth failure 分類正確 | failure classification 測試 |

---

## 檔案清單

| 檔案 | 動作 | 用途 |
|------|------|------|
| `brain/api/core/key_pool.py` | 新增 | key pool state 與 selection policy |
| `brain/api/core/provider_router.py` | 修改 | failure classification 與 key pool integration |
| `brain/api/core/llm_client.py` | 修改 | 改走 key pool manager |
| `brain/api/config.py` | 修改 | key pool / cooldown 設定 |
| `brain/api/tests/test_provider_router.py` | 新增 | key pool / classification / selection 測試 |
| `brain/api/tests/test_llm_client.py` | 新增或修改 | llm client 與 key pool 整合測試 |
| `docs/plans/TASK-22-llm-key-pool-manager-and-quota-aware-routing.md` | 新增 | 計畫書（本文件） |

