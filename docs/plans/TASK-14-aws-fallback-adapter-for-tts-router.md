# TASK-14: AWS Fallback Adapter for TTS Router

> Issue: #23 — AWS fallback adapter for TTS router
> Epic: #5
> Branch: `feature/backend`
> Status: **Planned**

---

## 開發需求

在 TTS router 中加入 AWS 作為第一層雲端 fallback provider，當 self-hosted TTS nodes 都不可用時，可改由 AWS 合成並回到 router 的統一內部格式。

| 需求 | 說明 |
|------|------|
| AWS adapter contract | 定義 router 對 AWS provider 的統一調用介面 |
| auth config | 支援 AWS 憑證、region、voice、engine 設定 |
| response normalization | AWS 回傳音訊與 metadata 需轉成 router 內部一致格式 |
| error mapping | 將 AWS provider 錯誤分類成 router 可理解的 reason codes |
| fallback integration | self-hosted nodes 失敗後可改走 AWS |
| 測試覆蓋 | adapter、normalization、error mapping、router fallback path 皆有測試 |

---

## 現況分析

### 已有資料

| 來源 | 內容 |
|------|------|
| [01_BACKEND_SPEC.md](/home/human/openVman/01_BACKEND_SPEC.md#L78) | 已明確指定 AWS 可作為雲端備援方案 |
| [01_BACKEND_SPEC.md](/home/human/openVman/01_BACKEND_SPEC.md#L81) | AWS 被定位為快速 fallback provider |
| [01_BACKEND_SPEC.md](/home/human/openVman/01_BACKEND_SPEC.md#L104) | 降級順序要求自建失敗後切雲端 provider |
| [01_BACKEND_SPEC.md](/home/human/openVman/01_BACKEND_SPEC.md#L173) | 已有 AWS 認證與 region 環境變數方向 |
| [TASK-13-tts-node-health-scoring-and-primary-secondary-failover.md](/home/human/openVman/docs/plans/TASK-13-tts-node-health-scoring-and-primary-secondary-failover.md#L1) | task13 已規劃 self-hosted node failover router |

### 缺口

| 缺口 | 說明 |
|------|------|
| 沒有 AWS provider adapter | router 目前只規劃 node path，沒有雲端 provider 實作 |
| 沒有統一 provider result shape | AWS 回傳格式尚未轉成 router 內部統一格式 |
| 沒有 AWS 錯誤分類 | 尚未定義 auth / throttling / invalid request / 5xx 的映射 |
| 沒有 node -> AWS fallback path | self-hosted 節點全壞時仍無法完成請求 |

### 前置依賴

- 本 task 依賴 task13 的 `backend/tts_router/` 骨架存在
- worker node 與 AWS adapter 都要回到同一個 internal result shape

---

## 開發方法

### 架構

```text
POST /v1/synthesize
    │
    ├─ try self-hosted nodes
    │    ├─ primary
    │    └─ secondary
    │
    └─ if all self-hosted failed
         └─ AWSPollyAdapter.synthesize(...)
                ├─ auth config
                ├─ Polly request
                ├─ response normalization
                └─ provider error mapping
```

### 設計決策

1. **AWS adapter 走 provider interface**  
   不把 AWS SDK 細節寫進 router service，透過 `ProviderAdapter` 介面隔離。

2. **先選 AWS Polly**  
   task14 以 Polly 為第一版 AWS adapter，先解決穩定備援，不追求品牌聲線一致性。

3. **統一回傳 shape**  
   AWS 與 self-hosted node 最終都回 `NormalizedTTSResult`，避免 router 下游分支爆炸。

4. **provider 錯誤要分類，不直接透傳 raw exception**  
   router 只吃標準化 reason code，如 `auth_error`、`rate_limited`、`provider_unavailable`。

5. **本 task 不做 provider chain metrics**  
   metrics 與完整 chain observability 留給 task15/24。

---

## 實作步驟

| 步驟 | 內容 | 產出檔案 |
|------|------|---------|
| 1. provider interface | 定義 AWS 與未來 GCP 共用的 adapter contract | `backend/tts_router/app/providers/base.py` |
| 2. AWS config | 補 AWS 憑證、region、voice、engine 設定 | `backend/tts_router/app/config.py` |
| 3. AWS adapter | 實作 Polly synthesize 與 response normalization | `backend/tts_router/app/providers/aws_adapter.py` |
| 4. error mapping | 定義 AWS 專屬錯誤 -> router reason code | `backend/tts_router/app/providers/error_mapping.py` |
| 5. router integration | self-hosted nodes 失敗後改走 AWS | `backend/tts_router/app/service.py` |
| 6. 測試 | adapter、error mapping、router fallback 測試 | `backend/tts_router/tests/*` |

---

## 詳細設計

### 1. Internal result shape

建議統一為：

```python
@dataclass
class NormalizedTTSResult:
    audio_bytes: bytes
    content_type: str
    sample_rate: int
    provider: str
    route_kind: str   # "node" | "provider"
    route_target: str
    latency_ms: float
    raw_metadata: dict[str, Any]
```

### 2. AWS adapter config

建議環境變數：

```env
TTS_AWS_ENABLED=true
TTS_AWS_REGION=ap-northeast-1
TTS_AWS_ACCESS_KEY_ID=***
TTS_AWS_SECRET_ACCESS_KEY=***
TTS_AWS_POLLY_VOICE_ID=Mizuki
TTS_AWS_POLLY_ENGINE=neural
TTS_AWS_OUTPUT_FORMAT=pcm
TTS_AWS_SAMPLE_RATE=24000
```

### 3. Adapter contract

```python
class ProviderAdapter(Protocol):
    def synthesize(self, request: SynthesizeRequest) -> NormalizedTTSResult:
        ...
```

AWS 請求輸入：
- `text`
- `locale`
- `sample_rate`
- `speaker_id` 或 `persona_id` 轉換出的 voice hint

### 4. Error mapping

首版分類：

| AWS 例外 | reason code |
|---|---|
| credentials missing / invalid | `auth_error` |
| throttling / too many requests | `rate_limited` |
| text too long / invalid ssml | `bad_request` |
| endpoint / network timeout | `network_error` |
| provider 5xx | `provider_unavailable` |

### 5. Router fallback order

首版固定：

1. primary node
2. secondary node
3. AWS Polly

不做：
- GCP fallback
- 多次 AWS retry
- AWS key pool

---

## 測試案例

| 測試 | 驗證內容 |
|------|---------|
| `test_aws_adapter_returns_normalized_tts_result` | AWS response 被轉成 internal result shape |
| `test_aws_adapter_maps_auth_error_correctly` | 憑證錯誤被分類為 `auth_error` |
| `test_aws_adapter_maps_throttling_correctly` | throttling 被分類為 `rate_limited` |
| `test_router_falls_back_to_aws_when_nodes_fail` | self-hosted nodes 失敗後會改走 AWS |
| `test_router_returns_normalized_aws_audio_payload` | router 對外仍回統一格式 |
| `test_router_stops_at_aws_success_without_extra_hops` | AWS 成功後不再多做 hop |

---

## 驗收方法

### 自動驗收

| 檢查項目 | 指令 | 驗證內容 |
|---------|------|---------|
| AWS adapter 測試 | `python3 -m pytest backend/tts_router/tests/test_aws_adapter.py -v` | adapter contract + error mapping |
| router fallback 測試 | `python3 -m pytest backend/tts_router/tests/test_service_fallback.py -v` | node -> AWS path |
| 全 router 測試 | `python3 -m pytest backend/tts_router/tests/ -v` | 不打壞 task13 |

### 手動驗收

| 檢查項目 | 指令 | 驗證內容 |
|---------|------|---------|
| AWS fallback | 關閉 primary/secondary nodes 後送 synthesize | 仍成功回音訊 |
| AWS normalization | 查看 router response headers / metadata | provider 標示為 `aws` 且格式一致 |
| error classification | 故意塞錯憑證或模擬 throttling | log 中 reason code 正確 |

### 驗收標準對照

| 驗收標準 | 如何確認 |
|---------|---------|
| 自建 node 失敗時可改走 AWS | router fallback 測試與手動停 node 驗證 |
| AWS 回傳格式可被內部統一格式接住 | adapter normalization 測試 |
| provider 錯誤分類正確 | AWS exception mapping 測試 |

---

## 檔案清單

| 檔案 | 動作 | 用途 |
|------|------|------|
| `backend/tts_router/app/providers/base.py` | 新增 | provider adapter 共用介面與 result shape |
| `backend/tts_router/app/providers/aws_adapter.py` | 新增 | AWS Polly adapter |
| `backend/tts_router/app/providers/error_mapping.py` | 新增 | AWS/GCP provider 錯誤分類 |
| `backend/tts_router/app/config.py` | 修改 | AWS 認證與 provider 設定 |
| `backend/tts_router/app/service.py` | 修改 | node path 失敗後接 AWS fallback |
| `backend/tts_router/tests/test_aws_adapter.py` | 新增 | AWS adapter 測試 |
| `backend/tts_router/tests/test_service_fallback.py` | 新增 | node -> AWS fallback 測試 |
| `docs/plans/TASK-14-aws-fallback-adapter-for-tts-router.md` | 新增 | 計畫書（本文件） |

