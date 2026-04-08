## Why

The previous direction put Gemini Live session ownership inside `backend`, which conflicts with the current system boundary:

- `brain` should own model sessions, tool calling, memory, and RAG
- `backend` should remain the public WebSocket/media gateway and protocol bridge

If Gemini Live lives in `backend`, we split LLM/session logic across two services and make tool calling, memory access, and recovery logic harder to reason about. To keep the architecture coherent, Gemini Live must be managed by `brain`, while `backend` relays frontend WebSocket events to the internal Brain live session.

## What Changes

- Keep the public `/ws/{client_id}` endpoint in `backend`, routing by event type and session state:
  - `user_speak` without an active relay → existing Brain SSE → TTS path
  - `client_audio_chunk` / `client_audio_end` → create Brain relay on first audio event, forward to Brain
  - `user_speak` with an active relay → forward to Brain relay (text fallback)
- Move Gemini Live session lifecycle, tool calling, audio/text turn handling, reconnect, and keepalive into `brain`
- Add an internal Brain live bridge so `backend` can forward:
  - `user_speak`
  - `client_audio_chunk`
  - `client_audio_end`
  - `client_interrupt`
- Keep frontend changes for raw microphone PCM streaming in `gemini_live` mode
- Preserve typed-text fallback when a Brain relay is active

## Capabilities

### New Capabilities
- `gemini-live-session-manager`: Brain-owned persistent Gemini Live session lifecycle, including setup, reuse, reconnect, keepalive, and teardown
- `brain-live-relay`: Internal duplex channel between `backend` and `brain` for live events and streamed responses
- `gemini-live-audio-input`: Full-duplex audio input path from frontend microphone through backend relay into Brain-owned Gemini Live sessions

### Modified Capabilities
- `live-voice-websocket-pipeline`: Backend `/ws/{client_id}` gains event-driven routing — audio events create a Brain relay, and `user_speak` routes through the relay when active
- `frontend-live-audio-runtime`: Frontend runtime supports a raw-audio mode for `gemini_live` while preserving existing `brain_tts` behavior

## Impact

- **Affected backend code**: `backend/app/main.py` (event-driven relay routing), new backend relay module for the internal Brain live bridge
- **Affected brain code**: `brain/api/config.py`, new Gemini Live session manager, new internal live endpoint/bridge, tool-call integration with existing memory/RAG flows
- **Affected frontend code**: `frontend/app/src/services/websocket.ts`, `frontend/app/src/services/liveRuntime.ts`, new `frontend/app/src/services/audioStreamer.ts`
- **Affected APIs**:
  - Public WS protocol gains `client_audio_chunk` and `client_audio_end`
  - Brain gains an internal live relay interface for backend-to-brain duplex streaming
- **Affected systems**: backend, brain, frontend, protocol contracts
