# Tasks: Add Live Voice WebSocket Pipeline

## 1. Protocol Contracts

- [x] 1.1 Add `set_lip_sync_mode` and `server_stop_audio` schemas under `contracts/schemas/v1/` and register them in `manifest.json`
- [x] 1.2 Update `client_interrupt` schema to allow optional `partial_asr` while preserving its control-signal semantics
- [x] 1.3 Update `server_stream_chunk` schema so audio-driven chunks no longer require `visemes`
- [x] 1.4 Regenerate TypeScript and Python protocol contracts and update validator consumers in Brain and frontend admin
- [x] 1.5 Record follow-up alignment notes for owner-maintained docs such as `docs/00_SYSTEM_ARCHITECTURE.md` and `docs/09_API_WS_LINKAGE.md` without blocking implementation

## 2. Backend Live Orchestration

- [x] 2.1 Expand `backend/app/session_manager.py` to track websocket session state, buffers, queues, and client/session lookup
- [x] 2.2 Add a backend live pipeline helper module that consumes Brain SSE tokens, chunks text by punctuation, synthesizes sentence audio, and builds `server_stream_chunk` payloads
- [x] 2.3 Replace the placeholder `user_speak` websocket path in `backend/app/main.py` with live Brain-stream-to-TTS orchestration
- [x] 2.4 Keep `client_interrupt` on the control path by classifying it with `backend/app/guard_agent.py` and preventing it from creating a Brain turn
- [x] 2.5 Emit `server_stop_audio` and reset session state cleanly when an interruption is accepted

## 3. Frontend Live Runtime

- [x] 3.1 Create the missing `frontend/app` runtime shell (`index.html`, TS config, Vite config, `src/main.tsx`, `src/App.tsx`)
- [x] 3.2 Update `frontend/app/src/services/websocket.ts` to send `client_init`, `client_interrupt`, `user_speak`, and lip-sync mode events using the shared protocol
- [x] 3.3 Add a frontend audio playback queue that decodes streamed audio chunks in order and clears on `server_stop_audio`
- [x] 3.4 Add browser-side turn detection to the live runtime, using true VAD when available and ASR silence fallback otherwise
- [x] 3.5 Wire `ASRService`, VAD/turn-detection state, `WebSocketService`, and `LipSyncManager` together so speech start can interrupt and stabilized speech becomes `user_speak`
- [x] 3.6 Add silence-based auto-send so one spoken utterance submits once after the configured quiet window
- [x] 3.7 Update `frontend/app/src/lib/lip-sync-manager/index.ts` so live playback is audio-driven and reset-aware during local interruption

## 4. Hardening And Observability

- [x] 4.1 Add websocket heartbeat (`ping`/`pong`) and stale-session cleanup in Backend
- [x] 4.2 Add live metrics for active sessions, queue depth, interruption count, and `user_speak` to first-audio latency
- [x] 4.3 Normalize live pipeline failures into shared `server_error` events without introducing a public `INTERNAL_CANCEL` event
- [x] 4.4 Add configurable frontend thresholds for speech start filtering and silence timeout so noise tolerance can be tuned without changing protocol semantics
- [x] 4.5 Update health and verification docs so operators can smoke-test handshake, interruption, VAD fallback, and chunked playback behavior

## 5. Verification

- [x] 5.1 Add or extend backend tests for session state, live websocket streaming, interruption behavior, heartbeat, and error bridging
- [x] 5.2 Add frontend tests for true VAD available, true VAD unavailable, silence auto-send, and duplicate-submit prevention
- [x] 5.3 Add or extend Brain/frontend admin protocol validation coverage for the updated live control contract
- [x] 5.4 Build `frontend/admin` and `frontend/app` successfully against the updated live protocol
- [x] 5.5 Run the focused backend, Brain, frontend, and contract verification commands required for the live pipeline change
