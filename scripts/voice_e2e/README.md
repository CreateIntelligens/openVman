# 語音對話模擬（voice_e2e）

不用對著前台講話，也能測一輪完整的語音對話。腳本送出聲音，走的是前台用的同一組公開端點：

| 步驟 | 端點 | 跟前台一樣的地方 |
|------|------|------|
| 產生語音 | `POST /v1/audio/speech` | 用系統自己的 TTS 念題目；也可以讀真人錄音 |
| 串流辨識 | `WS /api/v1/asr/stream` | 16 kHz PCM16，每 0.1 秒送 3200 bytes，講完送 `{"type":"end"}`；經過 Jev 定稿判斷 |
| 批次辨識 | `POST /api/v1/asr/transcribe` | 上傳 16 kHz wav，帶 `project_id`、`language_routes`；引擎照帳號設定，會帶專案詞表 |
| 回答 | `POST /api/v1/chat` | `mode` 預設 `fast`；台語（`language: "nan"`）會帶 `speech_language` |
| 念回答（選用） | `POST /api/v1/tts/stream` | 量第一段聲音多久出來 |

每一輪記錄這些項目：

- 辨識錯字率，比對時忽略標點、全形半形和大小寫。
- 專有名詞有沒有聽對。
- 回答有沒有提到預期的字。
- 各段耗時。串流辨識的耗時，是從講完最後一個字算到第一段定稿。

## 用法

在 repo 根目錄、主機上執行。需要 `httpx`、`websockets`、`ffmpeg`，也要能 `docker compose exec backend`。

```bash
# 鶴記全部題目 × 題庫裡的 4 種聲音，串流與批次都跑，辨識後問 Brain
python3 scripts/voice_e2e/run.py scripts/voice_e2e/cases/heji.json --user ai360

# 只跑兩題、一種聲音，再加上 TTS
python3 scripts/voice_e2e/run.py scripts/voice_e2e/cases/heji.json --user ai360 \
  --only diva eubl --voices edge-tts:zh-TW-HsiaoChenNeural --steps chat,tts

# 只測辨識、不問 Brain；混入雜訊
python3 scripts/voice_e2e/run.py scripts/voice_e2e/cases/heji.json --user ai360 --steps "" --noise 0.02
```

| 參數 | 說明 |
|------|------|
| `--user` | 用這個帳號跑。腳本在 backend 容器裡替它簽一個 60 分鐘的 session token，不需要密碼 |
| `--token` | 直接給 Bearer token（例如打遠端環境時） |
| `--base-url` | 預設 `https://localhost:8787`（nginx）。打 localhost 時不驗憑證；打正式網域請加 `--verify-tls` |
| `--asr` | `stream`、`batch`，或兩個都跑；預設用題庫的 `asr`，沒寫就兩個都跑 |
| `--steps` | 辨識完之後要做的步驟：`chat`（預設）、`chat,tts`；空字串代表只測辨識 |
| `--voices` | `provider:voice`，逗號分隔；預設用題庫的 `voices` |
| `--routes` | 語言分流，例如 `zh,en`；預設用後台設定 |
| `--noise` | 混入粉紅雜訊的振幅（`0.01` 輕、`0.05` 很吵） |
| `--only` | 只跑 id 符合這些 regex 的題目 |
| `--keep-sessions` | 保留這次建立的對話；預設跑完會刪掉 |

結果會印出「聲音 × 辨識路徑」的彙總表，逐題細節寫到 `scripts/voice_e2e/results/<題庫>-<時間>.json`。細節包含最後一段暫定字幕、每一段定稿、辨識引擎和回答全文。合成語音會快取在 `.cache/`。兩個目錄都已經 gitignore。

## 題庫格式

`cases/*.json`：

```json
{
 "project_id": "proj-0cc5c610b4",
 "voices": ["edge-tts:zh-TW-HsiaoChenNeural", "voxcpm:voxcpm2-cosy-young-male-01"],
 "cases": [
  {"id": "diva-agitator", "text": "請問 DIVA 有攪拌器嗎？", "terms": ["DIVA"], "reply_any": ["DIVA"]},
  {"id": "real-01", "text": "沉水泵最深可以放多深", "audio": "recordings/real-01.webm", "terms": ["沉水泵"]}
 ]
}
```

- `terms`：辨識結果裡要出現的詞，寫成 `A|B` 代表兩種寫法都算對。
- `reply_any`：回答裡提到其中任何一個字就算命中。
- `audio`：有給就用這個錄音，路徑相對於 repo 根目錄，ffmpeg 讀得了的格式都可以；這時 `text` 是正確答案。沒給就用 `voices` 裡的每個聲音各念一次。
- `speech_language`：批次辨識應該判成的語言。`nan` 表示應判成台語，`zh` 表示不該被判成台語；彙總表的「語言判斷」欄統計判對的題數。串流辨識不判台語，所以不計入。「判斷逾時」「判斷ms」來自回應的 `language_check`（台語分流時才有），不必去數 backend log。
- 題庫最外層可以寫 `asr`，例如 `["batch"]`，當作預設的辨識路徑。

現有題庫：

| 題庫 | 內容 |
|------|------|
| `heji.json` | 鶴記型錄 10 題（型號、泵浦專有名詞、閒聊），合成語音 4 種聲音，串流與批次都跑 |
| `taigi-drama.json` | 台語連續劇對白真人錄音 75 句（`/srv/818data`，只有這台機器有），`text` 是華語字幕（意譯，所以錯字率偏高），只跑批次。用來看 Breeze 轉寫和台語判斷；只測辨識時加 `--steps ""`。同時跑多句會讓台語判斷超過 2.5 秒逾時，要量判斷準度時加 `--concurrency 1` |

## 副作用與限制

- 會產生：
  - 用量記錄（Brain `usage.db`），算在 `--user` 那個帳號。
  - Jev 定稿判斷的記錄，寫進 `backend/logs/asr_final_judge.jsonl`。這個檔目前沒有欄位能區分測試和真人，用這份檔驗證 Jev 時要排除腳本執行期間的時間。
- 不會產生：turn timing 記錄（腳本不打 `/api/v1/metrics/turn`）。建立的對話 session（`voice-e2e-<時間>-*`）跑完會刪掉。
- 簽 token 需要能進 backend 容器，而能進容器本來就有完整權限。這個方式跳過登入稽核，只給維運用。
- 合成語音比真人清楚，錯字率只能拿來比較版本、聲音或引擎之間的差異，不代表真人的實際表現。要評估真人效果，請把錄音放進題庫的 `audio`。
- 同一條串流連線裡，Gemini 可能把一句話切成兩段定稿。前台會把它們當成兩輪送出，這裡則合起來問 Brain；逐題結果的 `finals` 看得出來有沒有被切開。
