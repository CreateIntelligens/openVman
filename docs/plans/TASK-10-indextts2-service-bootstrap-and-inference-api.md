# TASK-10: IndexTTS2 Service Bootstrap and Inference API

> Issue: #20 — IndexTTS2 service bootstrap and inference API
> Epic: #4
> Branch: `feature/backend`
> Status: **Planned**

---

## 開發需求

建立一個獨立於 `brain/` 的後端 TTS 推理服務，能在開發環境啟動、成功處理單次文字轉音訊請求，並留下初步延遲基準數據。

| 需求 | 說明 |
|------|------|
| 獨立服務啟動 | 在 `backend/tts_service/` 建立獨立服務根目錄、依賴、Dockerfile、compose 與 `.env` |
| 健康檢查 | 提供 `/healthz`，可確認服務存活、模型是否載入、目前 device 與預設 speaker |
| 推理 API 合約 | 提供 `POST /v1/synthesize`，輸入文字與 speaker，輸出音訊 bytes |
| 文字轉音訊路徑 | 接上 IndexTTS2-style runtime，從 text 產出 `audio/wav` |
| 基準數據 | 至少記錄 1 次 cold start 與數次 warm request latency |
| 邊界清楚 | 本 task 不碰 `brain/api/*`，也不處理 viseme / WebSocket chunking |

---

## 現況分析

### 已有資料

| 來源 | 內容 |
|------|------|
| [01_BACKEND_SPEC.md](/home/human/openVman/01_BACKEND_SPEC.md#L66) | 已明確指定正式方案應以自建 `IndexTTS2`-style zh-TW TTS 為核心 |
| [01_BACKEND_SPEC.md](/home/human/openVman/01_BACKEND_SPEC.md#L169) | 已有 TTS 相關環境變數方向，如 provider、node、speaker、output format |
| [readme.md](/home/human/openVman/readme.md#L199) | 系統總覽已把後端 TTS 視為獨立後端能力，不屬於 brain |

### 缺口

| 缺口 | 說明 |
|------|------|
| 沒有獨立 TTS 服務目錄 | repo 目前只有 `brain/`，沒有 `backend/tts_service/` 或等價獨立服務 |
| 沒有推理 HTTP contract | 還沒有 `/healthz` / `/v1/synthesize` 的實作與測試 |
| 沒有 dev bootstrap | 沒有專屬 Dockerfile、compose、環境檔、啟動方式 |
| 沒有延遲基準紀錄 | 目前沒有 cold/warm latency baseline 檔案與量測腳本 |
| 沒有 smoke 驗收腳本 | 還沒有單次 request -> 音訊輸出檔案的自動驗收入口 |

---

## 開發方法

### 架構

```text
backend/tts_service
    ├─ FastAPI app
    │   ├─ GET /healthz
    │   └─ POST /v1/synthesize
    ├─ TTSService
    │   ├─ request validation
    │   ├─ latency timing
    │   └─ response metadata assembly
    ├─ IndexTTS2Engine
    │   ├─ model bootstrap
    │   ├─ warmup
    │   └─ synthesize(text, speaker_id, sample_rate)
    ├─ scripts/smoke_request.py
    └─ scripts/benchmark_latency.py
```

### 設計決策

1. **獨立目錄、獨立環境**  
   服務放在 `backend/tts_service/`，有自己的 `requirements.txt`、`.env`、`Dockerfile`、`docker-compose.yml`，不共用 `brain` 的 runtime。

2. **先做 binary audio response**  
   `POST /v1/synthesize` 直接回 `audio/wav` bytes，metadata 放 headers。這比 JSON base64 更適合作為內部服務合約。

3. **先不做 viseme**  
   task10 只處理音訊產出與 API 啟動，viseme extraction 放後續 task，避免一次把 backend orchestration 全綁進來。

4. **Engine adapter 隔離模型細節**  
   API 層只知道 `TTSService`，實際模型載入和 inference 細節收斂在 `IndexTTS2Engine`，後續要換 runtime 或 mock 比較容易。

5. **基準數據落檔**  
   latency 不只印在 console，要輸出成 `benchmarks/dev-baseline.json`，後續才能比較優化前後差異。

---

## 實作步驟

| 步驟 | 內容 | 產出檔案 |
|------|------|---------|
| 1. 建立服務骨架 | 建 `backend/tts_service/` 根目錄、app/tests/scripts/benchmarks 結構與依賴檔 | `backend/tts_service/*` |
| 2. 健康檢查端點 | 實作 `/healthz` 與模型載入狀態回報 | `backend/tts_service/app/main.py` |
| 3. 推理請求 schema | 定義 synthesize request/response metadata contract | `backend/tts_service/app/schemas.py` |
| 4. 推理服務層 | 建 `TTSService`，處理 request 驗證、latency timing、headers 組裝 | `backend/tts_service/app/service.py` |
| 5. 模型 adapter | 建 `IndexTTS2Engine`，封裝模型 bootstrap、warmup、synthesize | `backend/tts_service/app/engine.py` |
| 6. Dev bootstrap | 補 Dockerfile、compose、`.env.example`，讓本機可獨立啟動 | `backend/tts_service/Dockerfile` `backend/tts_service/docker-compose.yml` |
| 7. 驗收腳本 | 補 smoke request 與 benchmark latency 腳本 | `backend/tts_service/scripts/*.py` |
| 8. 測試與文件 | 補 API/service 測試與服務 runbook | `backend/tts_service/tests/*` `backend/tts_service/README.md` |

---

## 詳細設計

### 1. 目錄與環境隔離

目標結構：

```text
backend/
└── tts_service/
    ├── app/
    ├── tests/
    ├── scripts/
    ├── benchmarks/
    ├── .env.example
    ├── Dockerfile
    ├── docker-compose.yml
    ├── requirements.txt
    └── README.md
```

規則：
- 不 import `brain/*`
- 不共用 `brain/api/requirements.txt`
- 不掛 `brain/docker-compose.yml`
- 服務啟動、smoke test、benchmark 要能只靠 `backend/tts_service/` 完成

### 2. API 合約

`GET /healthz`

```json
{
  "status": "ok",
  "service": "indextts2-tts",
  "engine": "indextts2",
  "model_loaded": true,
  "device": "cuda",
  "speaker_default": "brand_zh_tw_female_a"
}
```

`POST /v1/synthesize`

Request:

```json
{
  "text": "你好，歡迎光臨。",
  "speaker_id": "brand_zh_tw_female_a",
  "locale": "zh-TW",
  "audio_format": "wav",
  "sample_rate": 24000,
  "request_id": "req-local-001"
}
```

Response:
- `200 OK`
- `Content-Type: audio/wav`
- body = raw audio bytes
- headers:
  - `X-Request-Id`
  - `X-TTS-Model`
  - `X-TTS-Latency-Ms`
  - `X-Audio-Duration-Ms`
  - `X-Sample-Rate`

### 3. 環境變數

```env
INDEXTTS2_MODEL_PATH=/models/indextts2
INDEXTTS2_DEVICE=cuda
INDEXTTS2_DEFAULT_SPEAKER=brand_zh_tw_female_a
INDEXTTS2_SAMPLE_RATE=24000
INDEXTTS2_MAX_TEXT_LENGTH=300
INDEXTTS2_WARMUP_TEXT=你好，歡迎使用語音服務。
TTS_SERVICE_PORT=9000
TTS_SERVICE_LOG_LEVEL=info
```

補充：
- dev 沒 GPU 時可允許 `INDEXTTS2_DEVICE=cpu`
- 但 CPU 測到的 latency 只能當 bring-up baseline，不能當正式 SLA 依據

### 4. Latency baseline

至少輸出：

```json
{
  "service": "indextts2-tts",
  "engine": "indextts2",
  "device": "cuda",
  "sample_text": "你好，歡迎光臨。",
  "cold_start_ms": 1380,
  "warm_runs": [
    {"index": 1, "latency_ms": 420},
    {"index": 2, "latency_ms": 401}
  ],
  "warm_p50_ms": 410,
  "warm_p95_ms": 420,
  "recorded_at": "2026-03-15T12:00:00Z"
}
```

落檔位置：
- `backend/tts_service/benchmarks/dev-baseline.json`

---

## 測試案例

| 測試 | 驗證內容 |
|------|---------|
| `test_healthz_reports_service_metadata` | `/healthz` 回 200，且包含 service / engine / model_loaded |
| `test_synthesize_returns_wav_bytes` | `POST /v1/synthesize` 回 `audio/wav` bytes 與 latency headers |
| `test_invalid_text_rejected` | 空字串或過長 text 被 schema/validation 擋下 |
| `test_service_calls_engine_and_returns_audio_bytes` | `TTSService` 會正確呼叫 engine 並回傳 metadata |
| `test_startup_warmup_runs_once` | 服務啟動時 warmup 被執行一次，不在每次 request 重載模型 |
| `test_smoke_script_mentions_v1_synthesize` | smoke script 真的打服務正式端點 |
| `test_benchmark_output_shape` | latency baseline JSON 具有 cold/warm/p50/p95 欄位 |

---

## 驗收方法

### 自動驗收

| 檢查項目 | 指令 | 驗證內容 |
|---------|------|---------|
| health 測試 | `python3 -m pytest backend/tts_service/tests/test_healthz.py -v` | 健康檢查與啟動 metadata |
| synthesize API 測試 | `python3 -m pytest backend/tts_service/tests/test_synthesize_api.py -v` | 推理端點 contract |
| service/engine 測試 | `python3 -m pytest backend/tts_service/tests/test_service_engine.py -v` | engine adapter 與 service path |
| script 測試 | `python3 -m pytest backend/tts_service/tests/test_smoke_script.py -v` | smoke 腳本存在且對端點正確 |
| benchmark 測試 | `python3 -m pytest backend/tts_service/tests/test_benchmark_script.py -v` | baseline JSON 格式 |
| 全 TTS 測試 | `python3 -m pytest backend/tts_service/tests/ -v` | 不打壞獨立服務 |

### 手動驗收

| 檢查項目 | 指令 | 驗證內容 |
|---------|------|---------|
| 啟動服務 | `docker compose -f backend/tts_service/docker-compose.yml up -d --build` | dev 環境可啟動 |
| 單次音訊請求 | `python3 backend/tts_service/scripts/smoke_request.py` | 產出 `/tmp/indextts2_smoke.wav` |
| 基準量測 | `python3 backend/tts_service/scripts/benchmark_latency.py` | 產出 `benchmarks/dev-baseline.json` |

### 驗收標準對照

| 驗收標準 | 如何確認 |
|---------|---------|
| 開發環境可啟動 | compose 啟動成功，`GET /healthz` 回 `200` |
| 單次請求可成功回音訊 | smoke script 寫出可播放的 `.wav` 檔 |
| 有初步延遲基準數據 | `dev-baseline.json` 含 cold start 與 warm latency 數值 |

---

## 檔案清單

| 檔案 | 動作 | 用途 |
|------|------|------|
| `backend/tts_service/app/main.py` | 新增 | FastAPI 入口與 `/healthz`、`/v1/synthesize` |
| `backend/tts_service/app/config.py` | 新增 | TTS 服務環境變數設定 |
| `backend/tts_service/app/schemas.py` | 新增 | synthesize request schema |
| `backend/tts_service/app/service.py` | 新增 | service layer，封裝 metadata 與 latency timing |
| `backend/tts_service/app/engine.py` | 新增 | IndexTTS2 runtime adapter |
| `backend/tts_service/tests/test_healthz.py` | 新增 | health endpoint 測試 |
| `backend/tts_service/tests/test_synthesize_api.py` | 新增 | inference API contract 測試 |
| `backend/tts_service/tests/test_service_engine.py` | 新增 | service / engine 單元測試 |
| `backend/tts_service/tests/test_smoke_script.py` | 新增 | smoke script 測試 |
| `backend/tts_service/tests/test_benchmark_script.py` | 新增 | benchmark script 輸出測試 |
| `backend/tts_service/scripts/smoke_request.py` | 新增 | 單次請求驗收腳本 |
| `backend/tts_service/scripts/benchmark_latency.py` | 新增 | latency baseline 量測腳本 |
| `backend/tts_service/Dockerfile` | 新增 | 服務容器化 |
| `backend/tts_service/docker-compose.yml` | 新增 | dev 啟動入口 |
| `backend/tts_service/requirements.txt` | 新增 | 獨立 Python 依賴 |
| `backend/tts_service/.env.example` | 新增 | 環境變數範本 |
| `backend/tts_service/README.md` | 新增 | 啟動與驗收 runbook |
| `docs/plans/TASK-10-indextts2-service-bootstrap-and-inference-api.md` | 新增 | 計畫書（本文件） |
