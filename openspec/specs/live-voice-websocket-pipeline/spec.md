# live-voice-websocket-pipeline Specification

## Purpose
Establishes the live session flow from frontend WebSocket events through Backend orchestration to Brain streaming and sentence-level TTS audio chunks.

## Requirements

### Requirement: Live voice sessions use a single frontend/backend WebSocket path
The system SHALL establish a single authenticated frontend/backend WebSocket session for live voice interaction, and that session SHALL carry handshake, user text input, interruption control, stop-audio control, and streamed audio chunk responses. The WebSocket upgrade SHALL authenticate the same-origin session cookie or Authorization header before creating server session state. The `client_init` event SHALL support a `capabilities` object containing optional `voice_source` field (`"gemini"` | `"custom"`), and every supplied project, persona, character, or voice identifier SHALL be resolved within the authenticated account's accessible resources.

#### Scenario: Handshake succeeds before live interaction
- **WHEN** an authenticated frontend opens a live WebSocket connection
- **THEN** it sends `client_init` (optionally including `capabilities.voice_source`) and the backend returns `server_init_ack` only after validating every requested resource before processing any live user turn

#### Scenario: Unauthenticated WebSocket is rejected
- **WHEN** a client opens the live WebSocket without a valid session cookie or Authorization header
- **THEN** the backend rejects the connection before allocating a live session, Brain relay, or TTS resource

#### Scenario: Foreign capability resource is rejected
- **WHEN** an authenticated client sends `client_init` with a project, persona, character, or custom voice it cannot access
- **THEN** the backend rejects initialization and does not reveal whether that private resource exists

#### Scenario: Live response arrives as audio chunks
- **WHEN** an authenticated frontend sends `user_speak` after successful initialization
- **THEN** the backend emits one or more `server_stream_chunk` events containing chunk text, `audio_base64`, and `is_final`

### Requirement: user_speak in Live mode always routes through BrainLiveRelay
In Live mode, the backend `_handle_user_speak` handler SHALL always ensure a `BrainLiveRelay` is initialized (via `_ensure_brain_relay`) before forwarding the `user_speak` event to Brain, regardless of whether the user has previously sent audio. The `LiveVoicePipeline` fallback path SHALL NOT be used for Live mode `user_speak` events.

#### Scenario: Text input before any audio
- **WHEN** the user sends `user_speak` in Live mode without having sent any `client_audio_chunk` first
- **THEN** the backend SHALL initialize a `BrainLiveRelay` (if not already initialized) and route the text through it to Gemini

#### Scenario: Text input after audio session
- **WHEN** the user sends `user_speak` after having used the microphone (BrainLiveRelay already exists)
- **THEN** the backend SHALL route the text through the existing BrainLiveRelay to Gemini

### Requirement: Brain remains a token-stream provider for live orchestration
The live pipeline SHALL treat Brain as a token-stream provider only, and the backend SHALL be responsible for converting that token stream into sentence-level TTS requests.

#### Scenario: Backend chunks token stream by punctuation
- **WHEN** Brain returns a token stream for a user turn
- **THEN** the backend buffers tokens into sentence chunks and sends each completed chunk to TTS without waiting for the full answer

#### Scenario: Final chunk closes the speaking turn
- **WHEN** Brain completes the token stream and the backend emits the last synthesized chunk
- **THEN** the last `server_stream_chunk` is marked `is_final=true`
