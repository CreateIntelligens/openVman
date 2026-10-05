# R2T2 串流辨識接上前台

狀態：Done（2026-10-05 使用者授權結案）。已於 `afb9d6c` 提交並部署，正式引擎 `r2t2-live`（.37）；.35 另列為 `r2t2-dev`／`r2t2-dev-live`（`dd20940`）。下方「現況（交接時）」是 2026-10-01 的交接紀錄，不是現況。

## 目標

前台的串流辨識（邊講邊出字）多一個引擎選項：Confucius4-R2T2，跟現有的 Gemini Live 並存。帳號選了它，就走 R2T2 串流；台語分流時照舊改用 Breeze 批次。

## 為什麼做

鶴記型錄 10 題，合成語音，各 20 句；R2T2 已轉成繁體再算錯字率。

| 串流 | 錯字率 | 專有名詞聽對 | 講完到定稿 p50 |
|---|---|---|---|
| Gemini Live（現行） | 17.6% | 3/18 | 2.05 秒 |
| R2T2 .37，帶專案詞表 | 6.9% | 13/18 | 1.10 秒 |
| R2T2 .37，同時 3 路 | 6.9% | 13/18 | 1.59 秒，沒有漏掉斷句 |

- 數據和腳本在 `scripts/experiments/r2t2/`：`run.py` 測批次，`stream.py` 測串流。
- 延遲從音檔裡最後一個有聲音的取樣算起。

## 現況（交接時）

- **工作區有 Vman0914 未 commit 的改動。** 不要改、不要混進你的 commit，也不要 push。使用者交代 push 要等他確認。這些改動包括：
  - R2T2 **批次**整合：`backend/app/gateway/ingestion_audio.py` 的 `_transcribe_r2t2`、`config.py` 的 `asr_r2t2_url`、`settings_repository.py` 的 `SERVER_ASR_PROVIDERS` 加 `r2t2`、`routes/admin.py` 的引擎名稱、`frontend/shared/speech/asr/engines.ts`、`backend/tests/gateway/test_asr_r2t2.py`，以及兩個前端測試的引擎清單。
  - 知識圖譜略過停用文件的修正：`brain/api/tools/builtin/knowledge_tools.py`、`brain/api/tests/knowledge/test_graph_neighbor_retrieval.py`、`docs/specs/03_BRAIN_SPEC.md`，以及 `CHANGELOG.md` 的一條。
  - `scripts/experiments/r2t2/`、`scripts/experiments/__init__.py`。
  - 先跟使用者確認，是要等這些 commit 之後再開工，還是在另一個 worktree 做（`.worktree/<name>`）。
- R2T2 有兩套部署：
  - **用 .37**：`10.9.0.37:8803`，GB10，transformers。6 項修正已經上線，但改動還在 gb10 本機，沒有 commit。
  - .35（`10.9.0.35:8040`，vLLM，對外是 asr.5gao.ai）同時請求會卡死，接成獨立引擎 `r2t2-dev`／`r2t2-dev-live`（`ASR_R2T2_DEV_*`）：帳號選了才用，失敗不換台、不當其他引擎的備援，批次只等 20 秒。
- 正式 `.env` 還沒有任何 R2T2 設定。

## R2T2 串流協定（.37，以實測為準）

- 位址：`ws://10.9.0.37:8803/asr_stream_api_v1`。
- 連上後先送 JSON 握手：
  ```json
  {"requestId": "<uuid>", "language": "Chinese", "use_vad": true,
   "secret_key": "<ASR_R2T2_SECRET_KEY>", "system_prompt": "<專案詞表>"}
  ```
  - 金鑰目前是 `test0102`，放 `.env`，不要寫進程式碼。
  - `system_prompt` 是熱詞，選填。
  - `language` 用 `Chinese` 或 `zhen`（兩個都會以中文解碼，夾雜的英文照實輸出）。不要用 `auto`：自動判斷時，帶口音的華語曾被轉成葡萄牙文。
  - 伺服器會回一則 connected 訊息，裡面有實際使用的 language。
- 之後每 0.16 秒送一段 binary：16 kHz、16-bit、單聲道 PCM，每段 **5120 bytes**。
- 結束時送文字 `YOUDAO_ONETIME_ASR_STREAM_EOS`。
- 伺服器的回應長這樣：
  ```json
  {"status": "success", "requestId": "...",
   "msg": {"text": "<這次新增的字>", "reset": false, "asr_cost_ms": 32.5}}
  ```
  - `msg.text` 是**增量**，靜音時是空字串，要自己累加。
  - `reset: true` 表示一句講完（停頓約 0.7 秒，VAD 判斷）。這則訊息另外帶 `final_text`，是整句重新辨識的結果，**以它為定稿**。串流的增量偶爾會在句首多一個「好」之類的雜字。
- 輸出是簡體，要用 `app.utils.chinese.convert_to_traditional` 轉成繁體。
- 健康檢查是 `/healthz`：`inference.waiting`、`busy_seconds`、`last_success_seconds_ago`、`active_streams`；推論卡住超過 60 秒時，`status` 會變成 `stalled`。

## 設計

前台和後端之間的串流協定不變：前台送 PCM binary，後端回 `{"type": "ready" | "interim" | "final" | "error"}`。所以主要工作在後端，前台只是小改。

### 後端：`backend/app/gateway/asr_stream.py`

- 端點維持 `/api/v1/asr/stream`，依帳號偏好選上游：
  - `gemini-live` 走現有流程。
  - 新引擎 `r2t2-live` 走 R2T2。
  - 批次的 `r2t2` 是另一個引擎，兩個要分開授權。
- `_allowed()` 現在寫死 `gemini-live`，要改成接受任何一個串流引擎，並回傳選中的是哪一個。
- R2T2 轉接要做的事：
  - **重新切段**：前台每 0.1 秒送 3200 bytes，要攢到 5120 bytes 再送給上游。
  - **收尾**：前台送 `{"type": "end"}` 時，把剩下不滿一段的音訊補靜音送出，再送 EOS 字串。
  - **對應訊息**：
    - 累加的增量文字 → `interim`，送「這句目前的完整文字」，跟 Gemini 的 interim 一樣是整句，不是增量。
    - `reset: true` → `final`，用 `final_text`，沒有的話用累加的文字；轉繁體後送出，再清空累加。
  - **詞表**：用 `app.asr_glossary.project_asr_prompt(account, project_id)` 取專案詞表，放進 `system_prompt`。
  - **錯誤**：上游連不上或握手失敗時，回 `{"type": "error", "code": "upstream_failed"}`，前台會自動退回批次辨識（現有行為）。
  - **用量記錄**：照 Gemini 那段 `record_usage_event` 記錄串流秒數。
  - 不需要 Jev 的定稿判斷（`_judge_final`）：R2T2 的 `final_text` 本身就是整句重新辨識的結果。
- 設定放在 `backend/app/config.py`，並在 `.env.example` 加註解：
  - `ASR_R2T2_STREAM_URL`，正式值是 `ws://10.9.0.37:8803/asr_stream_api_v1`。
  - `ASR_R2T2_SECRET_KEY`。
  - 沒設定網址時，這個引擎不能用，回 `not_configured`。
- 引擎註冊：
  - `settings_repository.py`：`r2t2-live` 跟 `gemini-live` 一樣，屬於「前台直接驅動、不進 `transcribe()` 備援」的那一類。
  - `routes/admin.py` 的 `_ASR_ENGINE_LABELS` 加 `r2t2-live`，後台才能授權給帳號。
  - 後端引擎清單和 `engines.ts` 的一致性，有 `backend/tests/auth/test_system_settings.py` 在檢查。

### 前台

- `frontend/shared/speech/asr/engines.ts`：
  - 加 `R2T2_STREAM_ASR = "r2t2-live"`。
  - 定義一組串流引擎，例如 `STREAM_ASR_ENGINES = [GEMINI_STREAM_ASR, R2T2_STREAM_ASR]`。
  - `ASR_ENGINE_NOTES` 加說明文字。
- `frontend/app/src/App.vue`（約 908 行）：`useStreamAsrEngine` 從「等於 `GEMINI_STREAM_ASR`」改成「屬於串流引擎」。台語分流時照舊不走串流。
- `frontend/shared/speech/asr/stream-recognizer.ts` 應該不用改。ready 逾時 10 秒，送 end 後最多等 5 秒拿定稿，R2T2 實測都在範圍內。
- 後台的引擎選單和授權頁，會跟著 `engines.ts` 和後端的名稱清單自動出現，確認一下即可。

## 驗收

1. 單元測試：
   - 後端仿照 `backend/tests/gateway/test_asr_stream.py`，用假的上游 WebSocket 測：
     - 重新切段：送出去的每段都是 5120 bytes。
     - 增量累加成 interim。
     - reset 用 `final_text` 當定稿，並轉成繁體。
     - end 之後會送 EOS。
     - 上游連不上時回 `upstream_failed`。
     - 沒授權時回 `not_allowed`。
   - 前台：選 `r2t2-live` 時走串流；開了台語分流時不走串流。
2. 指令：
   - `cd backend && python -m pytest tests/ -q`
   - `cd frontend/admin && pnpm test`
   - `cd frontend/app && pnpm test`
   - `python contracts/scripts/generate_protocol_contracts.py --check`
   - `git diff --check`
3. 部署後實測：用語音模擬工具 `scripts/voice_e2e/run.py`（說明見同目錄的 README.md）。
   - `--asr stream` 走的是帳號偏好的引擎，所以要用一個偏好設成 `r2t2-live` 的測試帳號。**不要改 ai360 這類真人帳號的偏好**，或者先徵求使用者同意。
   - 預期鶴記題庫（`cases/heji.json`）兩個 edge 聲音的串流結果：錯字率約 7%，專有名詞約 13/18，回答命中不低於 Gemini Live。
   - 同時 3 路（`--concurrency 3`）不能有漏掉斷句。

## 文件（依 AGENTS.md，同一個變更裡一起更新）

- `CHANGELOG.md` 的 `[Unreleased]`。
- `README.md` 的語音辨識段落。
- `docs/specs/01_BACKEND_SPEC.md` 的「串流 ASR」一節。
- `docs/specs/02_FRONTEND_SPEC.md` 前台引擎選擇的部分。

## 注意

- R2T2 會把台語寫成台語漢字，不會翻成華語。所以台語分流一定要維持走 Breeze 批次，不能讓 R2T2 串流處理台語。
- 正式環境的部署方式：push 之後由 CI 建置、watchtower 換容器。本機 build 的映像會被 watchtower 換回遠端版本，所以不能用本機 build 驗證正式環境。
- 改正式 `.env`、授權帳號，都要先問使用者。
