# TASK-11: zh-TW Speaker Profile and Pronunciation Override Support

> Issue: #21 — zh-TW speaker profile and pronunciation override support
> Epic: #4
> Branch: `feature/backend`
> Status: **Planned**

---

## 開發需求

在獨立後端 TTS 服務中加入可配置的 speaker profile、persona 對應與台灣中文發音覆寫機制，讓不同 persona 可穩定對應到品牌聲線，並能修正常見詞、數字與產品名稱讀法。

| 需求 | 說明 |
|------|------|
| speaker profile config | speaker profile 由外部設定檔管理，不可硬寫在程式裡 |
| persona-to-speaker mapping | 請求帶 `persona_id` 時可解析到對應 speaker profile |
| lexicon override hooks | 支援指定詞條發音覆寫，修正常見 zh-TW 詞讀法 |
| number / product-name rules | 支援數字與品牌/產品名的正規化或覆寫規則 |
| 推理前處理 | 發音覆寫發生在送進 TTS engine 前，避免污染 API 邊界 |
| 測試覆蓋 | persona resolve、發音覆寫、生效優先序、config 載入都要有測試 |

---

## 現況分析

### 已有資料

| 來源 | 內容 |
|------|------|
| [01_BACKEND_SPEC.md](/home/human/openVman/01_BACKEND_SPEC.md#L67) | 後端 TTS 必須支援台灣口音、品牌聲線、可控停頓與語氣 |
| [01_BACKEND_SPEC.md](/home/human/openVman/01_BACKEND_SPEC.md#L69) | 已要求以 speaker index / voice profile 管理角色聲線 |
| [01_BACKEND_SPEC.md](/home/human/openVman/01_BACKEND_SPEC.md#L70) | 已要求支援 zh-TW 發音詞典、數字/專有名詞讀法覆寫 |
| [01_BACKEND_SPEC.md](/home/human/openVman/01_BACKEND_SPEC.md#L76) | 已要求每個 persona 至少有主 speaker profile 與備援 profile |
| [08_PROJECT_PLAN_2MONTH.md](/home/human/openVman/08_PROJECT_PLAN_2MONTH.md#L41) | 專案計畫已把 speaker profile、詞典覆寫列為 zh-TW TTS 整合範圍 |
| [TASK-10-indextts2-service-bootstrap-and-inference-api.md](/home/human/openVman/docs/plans/TASK-10-indextts2-service-bootstrap-and-inference-api.md#L1) | task10 已規劃獨立 `backend/tts_service/` 服務骨架與 `/v1/synthesize` 合約 |

### 缺口

| 缺口 | 說明 |
|------|------|
| speaker profile 尚無設定機制 | 沒有 `speaker_profiles` 配置檔與載入流程 |
| persona 尚無 speaker mapping | 目前 task10 合約只有明確 `speaker_id` 概念，尚未支援 `persona_id -> profile` |
| 沒有發音覆寫層 | 還沒有 lexicon / number / product-name normalizer hook |
| 沒有覆寫優先序 | 尚未定義顯式 speaker、persona mapping、default speaker 的解析順序 |
| 沒有測試詞清單 | 尚未建立驗收用 zh-TW 詞條、數字、產品名測試樣本 |

### 前置依賴

- 本 task 依賴 task10 的獨立 TTS 服務骨架先存在
- 若 task10 尚未落地，task11 仍可先完成 config loader、resolver、normalizer 與其測試

---

## 開發方法

### 架構

```text
POST /v1/synthesize
    │
    ├─ request schema
    │    ├─ text
    │    ├─ persona_id? 
    │    └─ speaker_id?
    │
    ├─ SpeakerResolver
    │    ├─ explicit speaker_id
    │    ├─ persona_id -> profile
    │    └─ default profile
    │
    ├─ PronunciationNormalizer
    │    ├─ exact lexicon overrides
    │    ├─ product-name overrides
    │    └─ number normalization rules
    │
    └─ IndexTTS2Engine.synthesize(
           normalized_text,
           resolved_speaker_profile
       )
```

### 設計決策

1. **設定檔優先，不寫死 speaker**  
   speaker profile、persona mapping、發音覆寫都放在 `backend/tts_service/config/`，程式只負責載入與驗證。

2. **speaker resolution 明確分層**  
   優先序固定為：
   `speaker_id` 顯式指定 > `persona_id` mapping > default speaker profile。

3. **發音覆寫先做 text normalization hook**  
   task11 先不要求 engine 原生 phoneme API；先在 engine 前做文字正規化，足以滿足「測試詞讀法修正」驗收。

4. **覆寫規則分三層**  
   exact lexicon、product-name、number normalization 分開定義，避免所有規則混在同一個表裡。

5. **profile 用 profile_id，不直接暴露 engine 細節**  
   對上層使用 `profile_id` / `persona_id`，由 profile 內部去描述實際 `speaker_ref`、語速、pitch、style、fallback profile。

6. **先做同步載入，不做 hot reload**  
   啟動時讀 config 檔即可。task11 不處理檔案變更即時重載，先把配置邏輯做穩。

---

## 實作步驟

| 步驟 | 內容 | 產出檔案 |
|------|------|---------|
| 1. 建立 config 結構 | 新增 speaker profiles、persona mapping、pronunciation overrides 設定檔 | `backend/tts_service/config/*.yaml` |
| 2. config schema 與 loader | 定義設定檔 schema、載入與驗證流程 | `backend/tts_service/app/config_loader.py` |
| 3. speaker resolver | 實作 `speaker_id` / `persona_id` / default 的解析邏輯 | `backend/tts_service/app/speaker_resolver.py` |
| 4. pronunciation normalizer | 實作詞典覆寫、產品名覆寫、數字規則 hook | `backend/tts_service/app/pronunciation.py` |
| 5. 更新 request contract | synthesize request 新增 `persona_id`，保留 `speaker_id` 顯式覆蓋能力 | `backend/tts_service/app/schemas.py` |
| 6. 接入 service path | 在 `TTSService` 中串起 resolver 與 normalizer，再送 engine | `backend/tts_service/app/service.py` |
| 7. 健康檢查擴充 | `/healthz` 回 profile count、default profile、override set version 等 metadata | `backend/tts_service/app/main.py` |
| 8. 測試與樣本 | 補 resolver / normalizer / service 測試與 test fixtures | `backend/tts_service/tests/*` |

---

## 詳細設計

### 1. 設定檔結構

建議目錄：

```text
backend/tts_service/config/
├── speaker_profiles.yaml
├── persona_speaker_map.yaml
└── pronunciation_overrides.yaml
```

`speaker_profiles.yaml`

```yaml
default_profile: brand_zh_tw_female_a

profiles:
  brand_zh_tw_female_a:
    speaker_ref: speaker_001
    locale: zh-TW
    speed: 1.0
    pitch: 0.0
    style: warm
    fallback_profile: brand_zh_tw_female_b

  brand_zh_tw_female_b:
    speaker_ref: speaker_002
    locale: zh-TW
    speed: 1.0
    pitch: 0.0
    style: calm
```

`persona_speaker_map.yaml`

```yaml
personas:
  default: brand_zh_tw_female_a
  concierge: brand_zh_tw_female_a
  support: brand_zh_tw_female_b
```

`pronunciation_overrides.yaml`

```yaml
lexicon:
  OpenVman: "Open V Man"
  LanceDB: "蘭斯資料庫"

products:
  VMAN-X1: "V Man X 一"
  SKU-2049: "S K U 二零四九"

numbers:
  currency_unit: "元"
  use_zh_tw_digits: true
  normalize_phone: true
```

### 2. Request contract 調整

`POST /v1/synthesize`

Request:

```json
{
  "text": "VMAN-X1 售價 1299 元。",
  "persona_id": "concierge",
  "speaker_id": "",
  "locale": "zh-TW",
  "audio_format": "wav",
  "sample_rate": 24000,
  "request_id": "req-local-002"
}
```

規則：
- `speaker_id` 可選，但若有值，直接指定 profile
- `persona_id` 可選，若未指定 `speaker_id` 才啟用 mapping
- 兩者都沒有時，使用 `default_profile`

### 3. Speaker resolver

介面概念：

```python
def resolve_speaker_profile(
    *,
    speaker_id: str | None,
    persona_id: str | None,
    profile_config: SpeakerProfileConfig,
    persona_map: PersonaSpeakerMap,
) -> SpeakerProfile:
    ...
```

規則：
- `speaker_id` 不存在於 profiles -> 400 validation error
- `persona_id` 不存在於 map -> fallback 到 default profile
- map 指向不存在 profile -> 啟動時即視為 config error，不允許服務啟動

### 4. Pronunciation normalizer

介面概念：

```python
def normalize_pronunciation(
    text: str,
    overrides: PronunciationOverrides,
) -> str:
    ...
```

執行順序：
1. product-name exact overrides
2. lexicon exact overrides
3. number normalization

原因：
- 產品名通常包含數字與英數混合，應先處理
- 一般詞條覆寫其次
- 最後才做通用數字規則，避免覆蓋掉前面已處理好的品牌詞

### 5. number / product-name 規則

首版只做 deterministic 規則，不碰完整 NLP：

- `1299 元` -> `一千二百九十九元`
- `02-2712-3456` -> `零二，二七一二，三四五六`
- `VMAN-X1` -> 依 products override 明確替換
- `SKU-2049` -> 依 products override 明確替換

不做的事：
- 不做全文語意斷詞
- 不做自動多音字 disambiguation
- 不做 sentence-level prosody tuning

### 6. health metadata

`GET /healthz` 可擴充為：

```json
{
  "status": "ok",
  "service": "indextts2-tts",
  "engine": "indextts2",
  "model_loaded": true,
  "device": "cuda",
  "default_profile": "brand_zh_tw_female_a",
  "profile_count": 2,
  "persona_mapping_count": 3,
  "lexicon_override_count": 2
}
```

---

## 測試案例

| 測試 | 驗證內容 |
|------|---------|
| `test_load_speaker_profiles_from_yaml` | speaker profiles 從設定檔載入，不是硬編碼 |
| `test_resolve_persona_to_target_profile` | `persona_id=concierge` 解析到對應 profile |
| `test_explicit_speaker_id_overrides_persona_mapping` | `speaker_id` 優先於 `persona_id` |
| `test_unknown_persona_falls_back_to_default_profile` | persona 不存在時回 default profile |
| `test_invalid_profile_reference_fails_at_startup` | mapping 指向不存在 profile 時服務啟動失敗 |
| `test_exact_lexicon_override_applies` | 指定詞條讀法會被改寫 |
| `test_product_name_override_applies` | 產品名覆寫能修正測試詞讀法 |
| `test_number_normalization_applies_to_currency` | 阿拉伯數字可轉成台灣中文讀法 |
| `test_number_normalization_applies_to_phone_number` | 電話格式依規則正規化 |
| `test_service_passes_normalized_text_and_profile_to_engine` | service 會把 normalized text 和 resolved profile 傳給 engine |
| `test_healthz_reports_profile_and_override_counts` | `/healthz` 能反映 profile 與 override 載入數量 |

---

## 驗收方法

### 自動驗收

| 檢查項目 | 指令 | 驗證內容 |
|---------|------|---------|
| config/resolver 測試 | `python3 -m pytest backend/tts_service/tests/test_speaker_resolver.py -v` | profile 與 persona mapping |
| pronunciation 測試 | `python3 -m pytest backend/tts_service/tests/test_pronunciation.py -v` | 詞典、產品名、數字覆寫 |
| service 測試 | `python3 -m pytest backend/tts_service/tests/test_service_engine.py -v` | normalizer + resolver + engine path |
| health 測試 | `python3 -m pytest backend/tts_service/tests/test_healthz.py -v` | health metadata |
| 全 TTS 測試 | `python3 -m pytest backend/tts_service/tests/ -v` | 不打壞 task10 service |

### 手動驗收

| 檢查項目 | 指令 | 驗證內容 |
|---------|------|---------|
| persona 對 speaker | `curl -s -X POST http://127.0.0.1:9000/v1/synthesize ...` | 不指定 `speaker_id`、只指定 `persona_id` 時仍成功合成 |
| 覆寫測試詞 | `python3 backend/tts_service/scripts/smoke_request.py --text "VMAN-X1 售價 1299 元"` | 回傳音訊對應目標讀法 |
| health metadata | `curl -s http://127.0.0.1:9000/healthz` | 可看到 profile / mapping / override counts |

### 驗收標準對照

| 驗收標準 | 如何確認 |
|---------|---------|
| persona 可對應到 speaker profile | resolver 測試與手動 synthesize 指定 `persona_id` 成功 |
| 詞典覆寫能修正測試詞讀法 | pronunciation 測試樣本與 smoke 詞句通過 |
| speaker profile 不是寫死在程式裡 | profile 由 YAML 設定檔載入，health 與 loader 測試可驗證 |

---

## 檔案清單

| 檔案 | 動作 | 用途 |
|------|------|------|
| `backend/tts_service/config/speaker_profiles.yaml` | 新增 | speaker profile 設定 |
| `backend/tts_service/config/persona_speaker_map.yaml` | 新增 | persona -> speaker profile mapping |
| `backend/tts_service/config/pronunciation_overrides.yaml` | 新增 | 詞典、產品名、數字覆寫規則 |
| `backend/tts_service/app/config_loader.py` | 新增 | config 載入與驗證 |
| `backend/tts_service/app/speaker_resolver.py` | 新增 | speaker / persona 解析 |
| `backend/tts_service/app/pronunciation.py` | 新增 | 發音正規化 hook |
| `backend/tts_service/app/schemas.py` | 修改 | synthesize request 新增 `persona_id` 等欄位 |
| `backend/tts_service/app/service.py` | 修改 | 串接 resolver + normalizer + engine |
| `backend/tts_service/app/main.py` | 修改 | health metadata 與啟動時 config 載入 |
| `backend/tts_service/tests/test_speaker_resolver.py` | 新增 | speaker/profile 解析測試 |
| `backend/tts_service/tests/test_pronunciation.py` | 新增 | 發音覆寫測試 |
| `backend/tts_service/tests/test_service_engine.py` | 修改 | service path 整合測試 |
| `backend/tts_service/tests/test_healthz.py` | 修改 | health metadata 測試 |
| `docs/plans/TASK-11-zh-tw-speaker-profile-and-pronunciation-override-support.md` | 新增 | 計畫書（本文件） |
