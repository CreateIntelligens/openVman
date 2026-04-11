## ADDED Requirements

### Requirement: Brain owns one persistent Gemini Live transport per relayed live session
The Brain service SHALL maintain a single Gemini Live WebSocket connection per relayed live session, and that connection SHALL be reused across multiple turns until the relay session ends or the transport is explicitly closed.

#### Scenario: First turn establishes Brain-owned persistent connection
- **WHEN** the first `user_speak` or `client_audio_chunk` arrives through the backend relay for a session
- **THEN** Brain opens a Gemini Live WebSocket, sends setup, waits for `setupComplete`, and stores the transport in Brain session state

#### Scenario: Subsequent turns reuse the existing Brain transport
- **WHEN** a later text turn or audio turn arrives for the same relayed session
- **THEN** Brain sends it on the already-established Gemini transport without reconnecting or re-sending setup

#### Scenario: Relay disconnect closes the Brain Gemini transport
- **WHEN** the backend-to-brain live relay disconnects for a session
- **THEN** Brain closes the associated Gemini transport and releases its resources

### Requirement: Brain-owned Gemini transport auto-reconnects on unexpected close
The Brain service SHALL automatically reconnect the Gemini Live WebSocket when it closes unexpectedly, using exponential backoff with jitter, and SHALL re-send setup on successful reconnect.

#### Scenario: Unexpected close triggers reconnect with backoff
- **WHEN** the Gemini Live WebSocket closes with an error
- **THEN** Brain retries connection with delays of 1s, 2s, 4s, 8s, and 16s with jitter, re-runs setup on success, and resumes normal operation

#### Scenario: Max retries exceeded emits upstream error
- **WHEN** reconnection fails after 5 consecutive attempts
- **THEN** Brain emits a `server_error` event upstream to backend and stops retrying

#### Scenario: Reconnect during active turn clears stale audio
- **WHEN** the Gemini transport drops while a response is in progress
- **THEN** Brain emits `server_stop_audio` upstream before attempting reconnect

### Requirement: Brain-owned Gemini session executes tools using existing Brain search and memory flows
Tool calling for Gemini Live SHALL be executed inside Brain using the same Brain-owned knowledge and memory access paths as other LLM features.

#### Scenario: Knowledge tool call uses Brain search
- **WHEN** Gemini Live issues a `search_knowledge` function call
- **THEN** Brain resolves it using Brain-owned search/memory infrastructure and returns the tool result to Gemini

#### Scenario: Memory tool call uses Brain memory context
- **WHEN** Gemini Live issues a `search_memory` function call
- **THEN** Brain resolves it using the current session/project/persona context inside Brain

### Requirement: Brain sends keepalive to prevent Gemini idle timeout
The Brain service SHALL send a periodic keepalive on the Gemini Live transport while the relay session remains active.

#### Scenario: Keepalive on idle live session
- **WHEN** no user turn has been sent for 10 minutes on an active relayed Gemini session
- **THEN** Brain sends a lightweight keepalive message and keeps the Gemini session alive when possible
