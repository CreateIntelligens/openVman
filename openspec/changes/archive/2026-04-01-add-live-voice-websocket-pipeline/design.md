## Context

The current codebase already contains the main ingredients for live voice interaction, but they are fragmented across layers. `frontend/app` has browser ASR and lip-sync service skeletons, `brain/api` can stream tokens over SSE, and `backend/app` can synthesize audio through `VibeVoiceAdapter` (VibeVoice-0.5B). The existing `/ws/{client_id}` handler is still a placeholder, the shared protocol is missing live control events, and frontend runtime wiring is incomplete.

Recently added documentation at `docs/00_SYSTEM_ARCHITECTURE.md` and `docs/09_API_WS_LINKAGE.md` already moves the repository toward the same layered model, but those docs still need live-interruption-specific alignment. This change should treat them as upstream architectural references, keep any implementation-critical clarifications in local planning/OpenSpec artifacts, and leave owner-maintained doc synchronization as a follow-up instead of a delivery blocker.

This change crosses multiple modules and requires explicit architectural decisions because it touches control flow, streaming behavior, protocol contracts, and interruption semantics. The core constraint is to keep cognition in Brain, fast reaction in Backend, and rendering/input in Frontend without duplicating responsibility across layers.

## Goals / Non-Goals

**Goals:**
- Build a single live session path from browser ASR through backend orchestration to Brain token streaming and sentence-level TTS output.
- Add browser-side turn detection so the frontend can react on speech start and auto-submit on speech end plus silence.
- Keep `client_interrupt` as a control signal evaluated quickly by Backend rather than turning it into a new Brain chat turn.
- Make `user_speak` the only formal text input sent to Brain for response generation.
- Keep lip-sync audio-driven on the frontend and avoid requiring viseme generation from Backend.
- Align the shared protocol so handshake, stop-audio control, lip-sync mode signaling, and interruption semantics are explicitly defined.

**Non-Goals:**
- Replacing browser ASR with a separate cloud or local STT provider in this change.
- Adding server-side VAD.
- Adding a public Brain cancellation protocol such as `INTERNAL_CANCEL` over WebSocket.
- Streaming provider-native audio frames from TTS; this change uses sentence-level chunked TTS results.
- Moving lip-sync rendering to Backend or streaming mouth image patches/video frames.

## Decisions

### Decision: Browser ASR remains in Frontend

Frontend SHALL continue to perform speech recognition locally in the browser and send text/control events over WebSocket.

Rationale:
- It matches the existing architectural direction and current frontend code.
- It gives the frontend immediate visibility into user speech for barge-in behavior.
- It keeps microphone capture and local playback in the same runtime.

Alternatives considered:
- Backend STT as the primary path: more uniform across browsers, but adds more transport complexity and is not needed to land the first live pipeline.

### Decision: Frontend uses layered turn detection with true VAD first and ASR silence fallback second

Frontend SHALL detect speech turn boundaries locally. When browser-side true VAD is available, it SHALL use VAD speech start and speech end signals as the primary trigger. When true VAD is unavailable or fails to initialize, the frontend SHALL fall back to ASR transcript inactivity and silence timers.

Rationale:
- It improves barge-in latency because interruption can fire on speech start instead of waiting for ASR text stabilization.
- It keeps the frontend usable across browsers where VAD support or assets are unavailable.
- It avoids coupling microphone turn detection to backend orchestration.

Alternatives considered:
- ASR inactivity only: simpler, but too slow and too dependent on transcript cadence for good interruption UX.
- True VAD only: cleaner signal quality, but weaker browser coverage and a riskier rollout.

### Decision: Backend Guard Agent is the first interruption judge

Backend SHALL use a lightweight Guard Agent to classify `client_interrupt` as either ignorable noise or a real interruption.

Rationale:
- It is much faster and cheaper than routing every interruption through the main Brain LLM.
- It fits Backend's role as the nervous-system/reflex layer.
- It keeps the Brain focused on response generation rather than interruption control.

Alternatives considered:
- Main Brain LLM as the interruption judge: more stylistically consistent, but slower and riskier under concurrency.

### Decision: `client_interrupt` and `user_speak` are separate event classes

`client_interrupt` SHALL remain a control event and SHALL NOT directly create a new Brain turn. `user_speak` SHALL be the only formal user message that enters Brain.

Rationale:
- Control and conversation are different concerns and need different latency and validation semantics.
- This prevents half-stable ASR fragments from polluting chat history or prompt state.
- It lets Frontend interrupt playback immediately, then send the final stabilized utterance as a later formal turn.

Alternatives considered:
- Treat interruption text as the next chat input immediately: simpler on paper, but couples noisy partial ASR to Brain state and increases false-positive turn creation.

### Decision: Auto-send waits for silence and stabilized transcript text

Frontend SHALL accumulate interim/final transcript state locally and SHALL submit one formal `user_speak` turn only after the current speech turn ends and the configured silence window expires with non-empty transcript text.

Rationale:
- It preserves the existing backend contract that `user_speak` is a formal user turn.
- It avoids splitting one utterance across multiple Brain turns.
- It lets VAD-driven interruption stay fast while final text submission remains stable.

Alternatives considered:
- Submit on every final ASR chunk: risks fragmenting one spoken utterance into several messages.
- Submit immediately on speech end: brittle because ASR finalization can lag slightly behind speech end.

### Decision: Brain streams tokens, Backend owns chunking and TTS

Brain SHALL stream tokens only. Backend SHALL convert token streams into sentence chunks, synthesize TTS per chunk, and emit `server_stream_chunk` payloads.

Rationale:
- Brain remains purely cognitive and does not need TTS-specific punctuation or audio concerns.
- Backend already owns provider routing, interruption cleanup, and session state.
- Sentence-level chunking is enough to achieve usable low-latency speech without requiring provider-native audio streaming.

Alternatives considered:
- Brain performs sentence chunking: mixes cognition and media orchestration.
- TTS waits for the entire answer: too much latency for a live experience.

### Decision: Audio-driven lip-sync stays in Frontend

Frontend SHALL drive lip-sync from the received audio timeline. Backend SHALL not be responsible for viseme generation or face-frame streaming in this change.

Rationale:
- This matches the existing DINet/Wav2Lip/WebGL direction.
- It reduces backend bandwidth and compute demands.
- It keeps `server_stream_chunk` focused on text plus audio.

Alternatives considered:
- Backend-generated visemes: currently misaligned with project direction and shared docs.
- Backend-generated mouth frames/video patches: more complex transport and out of scope for the first live pipeline.

### Decision: Add `server_stop_audio` to the shared protocol, but no public `INTERNAL_CANCEL`

The shared contract SHALL include a `server_stop_audio` event so frontend playback reset is first-class. Backend MAY abort Brain tasks internally, but there SHALL be no public `INTERNAL_CANCEL` event in the frontend/backend protocol.

Rationale:
- Frontend already needs a formal stop-audio signal.
- Internal cancellation is an implementation detail of backend orchestration, not a public cross-layer contract.

Alternatives considered:
- Exposing a public cancellation event to Brain or Frontend: leaks internals and complicates the contract without improving the user-facing protocol.

## Risks / Trade-offs

- **False-positive interruption classification** → Mitigation: start with a conservative lightweight guard and keep the protocol split so only `user_speak` mutates Brain state.
- **Sentence-level TTS may still feel slower than native realtime audio** → Mitigation: chunk on punctuation early, keep chunk sizes short, and measure `user_speak -> first chunk` latency.
- **Protocol drift across Python and TypeScript validators** → Mitigation: make schema generation part of verification and keep admin validators aligned with generated artifacts.
- **Frontend runtime complexity increases because app shell is currently missing** → Mitigation: land a minimal shell first, then wire playback and ASR incrementally.
- **Browser ASR behavior varies by environment** → Mitigation: keep ASR isolated to Frontend and avoid coupling it to backend protocol semantics beyond `client_interrupt` and `user_speak`.
- **VAD startup cost or browser incompatibility may delay voice capture** → Mitigation: feature-detect true VAD, initialize it lazily, and preserve ASR silence fallback.
- **False interruption from microphone noise** → Mitigation: require VAD speech-start confidence or minimal speech duration and keep thresholds configurable.

## Migration Plan

1. Create and validate the shared live protocol updates.
2. Land backend orchestration with Guard Agent, session state, and sentence-level TTS emission.
3. Add the frontend runtime shell and wire browser ASR, browser-side turn detection, silence auto-send, playback queue, and lip-sync.
4. Add heartbeat, error normalization, metrics, and verification steps.
5. Capture any remaining drift against owner-maintained architecture/linkage docs as a handoff follow-up, without blocking implementation on those edits.
6. Roll back by disabling the live frontend runtime path and falling back to the current non-live skeleton if phase verification fails.

## Open Questions

- Whether browser ASR quality is sufficient for the target kiosk environment, or a later provider-backed STT phase is needed.
- Whether true VAD should land first only in `frontend/app`, or also be mirrored into `frontend/admin` after the live runtime is in place.
- Whether `server_stop_audio` should carry only `session_id` and timestamp, or also an optional reason field in a future change.
- Whether the lightweight Guard Agent should remain deterministic/rule-based or later move to a tiny model with the same protocol semantics.
