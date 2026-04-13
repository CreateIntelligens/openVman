## 1. Backend: client_init voice_source support

- [x] 1.1 Read `capabilities.voice_source` from `client_init` data in `_handle_client_init` and store on session (default `"gemini"`)
- [x] 1.2 Pass stored `voice_source` to `BrainLiveRelay` constructor (or setter) when relay is created in `_ensure_brain_relay`

## 2. Backend: Unified user_speak routing

- [x] 2.1 In `_handle_user_speak`, call `_ensure_brain_relay` before sending to Brain when in Live mode, removing the `LiveVoicePipeline` fallback branch
- [x] 2.2 Verify `user_speak` text-only input works without prior `client_audio_chunk`

## 3. Backend: BrainLiveRelay TTS intercept

- [x] 3.1 Add `voice_source` parameter to `BrainLiveRelay.__init__` and store as instance attribute
- [x] 3.2 Add `TTSRouterService` dependency to `BrainLiveRelay` (import + inject via constructor or lazy init)
- [x] 3.3 In `_listen`, when `voice_source == "custom"` and event is `server_stream_chunk`: extract `text`, discard `audio_base64`, enqueue for TTS synthesis
- [x] 3.4 Implement async queue + worker for TTS synthesis using `run_in_executor` to avoid blocking the listener
- [x] 3.5 On TTS failure, emit `server_stream_chunk` with text intact and empty `audio_base64`

## 4. Frontend: useLiveSession voiceSource parameter

- [x] 4.1 Add `voiceSource` parameter to `useLiveSession` options (`"gemini"` | `"custom"`, default `"gemini"`)
- [x] 4.2 Include `voice_source` in `client_init` capabilities payload
- [x] 4.3 Trigger disconnect + reconnect when `voiceSource` prop changes

## 5. Frontend: Voice source toggle UI

- [x] 5.1 Add `voiceSource` state to `Chat.tsx` (default `"gemini"`)
- [x] 5.2 Pass `voiceSource` to `useLiveSession` hook
- [x] 5.3 Add voice source selector (pill toggle or Select) in Live status bar, visible only in Live mode
- [x] 5.4 On selector change, update state (reconnect handled automatically by hook)

## 6. Testing

- [x] 6.1 Backend unit test: `_handle_client_init` stores `voice_source` from capabilities
- [x] 6.2 Backend unit test: `_handle_user_speak` in Live mode always goes through `BrainLiveRelay`
- [x] 6.3 Backend unit test: `BrainLiveRelay` passthrough when `voice_source == "gemini"`
- [x] 6.4 Backend unit test: `BrainLiveRelay` TTS intercept when `voice_source == "custom"`
- [x] 6.5 Backend unit test: TTS failure fallback emits text with empty audio
- [x] 6.6 Frontend: verify `client_init` payload includes `voice_source` in capabilities
