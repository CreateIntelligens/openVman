## ADDED Requirements

### Requirement: Frontend live runtime supports gemini_live audio streaming mode
The frontend live runtime SHALL support a `gemini_live` mode where microphone PCM is streamed directly to the existing public backend WebSocket instead of relying solely on ASR text submission.

#### Scenario: Gemini Live mode starts audio streaming
- **WHEN** the live runtime is initialized with mode `gemini_live`
- **THEN** it starts `AudioStreamer` to capture and send `client_audio_chunk` events to backend alongside the existing ASR/VAD services

#### Scenario: Speech end in Gemini Live mode sends audio_end instead of user_speak
- **WHEN** VAD detects speech end in `gemini_live` mode
- **THEN** the runtime sends `client_audio_end` instead of `user_speak`

#### Scenario: Typed text input still works in Gemini Live mode
- **WHEN** the user types text via chat input while in `gemini_live` mode
- **THEN** the runtime sends `user_speak` with the typed text (text fallback path)

### Requirement: AudioStreamer captures 16 kHz mono PCM via AudioWorklet
The frontend SHALL provide an `AudioStreamer` service that captures microphone audio at 16 kHz mono 16-bit PCM using AudioWorklet, with ScriptProcessorNode fallback.

#### Scenario: AudioWorklet captures and sends PCM chunks
- **WHEN** `AudioStreamer.start()` is called and the browser supports AudioWorklet
- **THEN** it captures 16 kHz mono PCM and invokes the configured send callback every ~100ms with a base64-encoded chunk

#### Scenario: Fallback to ScriptProcessorNode
- **WHEN** AudioWorklet is not supported by the browser
- **THEN** `AudioStreamer` uses ScriptProcessorNode to capture equivalent PCM chunks

#### Scenario: AudioStreamer releases resources on stop
- **WHEN** `AudioStreamer.stop()` is called
- **THEN** the microphone MediaStream tracks are stopped and AudioContext is closed
