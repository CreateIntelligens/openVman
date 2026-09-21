# TASK-14: AWS Fallback Adapter for TTS Router

> Issue: #23 — AWS fallback adapter for TTS router
> Epic: #5
> Branch: `feature/brain`
> Status: **Draft**

---

## 開發需求

在 TTS router 中加入 AWS 作為雲端 fallback provider，當優先 provider 失敗時可改由 AWS 合成，並統一回傳格式。

| 需求 | 說明 |
|------|------|
| AWS adapter contract | 實作 `ProviderAdapter` protocol，呼叫 AWS Polly |
| auth config | 支援 AWS 憑證、region、voice、engine 設定 |
| response normalization | AWS 回傳音訊轉成 `NormalizedTTSResult` |
| error mapping | 將 AWS 錯誤分類為標準 reason code |

---

## 驗收標準對照

| 驗收標準（Issue #23） | 實作方式 |
|----------------------|---------|
| router can synthesize via AWS when self-hosted nodes fail | 前面 provider 失敗時 chain 自動走到 AWS Polly |
| AWS output is normalized into internal payload shape | `AWSPollyAdapter.synthesize()` 回傳 `NormalizedTTSResult` |
| provider-specific errors are classified correctly | `classify_aws_error()` 映射為 `auth_error`/`rate_limited`/`bad_request`/`network_error`/`provider_unavailable` |

---

## 設計

### AWS adapter config

```env
TTS_AWS_ENABLED=true
TTS_AWS_REGION=ap-northeast-1
TTS_AWS_ACCESS_KEY_ID=***
TTS_AWS_SECRET_ACCESS_KEY=***
TTS_AWS_POLLY_VOICE_ID=Zhiyu
TTS_AWS_POLLY_ENGINE=neural
TTS_AWS_OUTPUT_FORMAT=pcm
TTS_AWS_SAMPLE_RATE=24000
```

### Adapter contract

```python
class ProviderAdapter(Protocol):
    @property
    def provider_name(self) -> str: ...
    @property
    def enabled(self) -> bool: ...
    def synthesize(self, request: SynthesizeRequest) -> NormalizedTTSResult: ...
```

### Error mapping

| AWS 例外 | reason code |
|---|---|
| credentials missing / invalid | `auth_error` |
| throttling / too many requests | `rate_limited` |
| text too long / invalid ssml | `bad_request` |
| endpoint / network timeout | `network_error` |
| provider 5xx | `provider_unavailable` |

---

## 測試案例

| 測試 | 驗證內容 |
|------|---------|
| `test_aws_adapter_returns_normalized_tts_result` | AWS response 轉成 `NormalizedTTSResult` |
| `test_aws_adapter_maps_auth_error_correctly` | 憑證錯誤分類為 `auth_error` |
| `test_aws_adapter_maps_throttling_correctly` | throttling 分類為 `rate_limited` |
| `test_router_falls_back_to_aws_when_prior_providers_fail` | 前面 provider 失敗後走 AWS |

---

## 檔案清單

| 檔案 | 用途 |
|------|------|
| `backend/tts_router/app/providers/base.py` | provider adapter protocol 與 `NormalizedTTSResult` |
| `backend/tts_router/app/providers/aws_adapter.py` | AWS Polly adapter |
| `backend/tts_router/app/providers/error_mapping.py` | AWS 錯誤分類 |
| `backend/tts_router/app/config.py` | AWS 認證與設定 |
| `backend/tts_router/app/service.py` | fallback chain 路由邏輯 |
| `backend/tts_router/tests/test_aws_adapter.py` | AWS adapter 測試 |
| `backend/tts_router/tests/test_service_fallback.py` | fallback chain 測試 |
