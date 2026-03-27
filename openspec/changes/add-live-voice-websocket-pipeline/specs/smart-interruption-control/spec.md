## ADDED Requirements

### Requirement: Interruption is evaluated as a backend control decision
The system SHALL treat `client_interrupt` as a control signal that is classified by a lightweight Backend Guard Agent before any live pipeline teardown occurs.

#### Scenario: Noise-like interruption is ignored
- **WHEN** the frontend sends `client_interrupt` with ASR text that the Guard Agent classifies as ignorable
- **THEN** the backend keeps the current response pipeline active and does not stop audio or create a new Brain turn

#### Scenario: Valid interruption stops the active response
- **WHEN** the frontend sends `client_interrupt` with ASR text that the Guard Agent classifies as a real interruption
- **THEN** the backend stops in-flight speech output, aborts the active Brain/TTS work, and emits `server_stop_audio`

#### Scenario: Early speech start can interrupt before transcript stabilization
- **WHEN** the frontend emits `client_interrupt` because browser-side turn detection has identified speech start before a final transcript exists
- **THEN** the backend still evaluates the event as interruption control and does not require a formal `user_speak` payload first

### Requirement: Formal conversation input remains separate from interruption control
The system SHALL keep `client_interrupt` separate from `user_speak`, and only `user_speak` SHALL create a new formal Brain input turn.

#### Scenario: Partial ASR does not create a Brain turn
- **WHEN** the frontend sends `client_interrupt` with `partial_asr`
- **THEN** the backend does not forward that control event to Brain as a formal user message

#### Scenario: Final ASR creates the new turn after interruption
- **WHEN** the frontend later sends `user_speak` with stabilized text after an interruption
- **THEN** the backend starts a new Brain streaming turn using that `user_speak` payload
