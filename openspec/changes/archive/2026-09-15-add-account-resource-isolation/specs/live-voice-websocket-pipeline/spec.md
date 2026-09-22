## MODIFIED Requirements

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
