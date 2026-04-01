# Alignment Notes: Live Voice Pipeline

This document records the necessary updates for owner-maintained architectural documentation to align with the `add-live-voice-websocket-pipeline` change.

## 1. `docs/00_SYSTEM_ARCHITECTURE.md`
- **Update Component Responsibilities**: Explicitly mention `VibeVoice-0.5B` as the real-time synthesis engine in the Nervous System (Backend) section.
- **Update Workflow (Dialogue Flow)**: 
    - Clarify that `client_interrupt` is a control signal judged by the `Guard Agent` in the Backend.
    - Clarify that `user_speak` is the only formal turn-creation event sent to the Brain.
    - Mention that lip-sync is now audio-driven on the frontend (no visemes required from backend).

## 2. `docs/09_API_WS_LINKAGE.md`
- **Register New Events**: Add `set_lip_sync_mode` and `server_stop_audio` to the WebSocket event tables.
- **Update Event Schemas**: Reflect that `visemes` are now optional in `server_stream_chunk` and `partial_asr` is optional in `client_interrupt`.
- **Latency Targets**: Update the end-to-end latency target to `<300ms` for first-audio-chunk delivery.

## 3. `docs/10_MICROSERVICES_GUIDE.md`
- **Streaming Pipeline Section**: Add a dedicated section explaining the token-to-sentence-to-audio-chunk streaming flow between `api`, `backend`, and `vibevoice-serve`.
