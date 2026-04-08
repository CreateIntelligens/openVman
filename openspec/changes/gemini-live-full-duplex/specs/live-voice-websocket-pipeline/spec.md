## ADDED Requirements

### Requirement: Backend WebSocket handler routes live traffic by session state
The backend `/ws/{client_id}` handler SHALL route live traffic based on whether a Brain live relay is active for the session, using the existing Brain SSE → TTS path when no relay exists and the relay path when one has been established by audio events.

#### Scenario: Audio events establish Brain relay
- **WHEN** the frontend sends `client_audio_chunk` for a session that has no Brain relay
- **THEN** the backend creates a Brain live relay for that session and forwards the audio event through it

#### Scenario: user_speak routes through active relay
- **WHEN** the frontend sends `user_speak` and a Brain live relay is already active for the session
- **THEN** the backend forwards the text turn to the Brain relay instead of invoking `LiveVoicePipeline`

#### Scenario: user_speak uses LiveVoicePipeline when no relay exists
- **WHEN** the frontend sends `user_speak` and no Brain live relay exists for the session
- **THEN** the backend uses `LiveVoicePipeline` (Brain SSE → TTS) as before

### Requirement: Backend relays audio client events to Brain
The backend `/ws/{client_id}` handler SHALL accept `client_audio_chunk` and `client_audio_end` events and SHALL forward them to the Brain live relay, creating the relay on first audio event if needed.

#### Scenario: Audio chunk forwarded to Brain relay
- **WHEN** the frontend sends `client_audio_chunk`
- **THEN** the backend ensures a Brain relay exists and forwards the event payload

#### Scenario: Audio end forwarded to Brain relay
- **WHEN** the frontend sends `client_audio_end`
- **THEN** the backend forwards the event payload to the Brain live relay so Brain can complete the Gemini turn

### Requirement: Backend relays Brain live server events back to the client
The backend SHALL relay streamed live events received from the Brain live relay back to the frontend over the public WebSocket.

#### Scenario: Streamed audio chunk passes through from Brain
- **WHEN** Brain emits `server_stream_chunk`
- **THEN** backend forwards that event to the frontend without changing its client-facing contract

#### Scenario: Brain interruption passes through
- **WHEN** Brain emits `server_stop_audio` or `server_error`
- **THEN** backend forwards the event to the frontend for the active client session

### Requirement: Interrupt forwards to Brain relay when active
The backend SHALL forward `client_interrupt` to the Brain live relay when one is active for the session, in addition to performing local task cancellation.

#### Scenario: Interrupt with active relay
- **WHEN** the frontend sends `client_interrupt` and a Brain relay is active
- **THEN** the backend cancels local tasks, forwards the interrupt to Brain, and sends `server_stop_audio` to the frontend

#### Scenario: Interrupt without relay
- **WHEN** the frontend sends `client_interrupt` and no Brain relay exists
- **THEN** the backend cancels local tasks and sends `server_stop_audio` without contacting Brain
