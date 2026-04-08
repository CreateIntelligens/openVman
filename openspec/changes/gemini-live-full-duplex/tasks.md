# Tasks: Gemini Live Full-Duplex Upgrade

## 1. Config & Ownership Boundary

- [x] 1.1 ~~Add `live_provider` to `TTSRouterConfig`~~ Removed — routing is event-driven, no config flag needed
- [x] 1.2 Add Brain-owned `live_gemini_*` configuration fields to `brain/api/config.py`
- [x] 1.3 ~~Update `backend/.env.example` with `LIVE_PROVIDER`~~ Removed — no backend config needed for live routing
- [x] 1.4 Update `brain/.env.example` with the new Brain-owned `LIVE_GEMINI_*` environment variables and documentation comments

## 2. Backend Public WS Relay

- [x] 2.1 Add event-driven routing in `backend/app/main.py`: audio events create Brain relay, `user_speak` checks for active relay
- [x] 2.2 Add a backend relay path that opens/maintains one internal Brain live connection per public client session (lazy init on first audio event)
- [x] 2.3 Forward `user_speak` to Brain live relay when one is active, otherwise use `LiveVoicePipeline`
- [x] 2.4 Close the Brain live relay connection when the public WebSocket disconnects

## 3. Brain Live Bridge

- [x] 3.1 Add a Brain internal live bridge endpoint for backend-to-brain duplex streaming
- [x] 3.2 Add Brain-side session state to hold one persistent `GeminiLiveSession` per relayed session
- [x] 3.3 Ensure the Brain live bridge reuses the same `GeminiLiveSession` across multiple turns
- [x] 3.4 Close the Brain `GeminiLiveSession` when the backend relay disconnects

## 4. Brain-Owned Gemini Session Manager

- [x] 4.1 Extract Brain-owned Gemini transport lifecycle into a `GeminiLiveSession` class under `brain/api`
- [x] 4.2 Implement connect + setup + close lifecycle on `GeminiLiveSession`
- [x] 4.3 Implement text turn submission on `GeminiLiveSession` for relayed `user_speak`
- [x] 4.4 Implement a background listener that reads Gemini responses and emits relay-ready server events upstream
- [x] 4.5 Keep Gemini tool calling in Brain and integrate it with existing knowledge/memory search flows

## 5. Auto-Reconnect & Keepalive (Brain)

- [x] 5.1 Add exponential backoff reconnect logic to `GeminiLiveSession` (1s→2s→4s→8s→16s with jitter, max 5 retries)
- [x] 5.2 Emit `server_stop_audio` upstream when reconnect is triggered during an active response
- [x] 5.3 Emit `server_error` upstream when max retries are exceeded and mark the Gemini transport unavailable
- [x] 5.4 Add periodic keepalive (every 10 min) tied to the Brain-owned `GeminiLiveSession` lifecycle

## 6. Audio Input Relay

- [x] 6.1 Add `client_audio_chunk` and `client_audio_end` handling in `backend/app/main.py`
- [x] 6.2 Forward `client_audio_chunk` from backend relay to Brain live bridge in `gemini_live` mode
- [x] 6.3 Forward `client_audio_end` from backend relay to Brain live bridge in `gemini_live` mode
- [x] 6.4 Implement `send_realtime_input(audio_b64, mime_type)` on Brain-owned `GeminiLiveSession`
- [x] 6.5 Implement `send_turn_complete()` on Brain-owned `GeminiLiveSession`
- [x] 6.6 Silently drop relayed audio chunks when Brain's Gemini transport is reconnecting or unavailable

## 7. Protocol Contracts

- [x] 7.1 Add `client_audio_chunk` schema (`audio_base64`, `sample_rate`, `mime_type`, `timestamp`) to `contracts/schemas/v1/` and register it
- [x] 7.2 Add `client_audio_end` schema (`timestamp`) to `contracts/schemas/v1/` and register it
- [x] 7.3 Regenerate TypeScript and Python protocol contracts

## 8. Frontend AudioStreamer

- [x] 8.1 Create `frontend/app/src/services/audioStreamer.ts` with AudioWorklet-based 16 kHz mono PCM capture and base64 chunking at ~100 ms intervals
- [x] 8.2 Add ScriptProcessorNode fallback for browsers without AudioWorklet support
- [x] 8.3 Add `sendAudioChunk(audio_base64, sample_rate, mime_type)` and `sendAudioEnd()` methods to `frontend/app/src/services/websocket.ts`

## 9. Frontend LiveRuntime Dual-Mode

- [x] 9.1 Add `mode` to `LiveRuntime` (`brain_tts` | `gemini_live`) and wire `AudioStreamer` start/stop to runtime lifecycle
- [x] 9.2 In `gemini_live` mode, suppress ASR-derived `user_speak` submission while keeping ASR for display
- [x] 9.3 In `gemini_live` mode, send `client_audio_end` on VAD speech-end instead of `user_speak`
- [x] 9.4 Preserve typed text input fallback in `gemini_live` mode by still sending `user_speak`

## 10. Testing

- [x] 10.1 Add Brain-side unit tests for `GeminiLiveSession` persistence: connect-once, reuse across turns, close on relay disconnect
- [x] 10.2 Add Brain-side unit tests for reconnect behavior: backoff timing, max retries, `server_stop_audio`, keepalive scheduling
- [x] 10.3 Add Brain-side unit tests for audio relay: relayed `client_audio_chunk` to `realtimeInput`, `client_audio_end` to `turnComplete`, drop during reconnect
- [x] 10.4 Add backend integration tests for provider routing and Brain relay passthrough behavior
- [x] 10.5 Add frontend tests for `AudioStreamer`: start/stop lifecycle, chunk interval, resource cleanup
- [x] 10.6 Add frontend tests for `LiveRuntime` dual-mode behavior

## 11. Verification

- [x] 11.1 Run the relevant Gemini Live tests after refactor to ensure the earlier backend draft path is not regressing unexpectedly
- [x] 11.2 Run the full backend and Brain test suites (Note: 162 pre-existing failures unrelated to Gemini Live changes)
- [x] 11.3 Frontend tests pass (24/24 vitest with jsdom)
- [x] 11.4 Manual smoke test: text-in/audio-out via backend relay to Brain-owned Gemini Live, audio-in/audio-out full-duplex, reconnect after forced disconnect
