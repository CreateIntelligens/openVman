## ADDED Requirements

### Requirement: Voice source option in client_init capabilities
The frontend SHALL include a `voice_source` field in the `client_init` capabilities object, with allowed values `"gemini"` (default) and `"custom"`. The backend SHALL read `voice_source` from `client_init` capabilities and store it in session metadata for the duration of the WebSocket session.

#### Scenario: client_init with default voice source
- **WHEN** the frontend sends `client_init` without a `voice_source` in capabilities
- **THEN** the backend SHALL default `voice_source` to `"gemini"` and store it in session metadata

#### Scenario: client_init with explicit voice source
- **WHEN** the frontend sends `client_init` with `capabilities.voice_source` set to `"custom"`
- **THEN** the backend SHALL store `voice_source = "custom"` in session metadata

### Requirement: BrainLiveRelay intercepts audio for custom voice source
When `voice_source` is `"custom"`, the `BrainLiveRelay` SHALL intercept each `server_stream_chunk` event from Brain, discard the `audio_base64` field, extract the `text` field, synthesize replacement audio via `TTSRouterService`, and emit the chunk with the synthesized `audio_base64` to the frontend.

#### Scenario: Gemini voice passthrough
- **WHEN** `voice_source` is `"gemini"` and BrainLiveRelay receives a `server_stream_chunk` from Brain
- **THEN** the relay SHALL forward the event unchanged to the frontend (text + Gemini audio intact)

#### Scenario: Custom TTS synthesis replaces Gemini audio
- **WHEN** `voice_source` is `"custom"` and BrainLiveRelay receives a `server_stream_chunk` with `text` and `audio_base64`
- **THEN** the relay SHALL discard the original `audio_base64`, call `TTSRouterService.synthesize` with the `text`, and emit the chunk with the synthesized audio as `audio_base64`

#### Scenario: TTS synthesis failure fallback
- **WHEN** `voice_source` is `"custom"` and `TTSRouterService.synthesize` fails for a chunk
- **THEN** the relay SHALL emit the `server_stream_chunk` with `text` intact and `audio_base64` set to empty string, so the frontend displays text without audio

### Requirement: TTS synthesis does not block the relay listener
The BrainLiveRelay SHALL process custom TTS synthesis asynchronously using a queue and worker pattern, so that the Brain WebSocket listener is never blocked by TTS latency.

#### Scenario: Concurrent chunks queued for synthesis
- **WHEN** multiple `server_stream_chunk` events arrive in rapid succession with `voice_source = "custom"`
- **THEN** each chunk SHALL be enqueued for TTS synthesis and emitted to the frontend in arrival order after synthesis completes

### Requirement: Frontend voice source toggle UI
The frontend SHALL display a voice source selector in the Live mode status bar, allowing the user to choose between `"gemini"` and `"custom"` voice sources. The selector SHALL only be visible when the mode is `"live"`.

#### Scenario: Toggle triggers reconnect
- **WHEN** the user changes the voice source selector while connected
- **THEN** the frontend SHALL disconnect the current WebSocket session and reconnect with the new `voice_source` value in `client_init` capabilities

#### Scenario: Voice source persists across reconnects
- **WHEN** the user has selected `"custom"` and the WebSocket reconnects (manual or automatic)
- **THEN** the reconnection `client_init` SHALL include `capabilities.voice_source = "custom"`

### Requirement: Frontend useLiveSession accepts voiceSource parameter
The `useLiveSession` hook SHALL accept an optional `voiceSource` parameter (`"gemini"` | `"custom"`, default `"gemini"`) and include it in the `client_init` capabilities sent during WebSocket handshake. When `voiceSource` changes, the hook SHALL disconnect and reconnect.

#### Scenario: voiceSource change triggers reconnect
- **WHEN** the `voiceSource` parameter passed to `useLiveSession` changes from `"gemini"` to `"custom"`
- **THEN** the hook SHALL close the existing WebSocket connection and open a new one with updated `client_init` capabilities
