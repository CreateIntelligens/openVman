## ADDED Requirements

### Requirement: Frontend live runtime performs browser ASR, local turn detection, and emits protocol events
The frontend live runtime SHALL perform browser-based ASR, SHALL detect speech turns locally, SHALL emit `client_interrupt` during barge-in conditions, and SHALL emit `user_speak` only after stable/final user text is available.

#### Scenario: Speech start triggers interruption control
- **WHEN** the frontend detects a new speech start while the avatar is already speaking
- **THEN** the frontend sends `client_interrupt` on the control path without waiting for final ASR text

#### Scenario: True VAD is unavailable
- **WHEN** the browser does not support the configured true VAD runtime or VAD initialization fails
- **THEN** the frontend continues voice capture using browser ASR and derives turn boundaries from transcript inactivity timing

#### Scenario: Final ASR becomes formal user input
- **WHEN** the browser produces a final ASR result for the user utterance
- **THEN** the frontend sends `user_speak` as the formal live input event

### Requirement: Frontend live runtime auto-submits spoken turns after silence
The frontend live runtime SHALL wait for a configured silence window after speech end and SHALL submit one `user_speak` event for the current utterance only when the stabilized transcript is non-empty.

#### Scenario: Silence timeout completes with transcript text
- **WHEN** a speech turn ends and the configured silence window expires with non-empty stabilized transcript text
- **THEN** the frontend sends one `user_speak` event for that utterance

#### Scenario: Repeated transcript updates do not duplicate submit
- **WHEN** the browser emits repeated finalization or end-like updates for the same spoken utterance
- **THEN** the frontend suppresses duplicate `user_speak` submissions for that utterance

### Requirement: Frontend live runtime plays streamed audio and drives lip-sync from audio
The frontend live runtime SHALL enqueue incoming `server_stream_chunk` payloads, SHALL stop playback when `server_stop_audio` is received, and SHALL drive lip-sync from the received audio timeline rather than backend visemes.

#### Scenario: Audio chunks are queued in order
- **WHEN** multiple `server_stream_chunk` events arrive for one response
- **THEN** the frontend decodes and plays them sequentially in arrival order

#### Scenario: Stop-audio clears playback and render state
- **WHEN** the backend emits `server_stop_audio`
- **THEN** the frontend clears pending audio playback and resets speaking-related render state
