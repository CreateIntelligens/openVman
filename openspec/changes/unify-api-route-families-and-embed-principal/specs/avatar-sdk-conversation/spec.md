## ADDED Requirements

### Requirement: Conversation options on the single SDK bundle
The `openvman-avatar-sdk.js` bundle SHALL accept `embedKey`, `projectId`, `personaId`, and `tts: { provider?, voice? }` in `init` options in addition to the existing options, and SHALL keep host-provided audio (`playAudio`, `pushPcm`) working unchanged when none of the new options are supplied. There SHALL be no separate conversation bundle.

#### Scenario: Legacy host unchanged
- **WHEN** a host calls `init({ characterId })` and then `playAudio(blob)`
- **THEN** behaviour is identical to the keyless SDK and no chat or speech request is made

#### Scenario: Options are part of the instance signature
- **WHEN** a host calls `init` twice with different `projectId` or `embedKey`
- **THEN** the second call is rejected with `INSTANCE_EXISTS` as for any other differing option

### Requirement: ask(text) runs a full turn
An instance SHALL provide `ask(text): Promise<string>` that sends the text to `POST /api/v1/chat` with the instance's `project_id`, `persona_id`, and a per-instance `session_id`, emits a `reply` event with the answer text, requests `POST /v1/audio/speech` with the configured provider and voice, and plays the returned audio through the runtime. The promise SHALL resolve with the reply text once playback has finished or been interrupted; hosts that need the start of speech use the `speaking` event.

#### Scenario: Keyed host
- **WHEN** `init` received `embedKey` and the host calls `ask("你好")`
- **THEN** both requests carry `X-Embed-Key` and no credentials, the `reply` event fires with the answer, and the avatar speaks it

#### Scenario: Same-origin session host
- **WHEN** `init` received no `embedKey` and the host page has a session cookie
- **THEN** both requests are sent with `credentials: "include"` and behave as above

#### Scenario: Conversation continuity
- **WHEN** the host calls `ask` several times on one instance
- **THEN** every chat request reuses the same `session_id`

#### Scenario: Interrupt
- **WHEN** the host calls `ask` while a previous answer is still playing
- **THEN** the previous playback is interrupted before the new turn starts

### Requirement: Conversation errors are named
`ask` SHALL reject with `OpenVmanAvatarError` codes `UNAUTHORIZED` for 401 or 403, `RATE_LIMITED` for 429 (carrying `retryAfterSeconds` when the header is present), `CHAT_FAILED` for other chat failures, and `SPEECH_FAILED` for speech failures, and SHALL emit the same error through the `error` event.

#### Scenario: Revoked key
- **WHEN** the chat request returns 401
- **THEN** `ask` rejects with `UNAUTHORIZED` and no speech request is made

#### Scenario: Quota exhausted
- **WHEN** the chat request returns 429 with `Retry-After: 30`
- **THEN** `ask` rejects with `RATE_LIMITED` and `retryAfterSeconds = 30`

### Requirement: Silent instances can still converse
When the instance was created with `audioOutput: "silent"`, `ask` SHALL still drive lip sync through the runtime and resolve normally, so a host that owns audio playback can also delegate the conversation.

#### Scenario: Silent ask
- **WHEN** a silent instance calls `ask`
- **THEN** the runtime receives the synthesized audio for lip sync and no sound is emitted by the SDK
