# Proposal: Replace IndexTTS with Microsoft VibeVoice (0.5B/1.5B)

## 1. Problem Statement
The current `IndexTTS` implementation is a "legacy heavyweight" in the project:
- **Latency**: Based on vLLM batching, resulting in >1s TTFT, which is unacceptable for a real-time virtual human.
- **Complexity**: Forced Traditional-to-Simplified Chinese conversion before synthesis degrades prosody.
- **Architecture**: It is a "monolithic container" anti-pattern, running multiple heavy processes (Redis, IndexTTS, FastAPI) in a single Docker container.
- **Expressiveness**: It lacks emotional micro-expressions and regional (Taiwanese) nuance.

## 2. Proposed Solution
Adopt Microsoft's `VibeVoice` family to modernize the synthesis pipeline:
- **Primary**: `VibeVoice-0.5B (Real-time)` for conversational interaction (<300ms latency).
- **Secondary**: `VibeVoice-1.5B` for high-fidelity content/podcasts.
- **Taiwanese Nuance**: Use 5-10s high-quality Taiwanese voice prompts as Reference Voices (Zero-shot) to bypass model-level training.
- **Decoupling**: Move TTS to a standalone `vibevoice-serve` service to allow independent resource management and scaling.

## 3. Goals
- [x] Reduce First Token Latency (TTFT) from >1s to <300ms.
- [x] Eliminate the `backend/index-tts-vllm/` directory (approx. 500MB+ source).
- [x] Simplify `backend/Dockerfile` and `start-backend-container.sh`.
- [x] Achieve human-like prosody with Taiwanese accent support.

## 4. Scope
- **Backend Removal**: Delete all code and dependencies related to `IndexTTS`.
- **Infrastructure**: Create a new `vibevoice-serve` Docker service.
- **Provider Layer**: Implement `VibeVoiceAdapter` in `backend/app/providers/`.
- **Router Logic**: Update `TTSRouterService` priority: `VibeVoice-0.5B` -> `VibeVoice-1.5B` -> `Edge-TTS`.
- **Reference Management**: Add a mechanism to store and inject Taiwanese voice reference prompts.

## 5. Risks & Mitigations
- **Resource Usage**: VibeVoice 1.5B requires ~8GB VRAM. 
  - *Mitigation*: Enable 0.5B as default; make 1.5B optional or dynamic based on available GPU memory.
- **Reference Quality**: Poor reference audio leads to poor output.
  - *Mitigation*: Curate a set of high-quality "Taiwanese Default" reference clips.
