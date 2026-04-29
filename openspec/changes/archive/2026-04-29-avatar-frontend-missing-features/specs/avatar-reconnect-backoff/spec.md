## ADDED Requirements

### Requirement: Exponential backoff WebSocket reconnection
The frontend SHALL use an exponential backoff strategy when the WebSocket connection closes unexpectedly. The delay between reconnection attempts SHALL follow `min(1000 × 2^attempt, 30000)` milliseconds. The attempt counter SHALL reset to zero upon a successful connection.

#### Scenario: First reconnection attempt
- **WHEN** the WebSocket closes unexpectedly and no previous reconnection has been attempted
- **THEN** the frontend SHALL wait 1000 ms before the first reconnection attempt

#### Scenario: Successive reconnection attempts
- **WHEN** repeated reconnection attempts fail
- **THEN** each subsequent delay SHALL double the previous delay until the maximum of 30000 ms is reached

#### Scenario: Maximum delay cap
- **WHEN** the calculated delay exceeds 30000 ms
- **THEN** the frontend SHALL cap the delay at 30000 ms and retry at that interval

#### Scenario: Successful reconnection resets counter
- **WHEN** a reconnection attempt succeeds and the WebSocket `onopen` fires
- **THEN** the attempt counter SHALL be reset to zero so the next disconnection starts from 1000 ms again

#### Scenario: Reconnecting status shown to user
- **WHEN** the frontend is waiting to reconnect
- **THEN** the avatar state SHALL remain `DISCONNECTED` and the control bar SHALL reflect the disconnected state, giving the user a visual cue
