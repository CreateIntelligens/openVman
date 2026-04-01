# TASK-10: IndexTTS2 Service Bootstrap and Inference API

> [!CAUTION]
> **DEPRECATED**: This plan has been superceded by the [VibeVoice transition](../../openspec/changes/replace-indextts-with-vibevoice/proposal.md).
> The IndexTTS (vLLM) architecture has been removed in favor of a standalone VibeVoice service.

> Issue: #20 — IndexTTS2 service bootstrap and inference API
> Epic: #4
> Branch: `feature/backend`
> Status: **Draft**

---

## 開發需求

建立自建 IndexTTS2 推理服務，能在開發環境啟動、成功處理單次文字轉音訊請求，並留下初步延遲基準數據。

| 需求 | 說明 |
|------|------|
| 服務啟動 | 在開發環境可獨立啟動 IndexTTS2 推理服務 |
| 推理 API 合約 | 提供 `POST /tts`，輸入文字與 speaker，輸出音訊 bytes |
| 健康檢查 | 提供 `GET /healthz`，確認服務存活與模型狀態 |
| 基準數據 | 至少記錄 cold start 與 warm request latency |

---

## 驗收標準對照

| 驗收標準（Issue #20） | 實作方式 |
|----------------------|---------|
| service starts in dev environment | Docker 容器可獨立啟動 |
| one request returns audio successfully | `POST /tts` 回傳音訊 bytes |
| basic latency numbers are captured | benchmark 腳本產出 latency baseline JSON |

---

## 與 TTS Router 的整合

IndexTTS2 作為獨立推理服務（需要 GPU），TTS router 透過 `IndexTTSAdapter`（HTTP）呼叫：

```text
tts-router
    └─ Provider Fallback Chain
         ├─ 1. Index TTS ──HTTP──→ IndexTTS2 推理服務 (獨立容器)
         ├─ 2. GCP Cloud TTS
         ├─ 3. AWS Polly
         └─ 4. Edge-TTS (in-process)
```

TTS router 已有 `IndexTTSAdapter`，只需設定 `TTS_INDEX_URL` 指向推理服務即可接入。

---

## 設計決策

1. **獨立容器**
   IndexTTS2 需要 GPU 推理，與 TTS router 分開部署，透過 HTTP 通訊。

2. **API 合約與 TTS router 對齊**
   推理服務的 `/tts` 端點已被 `IndexTTSAdapter` 呼叫，request/response 格式需對齊。

3. **先做 binary audio response**
   直接回音訊 bytes，metadata 放 headers。

4. **Engine adapter 隔離模型細節**
   API 層只知道 `TTSService`，模型載入與 inference 細節收斂在 `IndexTTS2Engine`。

---

## 環境變數

```env
INDEXTTS2_MODEL_PATH=/models/indextts2
INDEXTTS2_DEVICE=cuda
INDEXTTS2_DEFAULT_SPEAKER=brand_zh_tw_female_a
INDEXTTS2_SAMPLE_RATE=24000
INDEXTTS2_MAX_TEXT_LENGTH=300
TTS_SERVICE_PORT=9000
```

---

## 測試案例

| 測試 | 驗證內容 |
|------|---------|
| `test_healthz_reports_service_metadata` | `/healthz` 回 200，含 service / engine / model_loaded |
| `test_synthesize_returns_audio_bytes` | `POST /tts` 回音訊 bytes 與 latency headers |
| `test_invalid_text_rejected` | 空字串或過長 text 被擋下 |
| `test_benchmark_output_shape` | latency baseline JSON 含 cold/warm/p50/p95 |

---

## 檔案清單

本 task 完成時預計產出：

| 檔案 | 用途 |
|------|------|
| `backend/indextts2/app/main.py` | FastAPI 入口與 `/healthz`、`/tts` |
| `backend/indextts2/app/config.py` | 環境變數設定 |
| `backend/indextts2/app/engine.py` | IndexTTS2 runtime adapter |
| `backend/indextts2/app/service.py` | service layer |
| `backend/indextts2/Dockerfile` | 服務容器化 |
| `backend/indextts2/requirements.txt` | Python 依賴 |
| `backend/indextts2/scripts/benchmark_latency.py` | latency baseline 量測 |
| `backend/indextts2/tests/` | 測試 |
