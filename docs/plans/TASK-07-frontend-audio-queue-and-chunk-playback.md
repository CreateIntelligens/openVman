# TASK-07: Frontend Audio Queue and Chunk Playback Controller

> Issue: [#17](https://github.com/CreateIntelligens/openVman/issues/17) — Frontend audio queue and chunk playback controller
> Epic: #3
> Branch: `feature/brain`
> Status: **Draft**

---

## 開發需求

實作前端 chunk-aware 音訊佇列控制器。`server_stream_chunk` 由 WebSocket 進入時，需依抵達順序排隊、解碼、緩衝，並依排程交給 `AudioContext` 做 gapless 播放，直到 `is_final=true` 收尾或 session 結束時排空。

| 需求 | 說明 |
|------|------|
| Chunk 佇列 | 將進入的 `server_stream_chunk` 依序入隊（FIFO），保持 server 抵達順序 |
| 解碼緩衝 | 將 `audio_base64` 解為 PCM Int16（16 kHz, mono, LE），失敗 chunk 必須隔離不影響後續 |
| 播放排序 | 排程到 `AudioContext` 時保留 chunk 抵達順序，避免亂序播放 |
| `is_final` 收尾 | 當 `is_final=true` 的 chunk 播畢時，觸發 `onUtteranceEnd`，並重置 queue 與 schedule |
| Session 結束排空 | session 關閉 / interrupt 時清空 pending queue 並 stop scheduled sources |
| 不漏 chunk | 一般串流負載下不丟包；abnormal payload 需記 log 但不停整條 queue |

---

## 開發方法

### 架構

```
WebSocket: server_stream_chunk
            │
            ▼
useAvatarChat.handleJsonMessage()
            │  (passes chunk payload)
            ▼
useAudioPlayer.enqueueChunk(chunkId, audio_base64, isFinal)
            │
            ▼
   ┌────────────────────┐
   │  pendingQueue[]    │   FIFO，保留抵達順序
   └────────────────────┘
            │
            ▼ (drain loop)
   decode → AudioBuffer → schedule(start = nextStartTime)
            │
            ▼
   nextStartTime += duration
            │
            ▼
   onended → if last && is_final → onUtteranceEnd()
                                   resetSchedule()
```

### 實作步驟

| 步驟 | 內容 | 產出檔案 |
|------|------|---------|
| 1. 寫失敗測試 | queue 順序、is_final 收尾、abnormal chunk 隔離、stopAll 排空 | `frontend/app/src/composables/__tests__/useAudioPlayer.spec.ts` |
| 2. 重構 `useAudioPlayer` | 新增內部 `pendingQueue`，將 `playChunk` 改為 `enqueueChunk` 並走 drain loop | `frontend/app/src/composables/useAudioPlayer.ts` |
| 3. is_final 收尾 | 標記 final chunk，最後一個 source `onended` 時 emit `onUtteranceEnd` + `resetSchedule()` | 同上 |
| 4. 接線 useAvatarChat | `server_stream_chunk` 改呼叫 `enqueueChunk`，傳入 `chunk_id` / `audio_base64` / `is_final` | `frontend/app/src/composables/useAvatarChat.ts` |
| 5. 排空策略 | `stopAll()` / `flush()` 同時清 pendingQueue 與已排程 source | `useAudioPlayer.ts` |
| 6. 觀測 | 失敗 chunk 計數 + console.warn（非 console.log），便於 e2e 抓回歸 | 同上 |

### 介面變更草案

```ts
interface AudioChunk {
  chunkId: string
  audioBase64: string
  isFinal: boolean
}

interface AudioPlayerOptions {
  onPcmChunk?: (pcm: Int16Array) => void
  onUtteranceEnd?: (lastChunkId: string) => void   // 取代既有 onPlaybackEnd / onQueueEmpty
  onChunkDropped?: (chunkId: string, reason: string) => void
}

function enqueueChunk(chunk: AudioChunk): void
function flush(): void          // 清 pending + 已排程
function resetSchedule(): void  // 既有，僅重設 nextStartTime
```

### 邊界情境

| 情境 | 處理 |
|------|------|
| audio_base64 解碼失敗 | 跳過該 chunk，呼叫 `onChunkDropped`，不阻塞後續 |
| 收到亂序到達（網路重傳） | 仍依抵達順序入隊 — server 端保證 chunk_id 序列為發送序 |
| `is_final` 在中途不再來 | session_end / stopAll 時主動 flush，視為非正常結束 |
| 連續多段 utterance | 上一段 `is_final` 觸發 `resetSchedule()`，下一段重新從 `currentTime` 起算 |
| AudioContext suspended | `enqueueChunk` 內 `await ctx.resume()`，第一筆需在 user gesture 之後 |

---

## 驗收方法

### 自動驗收

| 檢查項目 | 指令 | 驗證內容 |
|---------|------|---------|
| 單元測試 | `cd frontend/app && npm run test -- useAudioPlayer` | queue 順序、is_final 收尾、abnormal chunk 隔離、flush 排空 |
| 型別檢查 | `cd frontend/app && npx vue-tsc --noEmit` | `AudioChunk` / `enqueueChunk` 型別正確 |
| Lint | `cd frontend/app && npm run lint` | 無 console.log、符合既有風格 |

### 手動驗收

| 驗收標準 | 如何確認 |
|---------|---------|
| chunk playback order is stable | 連跑 5 次 user_speak，序列號對齊 server 發送順序（觀察 chunk_id 與排程時序） |
| queue drains cleanly at session end | 連線中途 disconnect，`pendingQueue.length === 0` 且無懸掛 source |
| no dropped chunk under normal streaming load | 一般 LLM streaming 場景（< 50 chunks/utterance）下 `onChunkDropped` 不被觸發 |
| `is_final` 後可正確收尾 | 最後一個 chunk 播畢觸發 `onUtteranceEnd`，state 從 SPEAKING → IDLE |

### 驗證指令

```bash
# 1. 單元測試
cd frontend/app && npm run test -- useAudioPlayer

# 2. 型別檢查
cd frontend/app && npx vue-tsc --noEmit

# 3. E2E（連線實機）
docker compose up -d && \
  open http://localhost:8080 && \
  # 觸發 user_speak，觀察 console 無 onChunkDropped 警告
```

---

## 檔案清單

| 檔案 | 動作 | 用途 |
|------|------|------|
| `frontend/app/src/composables/useAudioPlayer.ts` | 修改 | 新增 pendingQueue + enqueueChunk + is_final 收尾 |
| `frontend/app/src/composables/useAvatarChat.ts` | 修改 | `server_stream_chunk` 改呼叫 enqueueChunk |
| `frontend/app/src/composables/__tests__/useAudioPlayer.spec.ts` | 新增 | queue / is_final / flush / 失敗隔離測試 |
| `docs/plans/TASK-07-frontend-audio-queue-and-chunk-playback.md` | 新增 | 計畫書 |

---

## 相依性與風險

- **相依 TASK-04 / TASK-05**：`server_stream_chunk` schema 與 generated contracts（已存在 `contracts/schemas/v1/server_stream_chunk.schema.json`）。
- **相依 TASK-06**：`server_init_ack` handshake 完成後才會收到 chunk。
- **風險**：`AudioContext.createBuffer` 在某些瀏覽器對非常小的 chunk（< 10ms）會 underrun — 需在測試中模擬最小 chunk 並確認 gapless。
- **風險**：MatesX WASM lip-sync `onPcmChunk` 必須與排程時序一致，否則嘴型會超前/落後 — 沿用既有「解碼即呼叫」順序，不延遲到播放時刻。
