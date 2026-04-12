## MODIFIED Requirements

### Requirement: Live voice sessions use a single frontend/backend WebSocket path
The system SHALL establish a single frontend/backend WebSocket session for live voice interaction, and that session SHALL carry handshake, user text input, interruption control, stop-audio control, and streamed audio chunk responses. The `client_init` event SHALL support a `capabilities` object containing optional `voice_source` field (`"gemini"` | `"custom"`).

#### Scenario: Handshake succeeds before live interaction
- **WHEN** the frontend opens a live WebSocket connection
- **THEN** it sends `client_init` (optionally including `capabilities.voice_source`) and the backend returns `server_init_ack` before processing any live user turn

#### Scenario: Live response arrives as audio chunks
- **WHEN** the frontend sends `user_speak`
- **THEN** the backend emits one or more `server_stream_chunk` events containing chunk text, `audio_base64`, and `is_final`

## ADDED Requirements

### Requirement: user_speak in Live mode always routes through BrainLiveRelay
In Live mode, the backend `_handle_user_speak` handler SHALL always ensure a `BrainLiveRelay` is initialized (via `_ensure_brain_relay`) before forwarding the `user_speak` event to Brain, regardless of whether the user has previously sent audio. The `LiveVoicePipeline` fallback path SHALL NOT be used for Live mode `user_speak` events.

#### Scenario: Text input before any audio
- **WHEN** the user sends `user_speak` in Live mode without having sent any `client_audio_chunk` first
- **THEN** the backend SHALL initialize a `BrainLiveRelay` (if not already initialized) and route the text through it to Gemini

#### Scenario: Text input after audio session
- **WHEN** the user sends `user_speak` after having used the microphone (BrainLiveRelay already exists)
- **THEN** the backend SHALL route the text through the existing BrainLiveRelay to Gemini
