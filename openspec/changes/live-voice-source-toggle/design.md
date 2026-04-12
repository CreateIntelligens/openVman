## Context

Admin Chat Live 模式已打通 WebSocket → Backend → Brain → Gemini Live 全鏈路。目前 Gemini 回覆同時包含文字和音訊（`server_stream_chunk` 帶 `text` + `audio_base64`），但使用者無法選擇要用 Gemini 的聲音還是我們的 TTS。此外 `user_speak` 的路由取決於 `brain_live_relay` 是否已 lazy init，行為不一致。

## Goals / Non-Goals

**Goals:**
- Live 模式所有輸入（音訊 + 文字）統一走 BrainLiveRelay → Gemini
- 使用者可在前端切換語音來源（Gemini / 自訂 TTS）
- `voice_source` 選項通過 `client_init` capabilities 傳遞，backend 感知後決定行為

**Non-Goals:**
- 不改 Brain 端邏輯（Gemini 始終回 text + audio）
- 不改 Text 模式行為
- 不做語音來源的 per-message 切換（整個 session 固定一種）
- 不新增 TTS 語音選擇（沿用現有 TTSRouterService 預設）

## Decisions

### 1. voice_source 透過 client_init capabilities 傳遞

在 `client_init` 的 `capabilities` 物件中新增 `voice_source: "gemini" | "custom"`，預設 `"gemini"`。Backend 在 `_handle_client_init` 時讀取並存入 session metadata。

**替代方案**：獨立 WebSocket event（`set_voice_source`）— 更靈活但增加複雜度，且目前需求是 session 級別，不需要動態切換。

### 2. BrainLiveRelay 攔截模式處理 custom TTS

`voice_source === "custom"` 時，BrainLiveRelay 的 `_listen` 方法攔截 `server_stream_chunk` event：
1. 取出 `text`，丟棄 `audio_base64`
2. 用 `TTSRouterService.synthesize` 合成音訊
3. 替換 `audio_base64` 後送 `event_sink`

用 asyncio queue + worker 的方式處理，避免阻塞 listener。TTS 合成是同步的，需要 `run_in_executor`。

**替代方案**：在 Brain 端加 flag 控制是否回音訊 — 需改 Brain，且 Gemini API 不支援只回文字不回音訊。

### 3. user_speak 統一走 relay

`_handle_user_speak` 中，Live 模式下一律先 `_ensure_brain_relay` 再 `send_event`，移除 `LiveVoicePipeline` fallback 分支。`LiveVoicePipeline` 不刪除，Text 模式的 SSE 流仍可能用到。

### 4. 前端 UI：Live 狀態列加下拉選項

在 Chat.tsx Live 狀態列右側加一個小的 voice source 切換（pill toggle 或 Select），切換時斷線重連（因為 voice_source 在 client_init 階段傳遞）。

## Risks / Trade-offs

- **延遲增加（custom 模式）**：Gemini 回文字 → backend 跑 TTS → 送前端，比 Gemini 直接回音訊慢。→ 使用者自行取捨，UI 上可提示。
- **TTS 合成失敗**：TTSRouterService 可能失敗，導致有文字無音訊。→ 發 `server_stream_chunk` 時帶空 audio，前端顯示文字即可。
- **斷線重連的 UX**：切換 voice source 需要重連 WebSocket。→ 對話紀錄保留在前端 state 中，重連後不會消失。
