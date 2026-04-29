## ADDED Requirements

### Requirement: ASR voice input via SpeechRecognition API
The frontend SHALL provide a microphone button that activates the browser's `SpeechRecognition` (or `webkitSpeechRecognition`) API for voice input. The button SHALL only be rendered when `SpeechRecognition` is available in the browser. When a final recognition result is received, the frontend SHALL send a `user_speak` WebSocket event with the recognized text, identical to the text-input flow.

#### Scenario: Browser supports SpeechRecognition
- **WHEN** the avatar frontend loads on a browser that exposes `SpeechRecognition` or `webkitSpeechRecognition`
- **THEN** an ASR microphone button SHALL be visible in the chat input area

#### Scenario: Browser does not support SpeechRecognition
- **WHEN** the avatar frontend loads on a browser that does not expose `SpeechRecognition`
- **THEN** the ASR microphone button SHALL NOT be rendered, and text input remains the only option

#### Scenario: ASR activated while IDLE
- **WHEN** the user clicks the microphone button while the avatar state is `IDLE` or `DISCONNECTED`
- **THEN** `SpeechRecognition.start()` SHALL be called and the button SHALL show an active/listening indicator

#### Scenario: Final recognition result triggers user_speak
- **WHEN** `SpeechRecognition.onresult` fires with a final result containing non-empty text
- **THEN** the frontend SHALL stop ASR, call `chat.sendMessage(text)` with the recognized text, and transition to `THINKING`

#### Scenario: ASR automatically paused during THINKING or SPEAKING
- **WHEN** the avatar state changes to `THINKING` or `SPEAKING`
- **THEN** the frontend SHALL stop the active ASR session to prevent TTS audio from being misrecognized

#### Scenario: ASR restarts after SPEAKING returns to IDLE
- **WHEN** the avatar state transitions from `SPEAKING` back to `IDLE` and ASR was previously active
- **THEN** the frontend SHALL automatically restart ASR listening

#### Scenario: ASR error handling
- **WHEN** `SpeechRecognition.onerror` fires
- **THEN** the ASR session SHALL be stopped, the button SHALL return to inactive state, and no `user_speak` event SHALL be sent
