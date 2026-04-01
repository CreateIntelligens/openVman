## Why

The project already has the major building blocks for live voice interaction, but they are still disconnected: browser ASR exists on the frontend, Brain can stream tokens over SSE, and Backend can synthesize TTS over HTTP. What is missing is the nervous-system layer that turns those pieces into a coherent live session with <300ms latency, smart interruption, and audio-driven lip-sync, powered by the newly integrated VibeVoice-0.5B engine.

This change is needed now because the current WebSocket path is still a placeholder, the live control contract is incomplete, and interruption behavior is ambiguous. Without a clear contract and orchestration layer, frontend, backend, and Brain will continue to drift and implementation will remain fragile.

## What Changes

- Add an end-to-end live voice WebSocket pipeline that connects frontend ASR, backend orchestration, Brain token streaming, sentence-level TTS, and frontend audio playback.
- Define smart interruption behavior so `client_interrupt` remains a control signal evaluated by a lightweight Backend Guard Agent rather than a new Brain chat turn.
- Formalize the live control protocol, including handshake, lip-sync mode signaling, stop-audio signaling, and the separation between `client_interrupt` and `user_speak`.
- Add a runnable frontend live runtime that performs browser ASR, supports browser-side speech turn detection with optional true VAD, auto-submits speech after silence, receives audio chunks, clears playback on stop, and drives lip-sync from audio instead of visemes.
- Keep Brain focused on token streaming and cognition while moving text-to-sentence chunking and TTS orchestration fully into Backend.

## Capabilities

### New Capabilities
- `live-voice-websocket-pipeline`: Establishes the live session flow from frontend WebSocket events through Backend orchestration to Brain streaming and sentence-level TTS audio chunks.
- `smart-interruption-control`: Defines how interruption is classified, how control signals differ from formal user input, and how active audio/Brain generation is stopped safely.
- `frontend-live-audio-runtime`: Defines the browser-side live runtime for ASR capture, browser-side turn detection, silence-based auto-send, WebSocket event handling, audio queue playback, and audio-driven lip-sync lifecycle.

### Modified Capabilities
- `frontend-lipsync-manager`: Adjust lip-sync manager behavior so it participates in the live runtime through `set_lip_sync_mode`, audio-driven playback, and stop/reset handling instead of assuming an isolated renderer-only role.

## Impact

 - Affected code: `backend/app/main.py`, `backend/app/session_manager.py`, `backend/app/guard_agent.py`, new backend live pipeline helpers, `frontend/app/src/services/*`, `frontend/app/src/lib/lip-sync-manager/*`, frontend voice/VAD runtime hooks, frontend app bootstrap files, and protocol validator consumers.
- Affected APIs: frontend/backend WebSocket event flow, shared protocol contracts in `contracts/schemas/v1`, generated TypeScript/Python contract artifacts, and Brain/Backend interaction at the streaming boundary.
 - Affected dependencies: browser-side VAD dependency/runtime if true VAD is enabled, plus associated frontend asset loading.
 - Affected systems: Frontend, Backend, Brain, and the shared OpenSpec/documentation layer for live voice behavior.
