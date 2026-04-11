## ADDED Requirements

### Requirement: Chat page SHALL support toggling between Text and Live modes
The admin Chat page SHALL provide a mode toggle in the header that switches between Text mode (existing HTTP SSE chat) and Live mode (WebSocket voice session).

#### Scenario: Default mode is Text
- **WHEN** the Chat page loads
- **THEN** the mode is Text and all existing chat functionality works unchanged

#### Scenario: Switching to Live mode connects WebSocket
- **WHEN** the user toggles from Text to Live mode
- **THEN** the system opens a WebSocket to `/ws/{client_id}`, sends `client_init`, and waits for `server_init_ack`

#### Scenario: Switching back to Text mode disconnects WebSocket
- **WHEN** the user toggles from Live to Text mode
- **THEN** the system stops MediaRecorder, closes WebSocket, and restores Text mode UI

### Requirement: Live mode SHALL capture microphone audio and stream to backend
The system SHALL use MediaRecorder to capture microphone audio and send chunks as `client_audio_chunk` events over the WebSocket.

#### Scenario: Microphone starts streaming on activation
- **WHEN** the user activates the microphone in Live mode
- **THEN** the system requests microphone permission, starts MediaRecorder, and sends `client_audio_chunk` events with base64-encoded audio at regular intervals

#### Scenario: Microphone stops on deactivation
- **WHEN** the user deactivates the microphone or toggles off Live mode
- **THEN** the system sends `client_audio_end`, stops MediaRecorder, and releases the media stream

#### Scenario: Text input sends user_speak in Live mode
- **WHEN** the user types text and presses Enter in Live mode
- **THEN** the system sends a `user_speak` event over the WebSocket with the typed text

### Requirement: Live mode SHALL play audio responses from the backend
The system SHALL receive `server_stream_chunk` events, decode the audio, and play chunks sequentially.

#### Scenario: Audio chunks play in order
- **WHEN** multiple `server_stream_chunk` events arrive
- **THEN** the system decodes and plays them sequentially without gaps

#### Scenario: Stop audio clears playback
- **WHEN** a `server_stop_audio` event arrives
- **THEN** the system immediately stops all pending and playing audio

### Requirement: Live mode SHALL support interruption
The system SHALL send `client_interrupt` when the user starts speaking while audio is playing, and SHALL stop local playback immediately.

#### Scenario: Speaking during playback triggers interrupt
- **WHEN** the user activates the microphone while audio is playing
- **THEN** the system sends `client_interrupt`, stops local audio playback, and begins streaming microphone audio

### Requirement: Live mode SHALL display connection and session state
The system SHALL show visual indicators for the current Live session state.

#### Scenario: Connecting state shown during handshake
- **WHEN** the WebSocket is connecting or awaiting `server_init_ack`
- **THEN** the UI shows a "連線中" indicator

#### Scenario: Ready state shown after handshake
- **WHEN** `server_init_ack` is received
- **THEN** the UI shows "已連線" and enables the microphone button

#### Scenario: Listening state shown during audio capture
- **WHEN** the microphone is active and streaming audio
- **THEN** the UI shows "聆聽中" indicator

#### Scenario: Speaking state shown during playback
- **WHEN** audio response is playing
- **THEN** the UI shows "回覆中" indicator

#### Scenario: Disconnected state triggers reconnect
- **WHEN** the WebSocket disconnects unexpectedly
- **THEN** the UI shows "已斷線" and attempts reconnection after 3 seconds
