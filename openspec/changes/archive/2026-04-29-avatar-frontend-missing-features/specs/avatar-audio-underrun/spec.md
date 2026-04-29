## ADDED Requirements

### Requirement: Audio queue underrun protection
The frontend SHALL detect when the audio playback queue empties before the `is_final` flag is received on a `server_stream_chunk` event. When this condition occurs, the frontend SHALL start a 3-second watchdog timer. If `is_final` arrives within the timeout, the timer is cancelled and playback continues normally. If the timer expires without `is_final`, the frontend SHALL force-stop speaking state (clear lip-sync canvas, stop TTS) and transition to `IDLE`.

#### Scenario: Underrun detected — is_final arrives before timeout
- **WHEN** the audio queue empties while `is_final` has not yet been received AND a `server_stream_chunk` with `is_final = true` arrives within 3 seconds
- **THEN** the watchdog timer SHALL be cancelled and the normal utterance-complete flow SHALL proceed

#### Scenario: Underrun detected — timeout expires
- **WHEN** the audio queue empties while `is_final` has not yet been received AND 3 seconds pass without `is_final`
- **THEN** the frontend SHALL clear the lip-sync canvas, stop TTS streaming, and transition the avatar state to `IDLE`

#### Scenario: No underrun — is_final arrives before queue empties
- **WHEN** `is_final = true` is received while audio chunks are still playing
- **THEN** the frontend SHALL NOT start a watchdog timer and SHALL let the queue play to completion normally
