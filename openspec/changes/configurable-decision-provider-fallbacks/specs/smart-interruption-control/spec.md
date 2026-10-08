# Spec Delta

## MODIFIED Requirements

### Requirement: Interruption is evaluated as a backend control decision
The system SHALL treat `client_interrupt` as a control signal classified by the local Backend Guard Agent before pipeline teardown. The Guard Agent SHALL use the configured decision-provider chain only when local rules cannot classify the transcript, and SHALL use the existing conservative stop behavior if the chain fails.

#### Scenario: Noise-like interruption is ignored
- **WHEN** the frontend sends `client_interrupt` with ASR text that the Guard Agent classifies as ignorable
- **THEN** the backend keeps the current response pipeline active and does not stop audio or create a new Brain turn

#### Scenario: Valid interruption stops the active response
- **WHEN** the frontend sends `client_interrupt` with ASR text that the Guard Agent classifies as a real interruption
- **THEN** the backend stops in-flight speech output, aborts the active Brain/TTS work, and emits `server_stop_audio`

#### Scenario: Uncertain interruption uses decision providers
- **WHEN** local rules cannot classify an interruption transcript
- **THEN** the Guard Agent asks the configured decision-provider chain to classify it within the interruption deadline
- **THEN** it uses the returned valid decision and records the provider used

#### Scenario: Decision chain fails for an interruption
- **WHEN** every configured provider fails, refuses, or exceeds the interruption deadline
- **THEN** the Guard Agent preserves its existing conservative stop behavior

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
