# TASK-11: zh-TW Speaker Profile and Pronunciation Override Support

> Issue: #21 — zh-TW speaker profile and pronunciation override support
> Epic: #4
> Branch: `feature/backend`
> Status: **Draft**

---

## 開發需求

在 IndexTTS2 推理服務中加入可配置的 speaker profile、persona 對應與台灣中文發音覆寫機制。

| 需求 | 說明 |
|------|------|
| speaker profile config | speaker profile 由外部設定檔管理，不寫死在程式裡 |
| persona-to-speaker mapping | 請求帶 `persona_id` 時可解析到對應 speaker profile |
| lexicon override hooks | 支援指定詞條發音覆寫，修正常見 zh-TW 詞讀法 |
| number / product-name rules | 支援數字與品牌/產品名的正規化或覆寫規則 |

---

## 驗收標準對照

| 驗收標準（Issue #21） | 實作方式 |
|----------------------|---------|
| persona can resolve to target speaker profile | `SpeakerResolver` 依 persona_id → profile mapping 解析 |
| pronunciation overrides work for test terms | `PronunciationNormalizer` 在送進 engine 前做文字正規化 |
| speaker profiles are configurable, not hardcoded | 由 YAML 設定檔載入，程式只負責載入與驗證 |

---

## 前置依賴

- TASK-10 的 IndexTTS2 推理服務骨架先存在
- 本 task 的 config loader、resolver、normalizer 可先獨立開發與測試

---

## 設計

### Speaker resolution 優先序

```text
speaker_id 顯式指定 > persona_id mapping > default speaker profile
```

### 發音覆寫執行順序

```text
1. product-name exact overrides（產品名含英數混合，先處理）
2. lexicon exact overrides（一般詞條覆寫）
3. number normalization（通用數字規則，最後做）
```

### 設定檔結構

```text
config/
├── speaker_profiles.yaml
├── persona_speaker_map.yaml
└── pronunciation_overrides.yaml
```

---

## 測試案例

| 測試 | 驗證內容 |
|------|---------|
| `test_load_speaker_profiles_from_yaml` | profiles 從設定檔載入 |
| `test_resolve_persona_to_target_profile` | persona_id 解析到對應 profile |
| `test_explicit_speaker_id_overrides_persona` | speaker_id 優先於 persona_id |
| `test_unknown_persona_falls_back_to_default` | persona 不存在時回 default |
| `test_exact_lexicon_override_applies` | 詞條讀法被改寫 |
| `test_product_name_override_applies` | 產品名覆寫生效 |
| `test_number_normalization_applies` | 數字轉中文讀法 |

---

## 檔案清單

本 task 完成時預計產出：

| 檔案 | 用途 |
|------|------|
| `backend/indextts2/config/speaker_profiles.yaml` | speaker profile 設定 |
| `backend/indextts2/config/persona_speaker_map.yaml` | persona → speaker mapping |
| `backend/indextts2/config/pronunciation_overrides.yaml` | 詞典、產品名、數字覆寫 |
| `backend/indextts2/app/config_loader.py` | config 載入與驗證 |
| `backend/indextts2/app/speaker_resolver.py` | speaker / persona 解析 |
| `backend/indextts2/app/pronunciation.py` | 發音正規化 hook |
| `backend/indextts2/app/schemas.py` | synthesize request 新增 persona_id |
| `backend/indextts2/tests/` | 測試 |
