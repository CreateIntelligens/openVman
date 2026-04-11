## ADDED Requirements

### Requirement: Frontend captures microphone PCM and streams it via the public WebSocket
The frontend SHALL capture microphone audio as 16 kHz mono 16-bit PCM, encode it as base64, and send it to `backend` as `client_audio_chunk` events over the existing public WebSocket connection.

#### Scenario: Audio capture starts when Gemini Live mode is active
- **WHEN** the live runtime is configured in `gemini_live` mode and the user starts a live session
- **THEN** the frontend opens the microphone, captures 16 kHz mono PCM, and begins sending `client_audio_chunk` events at roughly 100 ms intervals

#### Scenario: Audio chunk event carries PCM payload
- **WHEN** the frontend sends a `client_audio_chunk` event
- **THEN** the event payload SHALL contain `audio_base64`, `sample_rate`, `mime_type`, and `timestamp`

#### Scenario: Audio capture stops when runtime stops
- **WHEN** the live runtime is stopped or disconnected
- **THEN** the frontend releases the microphone and stops sending `client_audio_chunk` events

### Requirement: Frontend signals end-of-speech with client_audio_end
The frontend SHALL send a `client_audio_end` event when the user stops speaking so Brain can complete the current Gemini Live turn.

#### Scenario: Speech end triggers client_audio_end
- **WHEN** VAD or silence detection determines the user has stopped speaking in `gemini_live` mode
- **THEN** the frontend sends `client_audio_end`

### Requirement: Backend relays audio events and Brain forwards realtimeInput to Gemini
The audio relay path SHALL be frontend -> backend -> brain -> Gemini, with backend forwarding the client event payload and brain translating it into Gemini Live `realtimeInput`.

#### Scenario: Audio chunk reaches Gemini through Brain
- **WHEN** backend receives `client_audio_chunk` for a `gemini_live` session
- **THEN** backend forwards it to Brain and Brain sends `{ "realtimeInput": { "mediaChunks": [...] } }` to Gemini Live

#### Scenario: Audio end completes the Gemini turn
- **WHEN** backend receives `client_audio_end` for a `gemini_live` session
- **THEN** backend forwards it to Brain and Brain signals `turnComplete` to Gemini Live

#### Scenario: Audio chunks during reconnect are dropped by Brain
- **WHEN** Brain receives relayed audio input while its Gemini transport is reconnecting
- **THEN** Brain silently drops the chunk without surfacing an error to the client

### Requirement: Browser ASR remains UI-only in Gemini Live mode
The frontend SHALL keep browser ASR active for local transcript display in `gemini_live` mode, but SHALL NOT submit ASR-derived `user_speak` events from that transcript stream.

#### Scenario: ASR text shown but not submitted
- **WHEN** browser ASR produces a transcript while in `gemini_live` mode
- **THEN** the transcript is displayed in the UI but no ASR-derived `user_speak` event is sent
