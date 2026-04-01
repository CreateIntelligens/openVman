# Tasks: Replace IndexTTS with VibeVoice

## Phase 1: Cleanup (The "Excision")
- [x] 1.1 Delete `backend/index-tts-vllm/` directory.
- [x] 1.2 Remove Index-TTS dependencies from `backend/Dockerfile` and `backend/requirements.txt`.
- [x] 1.3 Cleanup `backend/app/config.py` (remove `tts_index_*` fields).
- [x] 1.4 Delete `backend/app/providers/index_tts_adapter.py` and related tests.

## Phase 2: Infrastructure (Standalone Service)
- [x] 2.1 Create `backend/vibevoice-serve/` Docker setup (using Microsoft's reference implementation).
- [x] 2.2 Update `docker-compose.yml` to include `vibevoice-serve` as a standalone service.
- [x] 2.3 Refactor `backend/docker/start-backend-container.sh` to remove Redis/TTS startup logic (move Redis to its own service too).
- [x] 2.4 Verify network connectivity between `backend` and `vibevoice-serve`.

## Phase 3: Backend Implementation
- [x] 3.1 Implement `VibeVoiceAdapter` in `backend/app/providers/vibevoice_adapter.py`.
- [x] 3.2 Add "Reference Voice" loading logic to the adapter.
- [x] 3.3 Update `TTSRouterService` to prioritize VibeVoice-0.5B.
- [x] 3.4 Add `VibeVoiceHTTPError` to `error_mapping.py`.

## Phase 4: Prosody & Accent Optimization
- [x] 4.1 Collect 3-5 high-quality Taiwanese voice reference clips (Female/Male/Child).
- [x] 4.2 Test Zero-shot cloning performance with Traditional Chinese text.
- [x] 4.3 Fine-tune synthesis parameters (temperature, top_p) for Taiwanese Mandarin prosody.

## Phase 5: Validation & Benchmarking
- [x] 5.1 Benchmark First Token Latency (TTFT) for 0.5B model.
- [x] 5.2 Verify fallback chain: `VibeVoice-0.5B` -> `VibeVoice-1.5B` -> `Edge-TTS`.
- [x] 5.3 Conduct "blind test" for Taiwanese accent authenticity.
- [x] 5.4 Ensure GPU memory stability under concurrent requests.
